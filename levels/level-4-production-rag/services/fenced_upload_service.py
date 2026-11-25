"""Keyed upload execution only. T1 is supplied by upload_claim_service.

Public callers supply authenticated identities; all mutable state is reloaded.
A private bounded snapshot ensures concurrent executions of an attempt upload
identical bytes, even if the caller's original stream changes later.
"""
from enum import Enum
import logging
import time
from tempfile import SpooledTemporaryFile

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from app.models import Document, DocumentVersion, Membership, Tenant, UploadAttempt, UploadOperation, User
from services.upload_claim_service import UploadReplay
from services.upload_idempotency import fingerprint_pdf_upload
from services.upload_validator import MAX_FILE_SIZE

from services.upload_result import valid_completed_result

logger = logging.getLogger(__name__)


class RejectionReason(str, Enum):
    AUTHORIZATION_DENIED = "authorization_denied"
    LEASE_EXPIRED = "lease_expired"
    STALE_FENCE = "stale_fence"
    METADATA_MISMATCH = "metadata_mismatch"
    TERMINAL_OPERATION = "terminal_operation"
    RESULT_UNAVAILABLE = "result_unavailable"
    LEGACY_UNRESOLVED = "legacy_unresolved"


class UploadRejected(RuntimeError):
    """Stable internal reason; messages are not a public response contract."""

    def __init__(self, reason: RejectionReason, message: str):
        self.reason = reason
        super().__init__(message)


class UploadRetryable(RuntimeError):
    """T2 failed before commit and rollback was confirmed; preserve the object."""

    def __init__(self, sqlstate: str):
        self.sqlstate = sqlstate
        super().__init__(f"T2 rolled back ({sqlstate}); retry only with a fresh fence check")



class UploadWriteUncertain(RuntimeError):
    """PUT may have succeeded; preserve state and objects."""


class UploadCommitUncertain(RuntimeError):
    """Preserve the object; resolve the operation through a new request/recovery."""


class UploadRollbackUncertain(RuntimeError):
    """Rollback could not be confirmed; do not compensate externally."""


def _transaction(factory, work, *, t2=False):
    s = factory()
    commit_started = False
    try:
        if s.in_transaction():
            raise ValueError("Upload service requires a fresh independent session")
        s.begin()
        if s.connection().get_isolation_level() != "READ COMMITTED":
            raise ValueError("Upload sessions must use READ COMMITTED")
        s.execute(text("select set_config('lock_timeout', '1000ms', true)"))
        s.execute(text("select set_config('statement_timeout', '5000ms', true)"))
        result = work(s)
        s.flush()
        commit_started = True
        s.commit()
    except BaseException as primary:
        rollback_failed = False
        try:
            s.rollback()
        except BaseException:
            rollback_failed = True
            logger.exception("Upload rollback failed")
        try:
            s.close()
        except BaseException:
            logger.exception("Upload session cleanup failed")
        if commit_started:
            raise UploadCommitUncertain("Upload transaction commit outcome unknown") from primary
        if rollback_failed:
            raise UploadRollbackUncertain("Upload transaction rollback outcome unknown") from primary
        if t2 and isinstance(primary, DBAPIError):
            sqlstate = getattr(primary.orig, "sqlstate", None)
            if sqlstate in {"55P03", "40P01", "40001"}:
                raise UploadRetryable(sqlstate) from primary
        raise
    else:
        try:
            s.close()
        except Exception:
            # Acknowledged commit remains known, even if resource cleanup fails.
            logger.exception("Committed upload session cleanup failed")
    return result


