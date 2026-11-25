from uuid import UUID
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Header, Request
from fastapi.routing import APIRoute
from starlette.middleware.body_limit import RequestBodyLimitMiddleware
from starlette.types import Receive, Scope, Send
from sqlalchemy.orm import Session
from app.tenant_auth import (
    TenantPrincipal,
    get_current_tenant_member,
)
from services.upload_validator import (
    MAX_FILE_SIZE,
    FileTooLargeError,
    UploadValidationError,
    validate_pdf_upload,
)
from app.dependencies import get_db_session, get_document_storage
from services.document_storage import DocumentStorage
from services.document_upload_service import persist_document_upload
from app.keyed_upload_auth import get_keyed_upload_principal
from services.keyed_upload_application import execute_keyed_upload
from services.upload_http_contract import HttpOutcome
from fastapi.responses import JSONResponse
from dataclasses import asdict
from fastapi.encoders import jsonable_encoder


# Bound multipart spooling too, allowing 1 MiB for encoding/extra fields.
MAX_UPLOAD_BODY_SIZE = MAX_FILE_SIZE + 1024 * 1024


class BoundedUploadRoute(APIRoute):
    def get_route_handler(self):
        legacy = super().get_route_handler()
        if self.endpoint.__name__ != "upload_document":
            return legacy
        # Select dependency graph BEFORE FastAPI resolves it. The keyed graph
        # must never instantiate legacy request-scoped auth/database dependencies.
        keyed = APIRoute(self.path, keyed_upload_document, methods=self.methods).get_route_handler()
        async def dispatch(request):
            if "idempotency-key" in request.headers:
                return await keyed(request)
            return await legacy(request)
        return dispatch

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        bounded_handler = RequestBodyLimitMiddleware(
            super().handle, max_body_size=MAX_UPLOAD_BODY_SIZE,
        )
        await bounded_handler(scope, receive, send)


async def keyed_upload_document(
    request: Request,
    file: UploadFile = File(...),
    principal: TenantPrincipal = Depends(get_keyed_upload_principal),
    storage: DocumentStorage = Depends(get_document_storage),
):
    keys = request.headers.getlist("idempotency-key")
    # One opaque printable ASCII key, no trimming/normalization. Presence of an
    # invalid header never falls back to non-idempotent F01 behavior.
    if (len(keys) != 1 or not 1 <= len(keys[0]) <= 255
        or not keys[0].strip() or any(ord(c) < 33 or ord(c) > 126 for c in keys[0])):
        return JSONResponse({"detail": {"code": "invalid_request"}}, status_code=400)
    try:
        size = await validate_pdf_upload(file)
    except FileTooLargeError:
        return JSONResponse({"detail": {"code": "too_large"}}, status_code=413)
    except UploadValidationError:
        return JSONResponse({"detail": {"code": "invalid_request"}}, status_code=400)
    # FastAPI owns UploadFile lifetime; the non-abandoning worker is awaited
    # before this handler returns and the multipart exit stack closes the file.
    result = await execute_keyed_upload(
        engine=request.app.state.db_engine, storage=storage, principal=principal,
        idempotency_key=keys[0], title=file.filename, source=file.file, size_bytes=size,
    )
    if result.outcome == HttpOutcome.COMPLETED:
        return JSONResponse(jsonable_encoder(asdict(result.replay)), status_code=200)
    headers = {"Retry-After": str(result.retry_after)} if result.retry_after is not None else None
    return JSONResponse({"detail": {"code": result.outcome.value}}, status_code=result.status_code, headers=headers)


router = APIRouter(
    prefix="/tenants/{tenant_id}/documents",
    tags=["documents"],
    route_class=BoundedUploadRoute,
)


@router.post("/upload")
async def upload_document(
    tenant_id: UUID,
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key",
        description="Optional opaque printable ASCII key, 1–255 characters; no whitespace."),
    principal: TenantPrincipal = Depends(get_current_tenant_member),
    session: Session = Depends(get_db_session),
    storage: DocumentStorage = Depends(get_document_storage),
):
    try:
        file_size = await validate_pdf_upload(file)

    except FileTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except UploadValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        document, version = persist_document_upload(
            session=session,
            storage=storage,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            title=file.filename,
            source=file.file,
        )
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Document upload failed",
        )

    return {
        "status": "uploaded",
        "document_id": str(document.id),
        "version_id": str(version.id),
        "tenant_id": str(principal.tenant_id),
        "filename": file.filename,
        "size_bytes": file_size,
    }
