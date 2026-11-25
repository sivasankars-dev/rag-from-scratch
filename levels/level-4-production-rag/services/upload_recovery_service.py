"""R1 ownership only. No storage calls, renewal, FAILED resurrection or scheduler."""
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
import time
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.models import Document, DocumentVersion, Membership, Tenant, UploadAttempt, UploadOperation, User
from services.fenced_upload_service import _transaction, UploadCommitUncertain, UploadRollbackUncertain
from services.upload_claim_service import _validate, UploadClaim, UploadReplay
from services.upload_idempotency import UploadFingerprint
from services.upload_result import valid_completed_result


class RecoveryOutcome(str, Enum):
    CLAIMED = "claimed"
    REPLAY = "replay"
    IN_PROGRESS = "in_progress"
    ACCESS_DENIED = "access_denied"
    FAILED = "failed"
    LEGACY_UNRESOLVED = "legacy_unresolved"
    INCONSISTENT = "inconsistent"
    RESULT_UNAVAILABLE = "result_unavailable"
    UNRESOLVED = "unresolved"
    NOT_COMMITTED = "not_committed"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    BUSY = "busy"


@dataclass(frozen=True)
class RecoveryReceipt:
    """Correlation only, NEVER an executable claim or proof of commit."""
    operation_id: UUID
    attempt_id: UUID
    generation: int
    token: UUID


@dataclass(frozen=True)
class RecoveryDecision:
    outcome: RecoveryOutcome
    claim: UploadClaim | None = None
    replay: UploadReplay | None = None
    receipt: RecoveryReceipt | None = None


def _key(tenant, document, version, attempt):
    return f"tenants/{tenant}/documents/{document}/versions/{version}/attempts/{attempt}/source.pdf"


def _claim(op, attempt):
    return UploadClaim(op.id, attempt.id, attempt.reserved_document_id,
                       attempt.reserved_version_id, attempt.storage_key,
                       attempt.lease_token, attempt.lease_generation, op.lease_expires_at)


def _locked_state(s, tenant_id, user_id, operation_id):
    # Identical authorization lock group to T1/T2, before operation/history.
    authorized = s.scalar(select(User.id).join(Membership, Membership.user_id == User.id)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(User.id == user_id, Tenant.id == tenant_id, User.status == "ACTIVE",
               Tenant.status == "ACTIVE", Membership.status == "ACTIVE")
        .with_for_update(read=True, of=(User, Tenant, Membership)))
    if authorized is None:
        return RecoveryDecision(RecoveryOutcome.ACCESS_DENIED), None, None
    op = s.scalar(select(UploadOperation).where(
        UploadOperation.id == operation_id, UploadOperation.tenant_id == tenant_id).with_for_update())
    if op is None or (op.requesting_user_id is not None and op.requesting_user_id != user_id):
        return RecoveryDecision(RecoveryOutcome.ACCESS_DENIED), None, None
    metadata = (op.requesting_user_id, op.fingerprint_version, op.request_title,
                op.request_size_bytes, op.request_content_sha256)
    if any(value is None for value in metadata):
        return RecoveryDecision(RecoveryOutcome.LEGACY_UNRESOLVED), None, None
    if op.status == "FAILED":
        return RecoveryDecision(RecoveryOutcome.FAILED), None, None
    try:
        _validate(op.idempotency_key, op.request_title, UploadFingerprint(
            op.fingerprint_version, op.request_fingerprint, op.request_content_sha256, op.request_size_bytes))
    except ValueError:
        return RecoveryDecision(RecoveryOutcome.INCONSISTENT), None, None
    attempts = s.scalars(select(UploadAttempt).where(
        UploadAttempt.operation_id == op.id, UploadAttempt.tenant_id == tenant_id)
        .order_by(UploadAttempt.lease_generation, UploadAttempt.id).with_for_update()).all()
    invalid = RecoveryDecision(RecoveryOutcome.INCONSISTENT)
    if not attempts or op.lease_token is None or op.lease_expires_at is None:
        return invalid, None, None
    first, current = attempts[0], attempts[-1]
    if len(attempts) != op.lease_generation:
        return invalid, None, None
    for generation, attempt in enumerate(attempts, 1):
        if (attempt.lease_generation != generation
            or (attempt.reserved_document_id, attempt.reserved_version_id) !=
               (first.reserved_document_id, first.reserved_version_id)
            or (attempt.expected_size_bytes, attempt.expected_sha256) !=
               (op.request_size_bytes, op.request_content_sha256)
            or attempt.storage_key != _key(tenant_id, first.reserved_document_id, first.reserved_version_id, attempt.id)):
            return invalid, None, None
    if current.lease_token != op.lease_token:
        return invalid, None, None
    if op.status == "COMPLETED":
        if not valid_completed_result(s, op, tenant_id, user_id):
            return RecoveryDecision(RecoveryOutcome.RESULT_UNAVAILABLE), None, None
        return RecoveryDecision(RecoveryOutcome.REPLAY, replay=UploadReplay(
            op.document_id, op.version_id, tenant_id, op.request_title, op.request_size_bytes)), None, None
    if op.status != "PROCESSING" or op.document_id is not None or op.version_id is not None:
        return invalid, None, None
    # A processing operation must not already have canonical result rows.
    if (s.get(Document, first.reserved_document_id) is not None
        or s.get(DocumentVersion, first.reserved_version_id) is not None):
        return invalid, None, None
    return None, op, attempts


