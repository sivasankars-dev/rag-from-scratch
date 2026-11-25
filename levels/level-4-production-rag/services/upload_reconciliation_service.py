"""Conservative database reconciliation and advisory object inventory. No deletes."""
from contextlib import closing
from dataclasses import dataclass
from enum import Enum
import logging
from tempfile import SpooledTemporaryFile
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.models import DocumentVersion, Membership, Tenant, UploadAttempt, UploadOperation, User
from services.document_storage import ObjectMissing, ObjectAccessDenied
from services.fenced_upload_service import (
    _transaction, _finalize, UploadRejected, RejectionReason, UploadCommitUncertain,
    UploadRollbackUncertain, UploadRetryable,
)
from services.upload_claim_service import UploadReplay, _validate
from services.upload_recovery_service import _locked_state, _claim, RecoveryOutcome
from services.verified_recovery_service import _verify
from services.upload_validator import MAX_FILE_SIZE


logger = logging.getLogger(__name__)


def _diagnose(stage, claim=None, receipt=None):
    # Do not log exception strings/tracebacks: DBAPI and SDK errors may contain
    # SQL parameters, object keys, endpoints or credentials.
    import sys
    exc = sys.exc_info()[1]
    identity = claim or receipt
    logger.warning("Upload reconciliation failure", extra={
        "stage": stage, "error_type": type(exc).__name__,
        "operation_id": str(identity.operation_id) if identity else None,
        "attempt_id": str(identity.attempt_id) if identity else None,
    })


class ReconcileOutcome(str, Enum):
    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    SOURCE_REQUIRED = "source_required"
    STALE = "stale"
    UNRESOLVED = "unresolved"
    RECOVERABLE = "recoverable"


@dataclass(frozen=True)
class ReconcileDecision:
    outcome: ReconcileOutcome
    reason: str
    replay: UploadReplay | None = None


@dataclass(frozen=True)
class OrphanCandidate:
    attempt_id: UUID
    storage_key: str
    generation: int
    classification: str
    existence: str = "unknown"
    deletion_authorized: bool = False


@dataclass(frozen=True)
class OrphanReport:
    outcome: ReconcileOutcome
    reason: str
    candidates: tuple[OrphanCandidate, ...] = ()


def _operation(s, tenant_id, user_id, key):
    authorized = s.scalar(select(User.id).join(Membership, Membership.user_id == User.id)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(User.id == user_id, Tenant.id == tenant_id, User.status == "ACTIVE",
               Tenant.status == "ACTIVE", Membership.status == "ACTIVE")
        .with_for_update(read=True, of=(User, Tenant, Membership)))
    if authorized is None:
        return None, "access_denied"
    op = s.scalar(select(UploadOperation).where(
        UploadOperation.tenant_id == tenant_id, UploadOperation.idempotency_key == key).with_for_update())
    if op is None:
        # SELECT cannot lock a missing row or exclude an in-flight T1 INSERT.
        return None, "absence_not_proven"
    if op.requesting_user_id is None:
        return None, "legacy_unresolved"
    if op.requesting_user_id != user_id:
        return None, "access_denied"
    return op, None


