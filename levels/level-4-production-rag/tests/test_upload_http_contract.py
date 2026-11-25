from services.upload_http_contract import *
from services.upload_reconciliation_service import ReconcileDecision, ReconcileOutcome
from services.upload_recovery_service import RecoveryOutcome
from services.verified_recovery_service import ReadFailureReason, RecoveryReadFailure
from services.upload_validator import UploadValidationError, FileTooLargeError
import pytest


def test_outcome_maps_are_exhaustive():
    assert set(CLAIM_MAP) == set(ClaimOutcome)
    assert set(RECOVERY_MAP) == set(RecoveryOutcome)
    assert set(REJECTION_MAP) == set(RejectionReason)
    assert set(STATUS) == set(HttpOutcome)


@pytest.mark.parametrize("reason,outcome", list(RECONCILE_REASON_MAP.items()))
def test_reconciliation_reason_mapping(reason, outcome):
    # Successful decisions without replay are invalid and must fail closed.
    result = normalize_upload_result(ReconcileDecision(ReconcileOutcome.UNRESOLVED, reason))
    assert result.outcome == (HttpOutcome.INTERNAL_ERROR if outcome == HttpOutcome.COMPLETED else outcome)
    assert result.replay is None


@pytest.mark.parametrize("reason", list(RejectionReason))
def test_rejection_mapping_does_not_parse_messages(reason):
    assert normalize_upload_result(UploadRejected(reason, "arbitrary SECRET")).outcome == REJECTION_MAP[reason]


@pytest.mark.parametrize("error,expected", [
    (ClaimCommitUncertain("secret"), HttpOutcome.UNRESOLVED),
    (ClaimRollbackUncertain("secret"), HttpOutcome.UNRESOLVED),
    (UploadWriteUncertain("secret"), HttpOutcome.UNRESOLVED),
    (UploadCommitUncertain("secret"), HttpOutcome.UNRESOLVED),
    (UploadRollbackUncertain("secret"), HttpOutcome.UNRESOLVED),
    (UploadRetryable("40001"), HttpOutcome.RETRYABLE),
    (FileTooLargeError("secret"), HttpOutcome.TOO_LARGE),
    (UploadValidationError("secret"), HttpOutcome.INVALID_REQUEST),
    (ValueError("config secret"), HttpOutcome.INTERNAL_ERROR),
    (RuntimeError("secret"), HttpOutcome.INTERNAL_ERROR),
])
def test_exception_mapping(error, expected):
    result = normalize_upload_result(error)
    assert result.outcome == expected and "secret" not in repr(result)


@pytest.mark.parametrize("reason", list(ReadFailureReason))
def test_storage_read_errors_are_service_failures(reason):
    assert normalize_upload_result(RecoveryReadFailure(reason)).outcome == HttpOutcome.UNRESOLVED


def test_unknown_reason_fails_closed():
    assert normalize_upload_result(ReconcileDecision(ReconcileOutcome.UNRESOLVED, "new_reason")).status_code == 500
