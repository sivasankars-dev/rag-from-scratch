"""Pure typed application mapping; never serialize claims, receipts or exceptions."""
from dataclasses import dataclass
from enum import Enum
from sqlalchemy.exc import DBAPIError
from services.upload_claim_service import ClaimDecision, ClaimOutcome, UploadReplay, ClaimCommitUncertain, ClaimRollbackUncertain
from services.upload_recovery_service import RecoveryDecision, RecoveryOutcome
from services.upload_reconciliation_service import ReconcileDecision, ReconcileOutcome
from services.verified_recovery_service import SourceDecision, SourceOutcome, RecoveryReadFailure
from services.fenced_upload_service import UploadRejected, RejectionReason, UploadWriteUncertain, UploadCommitUncertain, UploadRollbackUncertain, UploadRetryable
from services.upload_validator import UploadValidationError, FileTooLargeError


class HttpOutcome(str, Enum):
    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    CONFLICT = "conflict"
    FORBIDDEN = "forbidden"
    TERMINAL = "terminal"
    SOURCE_REQUIRED = "source_required"
    RECOVERY_REQUIRED = "recovery_required"
    UNRESOLVED = "unresolved"
    RETRYABLE = "retryable"
    INVALID_REQUEST = "invalid_request"
    TOO_LARGE = "too_large"
    INTERNAL_ERROR = "internal_error"


STATUS = {
    HttpOutcome.COMPLETED: 200, HttpOutcome.IN_PROGRESS: 409,
    HttpOutcome.CONFLICT: 409, HttpOutcome.FORBIDDEN: 403,
    HttpOutcome.TERMINAL: 409, HttpOutcome.SOURCE_REQUIRED: 409,
    HttpOutcome.RECOVERY_REQUIRED: 409, HttpOutcome.UNRESOLVED: 503,
    HttpOutcome.RETRYABLE: 503, HttpOutcome.INVALID_REQUEST: 400,
    HttpOutcome.TOO_LARGE: 413, HttpOutcome.INTERNAL_ERROR: 500,
}


@dataclass(frozen=True)
class HttpDecision:
    outcome: HttpOutcome
    replay: UploadReplay | None = None

    @property
    def status_code(self):
        return STATUS[self.outcome]

    @property
    def retry_after(self):
        return 1 if self.outcome in {HttpOutcome.IN_PROGRESS, HttpOutcome.UNRESOLVED, HttpOutcome.RETRYABLE} else None


