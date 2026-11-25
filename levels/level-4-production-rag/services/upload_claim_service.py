"""PostgreSQL-only T1 claims and replay decisions. No storage or T2 writes.

Callers must authenticate user_id and validate PDF bytes before calling. The
service rechecks active authorization. session_factory must create a fresh,
independent READ COMMITTED session (never a request's existing session).
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import hashlib
import logging
import time
import re
from typing import Callable
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models import Document, DocumentVersion, Membership, Tenant, UploadAttempt, UploadOperation, User
from services.upload_idempotency import FINGERPRINT_VERSION, UploadFingerprint


from services.upload_result import valid_completed_result

logger = logging.getLogger(__name__)


class ClaimOutcome(str, Enum):
    CLAIMED = "claimed"
    REPLAY = "replay"
    CONFLICT = "conflict"
    ACCESS_DENIED = "access_denied"
    IN_PROGRESS = "in_progress"
    LEGACY_UNRESOLVED = "legacy_unresolved"
    RECOVERY_REQUIRED = "recovery_required"
    FAILED = "failed"
    RESULT_UNAVAILABLE = "result_unavailable"
    BUSY = "busy"


class ClaimCommitUncertain(RuntimeError):
    """No storage action is authorized; retry the same key to resolve T1."""


class ClaimRollbackUncertain(RuntimeError):
    """T1 rollback unconfirmed; no claim or BUSY decision is safe."""


@dataclass(frozen=True)
class OperationReference:
    operation_id: UUID


@dataclass(frozen=True)
class UploadClaim:
    operation_id: UUID
    attempt_id: UUID
    document_id: UUID
    version_id: UUID
    storage_key: str
    lease_token: UUID
    lease_generation: int
    lease_expires_at: datetime


@dataclass(frozen=True)
class UploadReplay:
    document_id: UUID
    version_id: UUID
    tenant_id: UUID
    filename: str
    size_bytes: int
    status: str = "uploaded"


@dataclass(frozen=True)
class ClaimDecision:
    outcome: ClaimOutcome
    claim: UploadClaim | None = None
    replay: UploadReplay | None = None
    operation: OperationReference | None = None


def _validate(key: str, title: str, fingerprint: UploadFingerprint) -> None:
    if not isinstance(key, str) or not 1 <= len(key) <= 255 or not key.strip() or any(ord(c) < 32 or ord(c) == 127 for c in key):
        raise ValueError("Invalid idempotency key")
    if not isinstance(title, str) or not 1 <= len(title) <= 255 or "\x00" in title:
        raise ValueError("Invalid stored title")
    if fingerprint.version != FINGERPRINT_VERSION or type(fingerprint.size_bytes) is not int or fingerprint.size_bytes <= 0:
        raise ValueError("Invalid fingerprint version or size")
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint.content_sha256):
        raise ValueError("Invalid content digest")
    # Reject a fingerprint paired with a different title/size. This verifies
    # metadata consistency, not PDF validation or possession of the bytes.
    digest = hashlib.sha256(b"production-rag/pdf-upload/v1\x00")
    for field in (title.encode("utf-8"), str(fingerprint.size_bytes).encode("ascii"), bytes.fromhex(fingerprint.content_sha256)):
        digest.update(len(field).to_bytes(8, "big"))
        digest.update(field)
    if digest.hexdigest() != fingerprint.fingerprint:
        raise ValueError("Fingerprint does not match request metadata")


def claim_upload(*, session_factory: Callable[[], Session], tenant_id: UUID,
                 user_id: UUID, idempotency_key: str, title: str,
                 fingerprint: UploadFingerprint, lease_seconds: int = 120,
                 lock_timeout_ms: int = 1000, statement_timeout_ms: int = 5000) -> ClaimDecision:
    """Return CLAIMED only after operation AND attempt commit successfully.

    Other decisions never transfer lease ownership or alter existing metadata.
    Timeouts/deadlocks return BUSY after rollback. Commit errors conservatively
    raise ClaimCommitUncertain; no automatic replay of a write transaction.
    """
    _validate(idempotency_key, title, fingerprint)
    if any(type(n) is not int or n <= 0 for n in (lease_seconds, lock_timeout_ms, statement_timeout_ms)):
        raise ValueError("Lease and timeouts must be positive integers")
    if lease_seconds > 86400 or not lock_timeout_ms <= statement_timeout_ms <= 60000:
        raise ValueError("Invalid lease or timeout bounds")
    session = session_factory()
    decision = None
    claim_deadline = None
    try:
        if session.in_transaction():
            raise ValueError("Claim service requires a fresh independent session")
        session.begin()
        # Reject incompatible factories instead of relying on a server default.
        if session.connection().get_isolation_level() != "READ COMMITTED":
            raise ValueError("Claim sessions must use READ COMMITTED")
        session.execute(text("select set_config('lock_timeout', :value, true)"), {"value": f"{lock_timeout_ms}ms"})
        session.execute(text("select set_config('statement_timeout', :value, true)"), {"value": f"{statement_timeout_ms}ms"})
        # Keep the same lock order for future T2: authorization, then operation.
        authorized = session.scalar(
            select(User.id).join(Membership, Membership.user_id == User.id)
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .where(User.id == user_id, Tenant.id == tenant_id,
                   User.status == "ACTIVE", Tenant.status == "ACTIVE", Membership.status == "ACTIVE")
            .with_for_update(read=True, of=(User, Tenant, Membership))
        )
        if authorized is None:
            decision = ClaimDecision(ClaimOutcome.ACCESS_DENIED)
        else:
            decision = _claim_or_decide(session, tenant_id, user_id, idempotency_key, title, fingerprint, lease_seconds)
        session.flush()
        if decision.claim is not None:
            # Conservative monotonic deadline also accounts for time spent in
            # commit/close. DB time is authoritative; no wall-clock comparison.
            sampled_at = time.monotonic()
            database_now = session.scalar(select(func.clock_timestamp()))
            claim_deadline = sampled_at + (decision.claim.lease_expires_at - database_now).total_seconds()
        try:
            session.commit()
        except Exception as exc:
            raise ClaimCommitUncertain("T1 commit outcome unknown; retry the same key before any storage action") from exc
    except BaseException as primary:
        # No context manager may replace the primary error with a cleanup error.
        rollback_failed = False
        for action in (session.rollback, session.close):
            try:
                action()
            except BaseException:
                if action == session.rollback:
                    rollback_failed = True
                logger.exception("Claim transaction cleanup failed; preserving primary error")
        if rollback_failed and not isinstance(primary, ClaimCommitUncertain):
            raise ClaimRollbackUncertain("T1 rollback outcome unknown") from primary
        if isinstance(primary, DBAPIError) and getattr(primary.orig, "sqlstate", None) in {"55P03", "57014", "40P01", "40001"}:
            return ClaimDecision(ClaimOutcome.BUSY)
        raise
    else:
        # Commit acknowledgment is not undone by a resource cleanup failure.
        try:
            session.close()
        except Exception:
            logger.exception("Committed claim session cleanup failed")
    if claim_deadline is not None and time.monotonic() >= claim_deadline:
        # T1 is durable but no usable lease is handed to the caller. No takeover.
        return ClaimDecision(ClaimOutcome.RECOVERY_REQUIRED, operation=OperationReference(decision.claim.operation_id))
    return decision


def _claim_or_decide(session, tenant_id, user_id, key, title, fp, lease_seconds):
    operation_id, attempt_id, document_id, version_id, token = (uuid4() for _ in range(5))
    now = session.scalar(select(func.clock_timestamp()))
    expiry = now + timedelta(seconds=lease_seconds)
    inserted = session.scalar(
        insert(UploadOperation).values(
            id=operation_id, tenant_id=tenant_id, idempotency_key=key,
            requesting_user_id=user_id, request_fingerprint=fp.fingerprint,
            fingerprint_version=fp.version, request_title=title,
            request_size_bytes=fp.size_bytes, request_content_sha256=fp.content_sha256,
            status="PROCESSING", lease_token=token, lease_generation=1, lease_expires_at=expiry,
        ).on_conflict_do_nothing(constraint="uq_upload_operations_tenant_key")
        .returning(UploadOperation.id)
    )
    if inserted is not None:
        storage_key = f"tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/attempts/{attempt_id}/source.pdf"
        session.add(UploadAttempt(
            id=attempt_id, operation_id=operation_id, tenant_id=tenant_id,
            reserved_document_id=document_id, reserved_version_id=version_id,
            storage_key=storage_key, expected_size_bytes=fp.size_bytes,
            expected_sha256=fp.content_sha256, lease_token=token, lease_generation=1,
        ))
        return ClaimDecision(ClaimOutcome.CLAIMED, claim=UploadClaim(operation_id, attempt_id, document_id, version_id, storage_key, token, 1, expiry))

    # A separate READ COMMITTED statement sees the winner after INSERT waits.
    operation = session.scalar(select(UploadOperation).where(
        UploadOperation.tenant_id == tenant_id, UploadOperation.idempotency_key == key,
    ).with_for_update())
    if operation is None:
        return ClaimDecision(ClaimOutcome.BUSY)  # Concurrent retention/deletion.
    metadata = (operation.requesting_user_id, operation.fingerprint_version, operation.request_title,
                operation.request_size_bytes, operation.request_content_sha256)
    if any(value is None for value in metadata):
        return ClaimDecision(ClaimOutcome.LEGACY_UNRESOLVED)
    if operation.requesting_user_id != user_id:
        return ClaimDecision(ClaimOutcome.ACCESS_DENIED)
    if (operation.request_fingerprint, *metadata[1:]) != (fp.fingerprint, fp.version, title, fp.size_bytes, fp.content_sha256):
        return ClaimDecision(ClaimOutcome.CONFLICT)
    if operation.status == "COMPLETED":
        if not valid_completed_result(session, operation, tenant_id, user_id):
            return ClaimDecision(ClaimOutcome.RESULT_UNAVAILABLE)
        return ClaimDecision(ClaimOutcome.REPLAY, replay=UploadReplay(operation.document_id, operation.version_id, tenant_id, operation.request_title, operation.request_size_bytes))
    if operation.status == "FAILED":
        return ClaimDecision(ClaimOutcome.FAILED)
    now = session.scalar(select(func.clock_timestamp()))
    if operation.lease_token is None or operation.lease_expires_at is None or operation.lease_expires_at <= now:
        return ClaimDecision(ClaimOutcome.RECOVERY_REQUIRED, operation=OperationReference(operation.id))
    return ClaimDecision(ClaimOutcome.IN_PROGRESS)
