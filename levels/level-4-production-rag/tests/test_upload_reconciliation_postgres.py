"""Disposable PostgreSQL and fake storage reconciliation tests."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
from threading import Event
import time

import pytest
from sqlalchemy import event, select, text

from app.models import DocumentVersion, Membership, UploadOperation
from services.document_storage import ObjectAccessDenied
from services.upload_recovery_service import recover_upload, RecoveryReceipt
from services.upload_reconciliation_service import reconcile_upload, report_orphan_candidates, ReconcileOutcome as O
from test_upload_claim_postgres import sessions, claim_request
from test_upload_recovery_postgres import recovery
from test_verified_recovery_postgres import recovered

pytestmark = pytest.mark.skipif(os.getenv("RUN_DISPOSABLE_UPLOAD_CLAIMS") != "1", reason="Disposable PostgreSQL opt-in")


def args(recovered, sessions):
    values, storage, old, request = recovered
    with sessions() as s:
        key = s.get(UploadOperation, old.operation_id).idempotency_key
    return dict(session_factory=storage.session_factory, storage=storage,
                tenant_id=values["tenant_id"], user_id=values["user_id"],
                idempotency_key=key, fingerprint=values["fingerprint"], title=values["title"])


def test_current_object_finalizes_without_put_and_reports_orphans(sessions, recovered):
    values, storage, old, _ = recovered
    storage.objects[values["claim"].storage_key] = b"%PDF-data"
    request = args(recovered, sessions)
    assert reconcile_upload(**request).outcome == O.IN_PROGRESS
    result = reconcile_upload(**request, claim=values["claim"])
    assert result.outcome == O.COMPLETED
    assert reconcile_upload(**request).replay == result.replay
    assert storage.saves == 0 and not storage.deletes
    assert all(s.closed for s in storage.streams)
    report = report_orphan_candidates(**{k: request[k] for k in (
        "session_factory", "tenant_id", "user_id", "idempotency_key")})
    assert [c.classification for c in report.candidates] == ["superseded_possible_orphan", "referenced_preserve"]
    assert all(c.existence == "unknown" and not c.deletion_authorized for c in report.candidates)


@pytest.mark.parametrize("kind,expected", [
    ("missing", O.SOURCE_REQUIRED), ("corrupt", O.SOURCE_REQUIRED),
    ("access", O.UNRESOLVED), ("timeout", O.UNRESOLVED), ("interrupt", O.UNRESOLVED),
])
def test_object_failures_are_distinct_and_preserved(sessions, recovered, kind, expected):
    values, storage, _, _ = recovered
    if kind != "missing": storage.objects[values["claim"].storage_key] = b"%PDF-else" if kind == "corrupt" else b"%PDF-data"
    if kind == "access": storage.open_error = ObjectAccessDenied()
    if kind == "timeout": storage.open_error = TimeoutError()
    if kind == "interrupt": storage.read_error = True
    result = reconcile_upload(**args(recovered, sessions), claim=values["claim"])
    assert result.outcome == expected
    assert storage.saves == 0 and not storage.deletes
    assert all(s.closed for s in storage.streams)


def test_delayed_put_can_be_reconciled_on_later_call(sessions, recovered):
    values, storage, _, _ = recovered
    request = args(recovered, sessions)
    assert reconcile_upload(**request, claim=values["claim"]).outcome == O.SOURCE_REQUIRED
    storage.objects[values["claim"].storage_key] = b"%PDF-data"  # Late PUT acknowledgment lost.
    assert reconcile_upload(**request, claim=values["claim"]).outcome == O.COMPLETED
    assert not storage.deletes


@pytest.mark.parametrize("change", ["takeover", "revoke", "expire"])
def test_fresh_t2_rejects_change_during_read(sessions, recovered, change):
    values, storage, old, recovery_request = recovered
    storage.objects[values["claim"].storage_key] = b"%PDF-data"
    def mutate():
        with sessions.begin() as s:
            if change == "revoke":
                s.get(Membership, (values["tenant_id"], values["user_id"])).status = "REVOKED"
            else:
                s.get(UploadOperation, old.operation_id).lease_expires_at -= timedelta(days=1)
        if change == "takeover": recover_upload(**recovery_request)
    storage.after_read = mutate
    assert reconcile_upload(**args(recovered, sessions), claim=values["claim"]).outcome == O.STALE
    assert not storage.deletes
    with sessions() as s: assert s.get(DocumentVersion, old.version_id) is None


@pytest.mark.parametrize("committed", [True, False])
def test_uncertain_t2_then_authoritative_reconciliation(sessions, recovered, committed):
    values, storage, _, _ = recovered
    storage.objects[values["claim"].storage_key] = b"%PDF-data"
    request = args(recovered, sessions)
    calls = 0
    def factory():
        nonlocal calls
        calls += 1
        s = storage.session_factory()
        if calls == 2:
            commit = s.commit
            def uncertain():
                if committed: commit()
                raise RuntimeError("lost commit acknowledgment")
            s.commit = uncertain
        return s
    assert reconcile_upload(**dict(request, session_factory=factory), claim=values["claim"]).outcome == O.UNRESOLVED
    assert reconcile_upload(**request, claim=values["claim"]).outcome == O.COMPLETED
    assert not storage.deletes and storage.saves == 0


@pytest.mark.parametrize("committed", [True, False])
def test_r1_receipt_waits_for_inflight_transaction(sessions, recovery, committed):
    from test_verified_recovery_postgres import RecoveryStorage
    request, old, original, _, _ = recovery
    ready, connected, release = Event(), Event(), Event()
    pids, receipts = {}, []
    def winner_factory():
        s = sessions()
        commit = s.commit
        def finish():
            from app.models import UploadAttempt
            attempt = s.scalar(select(UploadAttempt).where(UploadAttempt.operation_id == old.operation_id,
                                                           UploadAttempt.lease_generation == 2))
            receipts.append(RecoveryReceipt(old.operation_id, attempt.id, 2, attempt.lease_token))
            pids["winner"] = s.scalar(text("select pg_backend_pid()"))
            ready.set()
            assert release.wait(5)
            if committed: commit()
            else: raise RuntimeError("rolled back")
        s.commit = finish
        return s
    def contender_factory():
        s = sessions()
        def began(session, transaction, connection):
            pids["contender"] = connection.scalar(text("select pg_backend_pid()"))
            connected.set()
        event.listen(s, "after_begin", began)
        return s
    storage = RecoveryStorage(sessions)
    with ThreadPoolExecutor(max_workers=2) as pool:
        winner = pool.submit(recover_upload, **dict(request, session_factory=winner_factory))
        try:
            assert ready.wait(5)
            storage.objects[f"tenants/{request['tenant_id']}/documents/{old.document_id}/versions/{old.version_id}/attempts/{receipts[0].attempt_id}/source.pdf"] = b"%PDF-data"
            contender = pool.submit(reconcile_upload, session_factory=contender_factory, storage=storage,
                tenant_id=request["tenant_id"], user_id=request["user_id"], idempotency_key=original["idempotency_key"],
                fingerprint=original["fingerprint"], title=original["title"], receipt=receipts[0])
            assert connected.wait(5) and pids["winner"] != pids["contender"]
            with sessions() as observer:
                deadline = time.monotonic() + .8
                while time.monotonic() < deadline:
                    if pids["winner"] in observer.scalar(text("select pg_blocking_pids(:p)"), {"p": pids["contender"]}): break
                    time.sleep(.005)
                else: pytest.fail("No observed lock wait")
        finally: release.set()
        winner.result(timeout=5)
        assert contender.result(timeout=5).outcome == (O.COMPLETED if committed else O.RECOVERABLE)


@pytest.mark.parametrize("committed", [True, False])
def test_t1_absence_is_not_proof_of_rollback(sessions, claim_request, committed):
    from services.upload_claim_service import claim_upload, ClaimCommitUncertain
    from test_verified_recovery_postgres import RecoveryStorage
    original, _, _ = claim_request
    storage = RecoveryStorage(sessions)
    request = {k: original[k] for k in ("session_factory", "tenant_id", "user_id", "idempotency_key", "fingerprint", "title")}
    assert reconcile_upload(**request, storage=storage).reason == "absence_not_proven"
    def factory():
        s = sessions()
        commit = s.commit
        def uncertain():
            if committed: commit()
            raise RuntimeError("ack lost")
        s.commit = uncertain
        return s
    with pytest.raises(ClaimCommitUncertain):
        claim_upload(**dict(original, session_factory=factory))
    assert reconcile_upload(**request, storage=storage).outcome == (O.IN_PROGRESS if committed else O.UNRESOLVED)
    assert not storage.opens


def test_report_denies_other_user_and_never_claims_existence(sessions, recovered):
    from uuid import uuid4
    request = args(recovered, sessions)
    params = {k: request[k] for k in ("session_factory", "tenant_id", "user_id", "idempotency_key")}
    report = report_orphan_candidates(**params)
    assert all(c.existence == "unknown" for c in report.candidates)
    assert report_orphan_candidates(**dict(params, user_id=uuid4())).candidates == ()


@pytest.mark.parametrize("field", ["lease_token", "lease_generation"])
def test_forged_fence_never_opens_object(sessions, recovered, field):
    from dataclasses import replace
    from uuid import uuid4
    values, storage, _, _ = recovered
    changed = replace(values["claim"], **{field: uuid4() if field == "lease_token" else 99})
    assert reconcile_upload(**args(recovered, sessions), claim=changed).outcome == O.STALE
    assert not storage.opens


def test_expired_operation_requires_explicit_takeover(sessions, recovered):
    values, storage, old, _ = recovered
    request = args(recovered, sessions)
    with sessions.begin() as s:
        s.get(UploadOperation, old.operation_id).lease_expires_at -= timedelta(days=1)
    assert reconcile_upload(**request).outcome == O.RECOVERABLE
    assert not storage.opens


@pytest.mark.parametrize("rollback_fails", [True, False])
def test_t2_failure_preserves_object_and_reports_uncertainty(sessions, recovered, rollback_fails):
    values, storage, old, _ = recovered
    storage.objects[values["claim"].storage_key] = b"%PDF-data"
    request = args(recovered, sessions)
    calls = 0
    def factory():
        nonlocal calls
        calls += 1
        s = storage.session_factory()
        if calls == 2 and rollback_fails:
            rollback = s.rollback
            def fail():
                rollback()
                raise RuntimeError("rollback acknowledgment lost")
            s.rollback = fail
        return s
    def transient(mapper, connection, target):
        connection.execute(text("DO $$ BEGIN RAISE EXCEPTION 'transient' USING ERRCODE = '40001'; END $$"))
    event.listen(DocumentVersion, "before_insert", transient)
    try:
        result = reconcile_upload(**dict(request, session_factory=factory), claim=values["claim"])
    finally:
        event.remove(DocumentVersion, "before_insert", transient)
    assert result.outcome == (O.UNRESOLVED if rollback_fails else O.RECOVERABLE)
    assert values["claim"].storage_key in storage.objects and not storage.deletes
    with sessions() as s:
        assert s.get(UploadOperation, old.operation_id).status == "PROCESSING"
        assert s.get(DocumentVersion, old.version_id) is None


def test_failed_orphans_remain_advisory_and_never_resurrect(sessions, recovered):
    values, storage, old, _ = recovered
    request = args(recovered, sessions)
    with sessions.begin() as s:
        s.get(UploadOperation, old.operation_id).status = "FAILED"
    assert reconcile_upload(**request, claim=values["claim"]).outcome == O.UNRESOLVED
    report = report_orphan_candidates(**{k: request[k] for k in (
        "session_factory", "tenant_id", "user_id", "idempotency_key")})
    assert report.candidates[-1].classification == "failed_possible_orphan"
    assert all(not c.deletion_authorized for c in report.candidates)
    assert not storage.opens and not storage.deletes