def reconcile_upload(*, session_factory, storage, tenant_id, user_id,
                     idempotency_key, fingerprint, title, claim=None, receipt=None):
    """No ownership acquisition. Exact claim/receipt is required to finalize.

    T1 key-only resolution reports durable state but never adopts a live worker's
    fence. An absent T1 stays unresolved; retry original conflict-aware T1.
    """
    _validate(idempotency_key, title, fingerprint)
    if fingerprint.size_bytes > MAX_FILE_SIZE:
        raise ValueError("File too large")
    if claim is not None and receipt is not None:
        raise ValueError("Supply either a claim or an R1 receipt")

    def inspect(s):
        op, error = _operation(s, tenant_id, user_id, idempotency_key)
        if error:
            return ReconcileDecision(ReconcileOutcome.UNRESOLVED, error), None
        if any(value is None for value in (op.fingerprint_version, op.request_title,
                                            op.request_size_bytes, op.request_content_sha256)):
            return ReconcileDecision(ReconcileOutcome.UNRESOLVED, "legacy_unresolved"), None
        if (op.request_fingerprint, op.fingerprint_version, op.request_title,
            op.request_size_bytes, op.request_content_sha256) != (
                fingerprint.fingerprint, fingerprint.version, title, fingerprint.size_bytes, fingerprint.content_sha256):
            return ReconcileDecision(ReconcileOutcome.UNRESOLVED, "metadata_mismatch"), None
        decision, _, attempts = _locked_state(s, tenant_id, user_id, op.id)
        if decision is not None:
            if decision.outcome == RecoveryOutcome.REPLAY:
                return ReconcileDecision(ReconcileOutcome.COMPLETED, "committed", decision.replay), None
            return ReconcileDecision(ReconcileOutcome.UNRESOLVED, decision.outcome.value), None
        current = _claim(op, attempts[-1])
        if claim is not None and claim != current:
            return ReconcileDecision(ReconcileOutcome.STALE, "claim_changed"), None
        if receipt is not None:
            if receipt.operation_id != op.id:
                return ReconcileDecision(ReconcileOutcome.STALE, "wrong_operation"), None
            matched = next((a for a in attempts if a.id == receipt.attempt_id), None)
            if matched is None:
                return ReconcileDecision(ReconcileOutcome.RECOVERABLE, "r1_not_committed"), None
            if (matched.id, matched.lease_generation, matched.lease_token) != (
                    current.attempt_id, receipt.generation, receipt.token):
                return ReconcileDecision(ReconcileOutcome.STALE, "receipt_superseded_or_invalid"), None
        if op.lease_expires_at <= s.scalar(select(func.clock_timestamp())):
            return ReconcileDecision(ReconcileOutcome.RECOVERABLE, "expired_requires_takeover"), None
        if claim is None and receipt is None:
            return ReconcileDecision(ReconcileOutcome.IN_PROGRESS, "live_owner"), None
        return None, current

    try:
        result, current = _transaction(session_factory, inspect)
        if result is not None:
            return result
        try:
            stream = storage.open(key=current.storage_key)
        except ObjectMissing:
            return ReconcileDecision(ReconcileOutcome.SOURCE_REQUIRED, "missing_now_late_put_possible")
        except ObjectAccessDenied:
            _diagnose("storage_access", claim, receipt)
            return ReconcileDecision(ReconcileOutcome.UNRESOLVED, "storage_access_denied")
        except Exception:
            _diagnose("storage_read", claim, receipt)
            return ReconcileDecision(ReconcileOutcome.UNRESOLVED, "storage_unavailable_or_timeout")
        try:
            with closing(stream), SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as snapshot:
                valid = _verify(stream, snapshot, fingerprint, title)
        except Exception:
            _diagnose("storage_read", claim, receipt)
            return ReconcileDecision(ReconcileOutcome.UNRESOLVED, "read_interrupted_or_close_failed")
        if not valid:
            return ReconcileDecision(ReconcileOutcome.SOURCE_REQUIRED, "corrupt_object")
        # No PUT: finalize the verified current key under a fresh authoritative fence.
        replay = _transaction(session_factory, lambda s: _finalize(
            s, tenant_id, user_id, current, fingerprint, title), t2=True)
        return ReconcileDecision(ReconcileOutcome.COMPLETED, "verified_current_object", replay)
    except (UploadCommitUncertain, UploadRollbackUncertain):
        _diagnose("transaction_uncertain", claim, receipt)
        return ReconcileDecision(ReconcileOutcome.UNRESOLVED, "database_outcome_uncertain")
    except UploadRetryable:
        _diagnose("transaction_retryable", claim, receipt)
        return ReconcileDecision(ReconcileOutcome.RECOVERABLE, "t2_rolled_back_retryable")
    except UploadRejected as exc:
        outcome = ReconcileOutcome.STALE if exc.reason in {
            RejectionReason.STALE_FENCE, RejectionReason.LEASE_EXPIRED,
            RejectionReason.AUTHORIZATION_DENIED, RejectionReason.TERMINAL_OPERATION,
        } else ReconcileOutcome.UNRESOLVED
        return ReconcileDecision(outcome, exc.reason.value)
    except DBAPIError:
        _diagnose("database", claim, receipt)
        return ReconcileDecision(ReconcileOutcome.UNRESOLVED, "database_unavailable_or_contention")


def report_orphan_candidates(*, session_factory, tenant_id, user_id, idempotency_key):
    """Read-only DB inventory, not object existence evidence or deletion approval."""
    def inspect(s):
        op, error = _operation(s, tenant_id, user_id, idempotency_key)
        if error:
            return OrphanReport(ReconcileOutcome.UNRESOLVED, error)
        attempts = s.scalars(select(UploadAttempt).where(
            UploadAttempt.operation_id == op.id, UploadAttempt.tenant_id == tenant_id)
            .order_by(UploadAttempt.lease_generation, UploadAttempt.id).with_for_update()).all()
        candidates = []
        for attempt in attempts:
            referenced = s.scalar(select(DocumentVersion.id).where(
                DocumentVersion.storage_key == attempt.storage_key).limit(1)) is not None
            if referenced:
                classification = "referenced_preserve"
            elif attempt.lease_generation < op.lease_generation:
                classification = "superseded_possible_orphan"
            elif op.status == "FAILED":
                classification = "failed_possible_orphan"
            else:
                classification = "current_or_inconsistent_unresolved"
            candidates.append(OrphanCandidate(attempt.id, attempt.storage_key,
                                             attempt.lease_generation, classification))
        return OrphanReport(ReconcileOutcome.UNRESOLVED, "advisory_snapshot_not_deletion_authority", tuple(candidates))
    try:
        return _transaction(session_factory, inspect)
    except (UploadCommitUncertain, UploadRollbackUncertain, DBAPIError):
        return OrphanReport(ReconcileOutcome.UNRESOLVED, "database_outcome_uncertain")
