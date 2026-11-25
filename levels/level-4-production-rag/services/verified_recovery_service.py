"""Recover verified bytes into the CURRENT attempt key. Never deletes objects."""
from contextlib import closing
from dataclasses import dataclass
from enum import Enum
from tempfile import SpooledTemporaryFile
import time

from services.document_storage import ObjectMissing, ObjectAccessDenied
from services.fenced_upload_service import (
    _transaction, _load, _preflight, _finalize, UploadRejected, RejectionReason, UploadWriteUncertain,
)
from services.upload_claim_service import UploadReplay
from services.upload_idempotency import fingerprint_pdf_upload
from services.upload_recovery_service import _locked_state, RecoveryOutcome
from services.upload_validator import MAX_FILE_SIZE


class SourceOutcome(str, Enum):
    COMPLETED = "completed"
    SOURCE_REQUIRED = "source_required"


class ReadFailureReason(str, Enum):
    ACCESS_DENIED = "access_denied"
    UNAVAILABLE = "unavailable"
    INTERRUPTED = "interrupted"


class RecoveryReadFailure(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(f"Recovery source read failed: {reason.value}")


class RecoveryWriteUncertain(UploadWriteUncertain):
    """PUT may have succeeded. Preserve all objects and reconcile before cleanup."""


@dataclass(frozen=True)
class SourceDecision:
    outcome: SourceOutcome
    replay: UploadReplay | None = None
    missing: int = 0
    corrupted: int = 0


def _candidates(s, tenant_id, user_id, claim, fingerprint, title):
    # Lock all persisted history in the R1 order before selecting any keys.
    decision, _, attempts = _locked_state(s, tenant_id, user_id, claim.operation_id)
    if decision is not None and decision.outcome != RecoveryOutcome.REPLAY:
        reasons = {
            RecoveryOutcome.ACCESS_DENIED: RejectionReason.AUTHORIZATION_DENIED,
            RecoveryOutcome.FAILED: RejectionReason.TERMINAL_OPERATION,
            RecoveryOutcome.LEGACY_UNRESOLVED: RejectionReason.LEGACY_UNRESOLVED,
            RecoveryOutcome.RESULT_UNAVAILABLE: RejectionReason.RESULT_UNAVAILABLE,
        }
        raise UploadRejected(reasons.get(decision.outcome, RejectionReason.METADATA_MISMATCH),
                             "Recovery operation unavailable")
    _, _, completed = _load(s, tenant_id, user_id, claim, fingerprint, title)
    if completed is not None:
        return completed, ()
    # Only historical attempts. No caller-supplied object keys or bucket listing.
    return None, tuple(a.storage_key for a in reversed(attempts)
                       if a.lease_generation < claim.lease_generation)


def _verify(source, snapshot, fingerprint, title):
    """Read at most expected size + 1; a mismatched EOF is corrupt, not missing."""
    snapshot.seek(0)
    snapshot.truncate()
    count = 0
    while True:
        chunk = source.read(min(64 * 1024, fingerprint.size_bytes + 1 - count))
        if not chunk:
            break
        count += len(chunk)
        if count > fingerprint.size_bytes:
            return False
        snapshot.write(chunk)
    if count != fingerprint.size_bytes:
        return False
    snapshot.seek(0)
    if snapshot.read(5) != b"%PDF-":
        return False
    actual = fingerprint_pdf_upload(source=snapshot, size_bytes=count, title=title)
    snapshot.seek(0)
    return actual == fingerprint


def execute_recovery_upload(*, session_factory, storage, tenant_id, user_id, claim,
                            fingerprint, title, retry_source=None):
    """No takeover or cleanup. All storage streams close before final preflight.

    Caller owns retry_source; its position is restored. Storage streams are owned
    here and closed even when verification/read fails. Infrastructure failures
    stop execution rather than falling through to SOURCE_REQUIRED.
    """
    if type(fingerprint.size_bytes) is not int or not 0 < fingerprint.size_bytes <= MAX_FILE_SIZE:
        raise ValueError("Invalid recovery size")
    completed, keys = _transaction(session_factory, lambda s: _candidates(
        s, tenant_id, user_id, claim, fingerprint, title))
    if completed is not None:
        return SourceDecision(SourceOutcome.COMPLETED, replay=completed)
    missing = corrupted = 0
    with SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as snapshot:
        valid = False
        if retry_source is not None:
            try:
                position = retry_source.tell()
                try:
                    retry_source.seek(0)
                    valid = _verify(retry_source, snapshot, fingerprint, title)
                finally:
                    retry_source.seek(position)
            except Exception as exc:
                raise RecoveryReadFailure(ReadFailureReason.INTERRUPTED) from exc
            if not valid:
                corrupted += 1
        if not valid:
            for key in keys:
                try:
                    stream = storage.open(key=key)
                except ObjectMissing:
                    missing += 1
                    continue
                except ObjectAccessDenied as exc:
                    raise RecoveryReadFailure(ReadFailureReason.ACCESS_DENIED) from exc
                except Exception as exc:
                    raise RecoveryReadFailure(ReadFailureReason.UNAVAILABLE) from exc
                try:
                    with closing(stream):
                        valid = _verify(stream, snapshot, fingerprint, title)
                except Exception as exc:
                    raise RecoveryReadFailure(ReadFailureReason.INTERRUPTED) from exc
                if valid:
                    break
                corrupted += 1
        if not valid:
            return SourceDecision(SourceOutcome.SOURCE_REQUIRED, missing=missing, corrupted=corrupted)

        completed, deadline = _transaction(session_factory, lambda s: _preflight(
            s, tenant_id, user_id, claim, fingerprint, title))
        if completed is not None:
            return SourceDecision(SourceOutcome.COMPLETED, replay=completed)
        if time.monotonic() >= deadline:
            raise UploadRejected(RejectionReason.LEASE_EXPIRED, "Recovery lease expired before storage")
        snapshot.seek(0)
        try:
            storage.save(key=claim.storage_key, source=snapshot)
        except Exception as exc:
            # Unlike legacy compensation, any PUT failure here is unresolved:
            # it may have written bytes, including a delayed remote completion.
            raise RecoveryWriteUncertain("Recovery PUT outcome unknown; preserve objects") from exc
        replay = _transaction(session_factory, lambda s: _finalize(
            s, tenant_id, user_id, claim, fingerprint, title), t2=True)
        return SourceDecision(SourceOutcome.COMPLETED, replay=replay)