C = HttpOutcome
CLAIM_MAP = {
    ClaimOutcome.CLAIMED: C.IN_PROGRESS, ClaimOutcome.REPLAY: C.COMPLETED,
    ClaimOutcome.CONFLICT: C.CONFLICT, ClaimOutcome.ACCESS_DENIED: C.FORBIDDEN,
    ClaimOutcome.IN_PROGRESS: C.IN_PROGRESS, ClaimOutcome.LEGACY_UNRESOLVED: C.INTERNAL_ERROR,
    ClaimOutcome.RECOVERY_REQUIRED: C.RECOVERY_REQUIRED, ClaimOutcome.FAILED: C.TERMINAL,
    ClaimOutcome.RESULT_UNAVAILABLE: C.INTERNAL_ERROR, ClaimOutcome.BUSY: C.RETRYABLE,
}
RECOVERY_MAP = {
    RecoveryOutcome.CLAIMED: C.IN_PROGRESS, RecoveryOutcome.REPLAY: C.COMPLETED,
    RecoveryOutcome.IN_PROGRESS: C.IN_PROGRESS, RecoveryOutcome.ACCESS_DENIED: C.FORBIDDEN,
    RecoveryOutcome.FAILED: C.TERMINAL, RecoveryOutcome.LEGACY_UNRESOLVED: C.INTERNAL_ERROR,
    RecoveryOutcome.INCONSISTENT: C.INTERNAL_ERROR, RecoveryOutcome.RESULT_UNAVAILABLE: C.INTERNAL_ERROR,
    RecoveryOutcome.UNRESOLVED: C.UNRESOLVED, RecoveryOutcome.NOT_COMMITTED: C.RECOVERY_REQUIRED,
    RecoveryOutcome.SUPERSEDED: C.RECOVERY_REQUIRED, RecoveryOutcome.EXPIRED: C.RECOVERY_REQUIRED,
    RecoveryOutcome.BUSY: C.RETRYABLE,
}
REJECTION_MAP = {
    RejectionReason.AUTHORIZATION_DENIED: C.FORBIDDEN, RejectionReason.LEASE_EXPIRED: C.RECOVERY_REQUIRED,
    RejectionReason.STALE_FENCE: C.RECOVERY_REQUIRED, RejectionReason.METADATA_MISMATCH: C.CONFLICT,
    RejectionReason.TERMINAL_OPERATION: C.TERMINAL, RejectionReason.RESULT_UNAVAILABLE: C.INTERNAL_ERROR,
    RejectionReason.LEGACY_UNRESOLVED: C.INTERNAL_ERROR,
}
# Exact machine codes, never exception-message parsing. Unknown codes fail closed.
RECONCILE_REASON_MAP = {
    "access_denied": C.FORBIDDEN, "access_denied_or_legacy": C.FORBIDDEN,
    "metadata_mismatch_or_legacy": C.CONFLICT, "absence_not_proven": C.UNRESOLVED,
    "failed": C.TERMINAL, "legacy_unresolved": C.INTERNAL_ERROR, "inconsistent": C.INTERNAL_ERROR,
    "result_unavailable": C.INTERNAL_ERROR, "committed": C.COMPLETED,
    "verified_current_object": C.COMPLETED, "live_owner": C.IN_PROGRESS,
    "claim_changed": C.RECOVERY_REQUIRED, "wrong_operation": C.RECOVERY_REQUIRED,
    "r1_not_committed": C.RECOVERY_REQUIRED, "receipt_superseded_or_invalid": C.RECOVERY_REQUIRED,
    "expired_requires_takeover": C.RECOVERY_REQUIRED,
    "missing_now_late_put_possible": C.SOURCE_REQUIRED, "corrupt_object": C.SOURCE_REQUIRED,
    "storage_access_denied": C.UNRESOLVED, "storage_unavailable_or_timeout": C.UNRESOLVED,
    "read_interrupted_or_close_failed": C.UNRESOLVED, "database_outcome_uncertain": C.UNRESOLVED,
    "t2_rolled_back_retryable": C.RETRYABLE, "database_unavailable_or_contention": C.RETRYABLE,
    **{reason.value: outcome for reason, outcome in REJECTION_MAP.items()},
}


def normalize_upload_result(value):
    replay = getattr(value, "replay", None)
    if isinstance(value, UploadReplay):
        return HttpDecision(C.COMPLETED, value)
    if isinstance(value, ClaimDecision): outcome = CLAIM_MAP[value.outcome]
    elif isinstance(value, RecoveryDecision): outcome = RECOVERY_MAP[value.outcome]
    elif isinstance(value, ReconcileDecision): outcome = RECONCILE_REASON_MAP.get(value.reason, C.INTERNAL_ERROR)
    elif isinstance(value, SourceDecision):
        outcome = C.COMPLETED if value.outcome == SourceOutcome.COMPLETED else C.SOURCE_REQUIRED
    elif isinstance(value, UploadRejected): outcome = REJECTION_MAP[value.reason]
    elif isinstance(value, (ClaimCommitUncertain, ClaimRollbackUncertain, UploadCommitUncertain,
                            UploadRollbackUncertain, UploadWriteUncertain, RecoveryReadFailure)):
        outcome = C.UNRESOLVED
    elif isinstance(value, (UploadRetryable, DBAPIError)): outcome = C.RETRYABLE
    elif isinstance(value, FileTooLargeError): outcome = C.TOO_LARGE
    elif isinstance(value, UploadValidationError): outcome = C.INVALID_REQUEST
    else: outcome = C.INTERNAL_ERROR  # Includes programming/config ValueError; not client blame.
    if outcome == C.COMPLETED and not isinstance(replay, UploadReplay):
        return HttpDecision(C.INTERNAL_ERROR)
    return HttpDecision(outcome, replay if outcome == C.COMPLETED else None)