def _load(s, tenant_id, user_id, claim, fp, title):
    # Same order as T1: authorization -> operation -> attempt -> result rows.
    authorized = s.scalar(select(User.id).join(Membership, Membership.user_id == User.id)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(User.id == user_id, Tenant.id == tenant_id, User.status == "ACTIVE",
               Tenant.status == "ACTIVE", Membership.status == "ACTIVE")
        .with_for_update(read=True, of=(User, Tenant, Membership)))
    if authorized is None:
        raise UploadRejected(RejectionReason.AUTHORIZATION_DENIED, "Access denied")
    op = s.scalar(select(UploadOperation).where(UploadOperation.id == claim.operation_id,
        UploadOperation.tenant_id == tenant_id).with_for_update())
    if op is not None and op.requesting_user_id is None:
        raise UploadRejected(RejectionReason.LEGACY_UNRESOLVED, "Legacy operation requires reconciliation")
    if op is None or op.requesting_user_id != user_id:
        raise UploadRejected(RejectionReason.AUTHORIZATION_DENIED, "Access denied")
    if any(value is None for value in (op.fingerprint_version, op.request_title,
                                       op.request_size_bytes, op.request_content_sha256)):
        raise UploadRejected(RejectionReason.LEGACY_UNRESOLVED, "Legacy operation requires reconciliation")
    attempt = s.scalar(select(UploadAttempt).where(UploadAttempt.id == claim.attempt_id,
        UploadAttempt.operation_id == op.id, UploadAttempt.tenant_id == tenant_id).with_for_update())
    if attempt is None:
        raise UploadRejected(RejectionReason.STALE_FENCE, "Attempt unavailable")
    if (op.request_fingerprint, op.fingerprint_version, op.request_title, op.request_size_bytes, op.request_content_sha256) != (fp.fingerprint, fp.version, title, fp.size_bytes, fp.content_sha256):
        raise UploadRejected(RejectionReason.METADATA_MISMATCH, "Request metadata mismatch")
    if (attempt.expected_size_bytes, attempt.expected_sha256) != (fp.size_bytes, fp.content_sha256):
        raise UploadRejected(RejectionReason.METADATA_MISMATCH, "Attempt metadata mismatch")
    if (op.lease_token, op.lease_generation) != (claim.lease_token, claim.lease_generation) or (attempt.lease_token, attempt.lease_generation) != (claim.lease_token, claim.lease_generation):
        raise UploadRejected(RejectionReason.STALE_FENCE, "Stale upload fence")
    if (attempt.reserved_document_id, attempt.reserved_version_id, attempt.storage_key) != (claim.document_id, claim.version_id, claim.storage_key):
        raise UploadRejected(RejectionReason.METADATA_MISMATCH, "Reserved identity mismatch")
    expected_key = f"tenants/{tenant_id}/documents/{attempt.reserved_document_id}/versions/{attempt.reserved_version_id}/attempts/{attempt.id}/source.pdf"
    if attempt.storage_key != expected_key:
        raise UploadRejected(RejectionReason.METADATA_MISMATCH, "Invalid attempt namespace")
    replay = UploadReplay(attempt.reserved_document_id, attempt.reserved_version_id, tenant_id, op.request_title, op.request_size_bytes)
    if op.status == "COMPLETED":
        if not valid_completed_result(s, op, tenant_id, user_id):
            raise UploadRejected(RejectionReason.RESULT_UNAVAILABLE, "Completed result unavailable")
        return op, attempt, replay
    if op.status != "PROCESSING" or op.document_id is not None or op.version_id is not None:
        raise UploadRejected(RejectionReason.TERMINAL_OPERATION, "Operation is not processing")
    if op.lease_expires_at is None or op.lease_expires_at <= s.scalar(select(func.clock_timestamp())):
        raise UploadRejected(RejectionReason.LEASE_EXPIRED, "Upload lease expired; recovery required")
    return op, attempt, None



def _preflight(s, tenant_id, user_id, claim, fp, title):
    op, _, completed = _load(s, tenant_id, user_id, claim, fp, title)
    if completed is not None:
        return completed, None
    # Sample before the round trip so its latency reduces, never extends, budget.
    sampled_at = time.monotonic()
    database_now = s.scalar(select(func.clock_timestamp()))
    return None, sampled_at + (op.lease_expires_at - database_now).total_seconds()


def _fence(op, claim):
    return (UploadOperation.id == op.id, UploadOperation.status == "PROCESSING",
            UploadOperation.lease_token == claim.lease_token,
            UploadOperation.lease_generation == claim.lease_generation,
            UploadOperation.lease_expires_at > func.clock_timestamp())


