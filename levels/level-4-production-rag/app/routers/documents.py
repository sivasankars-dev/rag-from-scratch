from uuid import UUID
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.routing import APIRoute
from starlette.middleware.body_limit import RequestBodyLimitMiddleware
from starlette.types import Receive, Scope, Send
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


# Bound multipart spooling too, allowing 1 MiB for encoding/extra fields.
MAX_UPLOAD_BODY_SIZE = MAX_FILE_SIZE + 1024 * 1024


class BoundedUploadRoute(APIRoute):
    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        bounded_handler = RequestBodyLimitMiddleware(
            super().handle, max_body_size=MAX_UPLOAD_BODY_SIZE,
        )
        await bounded_handler(scope, receive, send)


router = APIRouter(
    prefix="/tenants/{tenant_id}/documents",
    tags=["documents"],
    route_class=BoundedUploadRoute,
)


@router.post("/upload")
async def upload_document(
    tenant_id: UUID,
    file: UploadFile = File(...),
    principal: TenantPrincipal = Depends(get_current_tenant_member),
):
    try:
        file_size = await validate_pdf_upload(file)

    except FileTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except UploadValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "validated",
        "tenant_id": str(principal.tenant_id),
        "user_id": str(principal.user_id),
        "filename": file.filename,
        "size_bytes": file_size,
    }