def recover_upload(*, session_factory, tenant_id, user_id, operation_id, lease_seconds=120,
                   receipt: RecoveryReceipt | None = None):
    """Take over an expired operation, or reconcile a receipt without any writes.

    A receipt selects reconciliation mode: only its exact current, live attempt
    can return CLAIMED. NOT_COMMITTED permits a later explicit recovery request.
    Factory must create fresh dedicated READ COMMITTED sessions. Shared helper
    enforces 1s lock / 5s statement timeouts and preserves uncertain outcomes.
    """
    if type(lease_seconds) is not int or not 1 <= lease_seconds <= 86400:
        raise ValueError("Lease must be between 1 and 86400 seconds")
    if receipt is not None and receipt.operation_id != operation_id:
        return RecoveryDecision(RecoveryOutcome.ACCESS_DENIED)
    pending = receipt
    deadline = None

    def work(s):
        nonlocal pending, deadline
        decision, op, attempts = _locked_state(s, tenant_id, user_id, operation_id)
        if decision is not None:
            return decision
        # Sampling after operation/history locks resolves in-flight R1 first.
        sampled_at = time.monotonic()
        now = s.scalar(select(func.clock_timestamp()))
        current = attempts[-1]
        if receipt is not None:
            matching = next((a for a in attempts if a.id == receipt.attempt_id), None)
            if matching is None:
                return RecoveryDecision(RecoveryOutcome.NOT_COMMITTED)
            if (matching.lease_generation, matching.lease_token) != (receipt.generation, receipt.token):
                return RecoveryDecision(RecoveryOutcome.INCONSISTENT)
            if matching.id != current.id:
                return RecoveryDecision(RecoveryOutcome.SUPERSEDED)
            if op.lease_expires_at <= now:
                return RecoveryDecision(RecoveryOutcome.EXPIRED)
        else:
            if op.lease_expires_at > now:
                return RecoveryDecision(RecoveryOutcome.IN_PROGRESS)
            if op.lease_generation >= 2**63 - 1:
                return RecoveryDecision(RecoveryOutcome.INCONSISTENT)
            first = attempts[0]
            attempt_id, token = uuid4(), uuid4()
            op.lease_generation += 1
            op.lease_token = token
            op.lease_expires_at = now + timedelta(seconds=lease_seconds)
            current = UploadAttempt(
                id=attempt_id, operation_id=op.id, tenant_id=tenant_id,
                reserved_document_id=first.reserved_document_id,
                reserved_version_id=first.reserved_version_id,
                expected_size_bytes=op.request_size_bytes, expected_sha256=op.request_content_sha256,
                lease_generation=op.lease_generation, lease_token=token,
                storage_key=_key(tenant_id, first.reserved_document_id, first.reserved_version_id, attempt_id))
            pending = RecoveryReceipt(op.id, attempt_id, op.lease_generation, token)
            s.add(current)
        deadline = sampled_at + (op.lease_expires_at - now).total_seconds()
        return RecoveryDecision(RecoveryOutcome.CLAIMED, claim=_claim(op, current))

    try:
        decision = _transaction(session_factory, work)
    except (UploadCommitUncertain, UploadRollbackUncertain):
        return RecoveryDecision(RecoveryOutcome.UNRESOLVED, receipt=pending)
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) in {"55P03", "57014", "40P01", "40001"}:
            return RecoveryDecision(RecoveryOutcome.BUSY, receipt=pending)
        raise
    if deadline is not None and time.monotonic() >= deadline:
        return RecoveryDecision(RecoveryOutcome.EXPIRED, receipt=pending)
    return decision