def _finalize(s, tenant_id, user_id, claim, fp, title):
    op, attempt, completed = _load(s, tenant_id, user_id, claim, fp, title)
    if completed is not None:
        return completed
    s.add(Document(id=attempt.reserved_document_id, tenant_id=tenant_id,
                   owner_user_id=user_id, title=op.request_title))
    s.flush()
    s.add(DocumentVersion(id=attempt.reserved_version_id, document_id=attempt.reserved_document_id,
                          version_number=1, status="READY", storage_key=attempt.storage_key))
    s.flush()
    # Final lease check occurs after result inserts, immediately at the guarded
    # completion transition. Zero rows causes rollback of BOTH result inserts.
    changed = s.execute(update(UploadOperation).where(*_fence(op, claim)).values(
        status="COMPLETED", document_id=attempt.reserved_document_id,
        version_id=attempt.reserved_version_id).execution_options(synchronize_session=False)).rowcount
    if changed != 1:
        raise UploadRejected(RejectionReason.LEASE_EXPIRED, "Upload fence expired before completion")
    return UploadReplay(attempt.reserved_document_id, attempt.reserved_version_id, tenant_id, op.request_title, op.request_size_bytes)


def _reserve_cleanup(s, tenant_id, user_id, claim, fp, title):
    op, attempt, completed = _load(s, tenant_id, user_id, claim, fp, title)
    if completed is not None:
        return False
    if s.scalar(select(DocumentVersion.id).where(DocumentVersion.storage_key == attempt.storage_key).limit(1)) is not None:
        return False
    # Terminal FAILED prevents any conforming concurrent T2 from publishing this
    # object after the transaction closes and before external deletion finishes.
    return s.execute(update(UploadOperation).where(*_fence(op, claim)).values(status="FAILED")
                     .execution_options(synchronize_session=False)).rowcount == 1


def execute_claimed_upload(*, session_factory, storage, tenant_id, user_id, claim,
                           fingerprint, title, source):
    """Preflight -> storage (no DB transaction) -> fenced atomic T2.

    Does not claim, take over, renew or modify router/no-key behavior. Failures
    after uncertain commit or lost authorization/fencing preserve the object.
    """
    if fingerprint.size_bytes > MAX_FILE_SIZE:
        raise ValueError("File too large")
    with SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as snapshot:
        source.seek(0)
        size = 0
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_FILE_SIZE:
                raise ValueError("File too large")
            snapshot.write(chunk)
        actual = fingerprint_pdf_upload(source=snapshot, size_bytes=fingerprint.size_bytes, title=title)
        if actual != fingerprint:
            raise UploadRejected(RejectionReason.METADATA_MISMATCH, "Upload bytes do not match claim fingerprint")
        snapshot.seek(0)
        if snapshot.read(5) != b"%PDF-":
            raise UploadRejected(RejectionReason.METADATA_MISMATCH, "Invalid PDF signature")
        snapshot.seek(0)
        completed, deadline = _transaction(session_factory, lambda s: _preflight(s, tenant_id, user_id, claim, actual, title))
        if completed is not None:
            return completed
        if time.monotonic() >= deadline:
            raise UploadRejected(RejectionReason.LEASE_EXPIRED, "Upload lease expired before storage")
        try:
            try:
                storage.save(key=claim.storage_key, source=snapshot)
            except Exception as exc:
                raise UploadWriteUncertain("PUT outcome unknown") from exc
            return _transaction(session_factory, lambda s: _finalize(s, tenant_id, user_id, claim, actual, title), t2=True)
        except (UploadWriteUncertain, UploadCommitUncertain, UploadRollbackUncertain, UploadRejected, UploadRetryable):
            # Includes expiry/revocation/stale worker after a successful upload.
            raise
        except Exception:
            try:
                safe = _transaction(session_factory, lambda s: _reserve_cleanup(s, tenant_id, user_id, claim, actual, title))
                if safe:
                    storage.delete(key=claim.storage_key)
            except Exception:
                logger.exception("Upload cleanup deferred or failed", extra={"operation_id": str(claim.operation_id), "attempt_id": str(claim.attempt_id)})
            raise
