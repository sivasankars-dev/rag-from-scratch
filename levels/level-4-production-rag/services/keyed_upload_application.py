"""Keyed upload application boundary: one synchronous worker, no Session input."""
from functools import partial
import anyio
from app.database import create_claim_session_factory
from services.upload_claim_service import claim_upload, ClaimOutcome
from services.upload_idempotency import fingerprint_pdf_upload
from services.upload_recovery_service import recover_upload, RecoveryOutcome
from services.fenced_upload_service import execute_claimed_upload
from services.verified_recovery_service import execute_recovery_upload
from services.upload_http_contract import normalize_upload_result
from services.upload_validator import UploadValidationError, FileTooLargeError, MAX_FILE_SIZE, validate_pdf_extension


def _execute(*, engine, storage, principal, idempotency_key, title, source, size_bytes):
    factory = create_claim_session_factory(engine)  # Sessions created only inside this worker.
    try:
        try:
            validate_pdf_extension(title)
            if type(size_bytes) is int and size_bytes > MAX_FILE_SIZE:
                raise FileTooLargeError("File too large")
            source.seek(0)
            if source.read(5) != b"%PDF-":
                raise UploadValidationError("Invalid PDF signature")
            fingerprint = fingerprint_pdf_upload(source=source, size_bytes=size_bytes, title=title)
            from services.upload_claim_service import _validate
            _validate(idempotency_key, title, fingerprint)
        except UploadValidationError:
            raise
        except ValueError as exc:
            raise UploadValidationError("Invalid keyed upload metadata") from exc
        decision = claim_upload(session_factory=factory, tenant_id=principal.tenant_id,
            user_id=principal.user_id, idempotency_key=idempotency_key, title=title, fingerprint=fingerprint)
        common = dict(session_factory=factory, storage=storage, tenant_id=principal.tenant_id,
                      user_id=principal.user_id, fingerprint=fingerprint, title=title)
        if decision.outcome == ClaimOutcome.CLAIMED:
            return normalize_upload_result(execute_claimed_upload(**common, claim=decision.claim, source=source))
        if decision.outcome == ClaimOutcome.RECOVERY_REQUIRED:
            recovery = recover_upload(session_factory=factory, tenant_id=principal.tenant_id,
                                      user_id=principal.user_id, operation_id=decision.operation.operation_id)
            if recovery.outcome == RecoveryOutcome.CLAIMED:
                return normalize_upload_result(execute_recovery_upload(**common, claim=recovery.claim, retry_source=source))
            return normalize_upload_result(recovery)
        return normalize_upload_result(decision)
    except Exception as exc:
        return normalize_upload_result(exc)


async def execute_keyed_upload(**kwargs):
    """Caller exclusively lends the validated upload stream until await completes.

    AnyIO's non-abandoning worker boundary keeps the stream alive through task
    cancellation. No Session/ORM instances are accepted; engine, immutable
    principal, storage adapter and caller-owned stream are the only resources.
    No automatic retry of uncertainty. Router selects the keyed dependency graph before invoking this boundary.
    """
    return await anyio.to_thread.run_sync(partial(_execute, **kwargs), abandon_on_cancel=False)
