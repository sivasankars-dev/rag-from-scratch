"""Integration contract tests; unique disposable PostgreSQL databases only."""
import asyncio
from datetime import timedelta
from io import BytesIO
import os
from threading import Event, get_ident
from types import SimpleNamespace

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import event, select, text

from app.models import DocumentVersion, UploadOperation, UploadAttempt
from app.tenant_auth import TenantPrincipal
from app.keyed_upload_auth import get_keyed_upload_principal
from services.upload_claim_service import claim_upload, ClaimOutcome, ClaimRollbackUncertain
from services.upload_recovery_service import recover_upload, RecoveryOutcome
from services.fenced_upload_service import execute_claimed_upload, UploadWriteUncertain, UploadRejected
from services.upload_reconciliation_service import reconcile_upload, ReconcileOutcome
from services.keyed_upload_application import execute_keyed_upload
from services.upload_http_contract import HttpOutcome
from test_upload_claim_postgres import sessions, claim_request, complete_fixture
from test_fenced_upload_postgres import Storage
from test_verified_recovery_postgres import RecoveryStorage

pytestmark = pytest.mark.skipif(os.getenv("RUN_DISPOSABLE_UPLOAD_CLAIMS") != "1", reason="Disposable PostgreSQL opt-in")


def test_expired_handoff_contains_only_operation_reference(sessions, claim_request):
    args, _, _ = claim_request
    original = claim_upload(**args).claim
    with sessions.begin() as s:
        s.get(UploadOperation, original.operation_id).lease_expires_at -= timedelta(days=1)
    decision = claim_upload(**args)
    assert decision.outcome == ClaimOutcome.RECOVERY_REQUIRED and decision.claim is None
    assert vars(decision.operation) == {"operation_id": original.operation_id}
    result = recover_upload(session_factory=sessions, tenant_id=args["tenant_id"], user_id=args["user_id"],
                            operation_id=decision.operation.operation_id)
    assert result.outcome == RecoveryOutcome.CLAIMED


def test_uncertain_initial_put_can_reconcile(sessions, claim_request):
    args, _, _ = claim_request
    claim = claim_upload(**args).claim
    storage = RecoveryStorage(sessions)
    def fail(): raise TimeoutError("secret exception detail")
    storage.after_save = fail
    with pytest.raises(UploadWriteUncertain):
        execute_claimed_upload(session_factory=storage.session_factory, storage=storage,
            tenant_id=args["tenant_id"], user_id=args["user_id"], claim=claim,
            fingerprint=args["fingerprint"], title=args["title"], source=BytesIO(b"%PDF-data"))
    assert not storage.deletes and storage.objects
    result = reconcile_upload(**args, storage=storage, claim=claim)
    assert result.outcome == ReconcileOutcome.COMPLETED


@pytest.mark.parametrize("change", ["key", "owner", "deleted"])
def test_completed_replay_consistency(sessions, claim_request, change):
    from app.models import Document
    from services.fenced_upload_service import _transaction, _finalize
    args, other, _ = claim_request
    claim = complete_fixture(sessions, args)
    with sessions.begin() as s:
        if change == "key": s.get(DocumentVersion, claim.version_id).storage_key = "other/key"
        elif change == "owner": s.get(Document, claim.document_id).owner_user_id = other
        else: s.get(Document, claim.document_id).deleted_at = s.scalar(text("select clock_timestamp()"))
    assert claim_upload(**args).outcome == ClaimOutcome.RESULT_UNAVAILABLE
    assert recover_upload(session_factory=sessions, tenant_id=args["tenant_id"], user_id=args["user_id"],
                          operation_id=claim.operation_id).outcome == RecoveryOutcome.RESULT_UNAVAILABLE
    with pytest.raises(UploadRejected):
        _transaction(sessions, lambda s: _finalize(s, args["tenant_id"], args["user_id"], claim, args["fingerprint"], args["title"]))
    assert reconcile_upload(**args, storage=RecoveryStorage(sessions)).reason == "result_unavailable"


def test_t1_rollback_uncertainty_beats_busy(sessions, claim_request):
    args, _, _ = claim_request
    def factory():
        s = sessions()
        rollback = s.rollback
        def fail():
            rollback()
            raise RuntimeError("rollback ack lost")
        s.rollback = fail
        return s
    def transient(mapper, connection, target):
        connection.execute(text("DO $$ BEGIN RAISE EXCEPTION 'deadlock' USING ERRCODE='40P01'; END $$"))
    event.listen(UploadAttempt, "before_insert", transient)
    try:
        with pytest.raises(ClaimRollbackUncertain):
            claim_upload(**dict(args, session_factory=factory))
    finally:
        event.remove(UploadAttempt, "before_insert", transient)


def test_short_auth_and_worker_leave_event_loop_responsive(sessions, claim_request, monkeypatch):
    args, _, _ = claim_request
    import app.auth as auth
    monkeypatch.setattr(auth, "verify_access_token", lambda **kwargs: {"sub": str(args["user_id"])})
    auth_sessions, closed = [], []
    def auth_factory():
        s = sessions()
        original = s.close
        def close():
            original()
            closed.append(s)
        s.close = close
        auth_sessions.append(s)
        return s
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        session_factory=auth_factory, jwt_public_key=b"unused", jwt_issuer="i", jwt_audience="a")))
    principal = get_keyed_upload_principal(request, args["tenant_id"],
        HTTPAuthorizationCredentials(scheme="Bearer", credentials="test"))
    assert closed == auth_sessions
    assert all(not s.in_transaction() for s in auth_sessions)
    entered, release = Event(), Event()
    thread_ids = []
    storage = Storage(sessions)
    save = storage.save
    def blocked(**kwargs):
        thread_ids.append(get_ident())
        assert all(not s.in_transaction() for s in auth_sessions)
        entered.set()
        assert release.wait(5)
        save(**kwargs)
    storage.save = blocked
    async def exercise():
        main_thread = get_ident()
        task = asyncio.create_task(execute_keyed_upload(
            engine=sessions.kw["bind"], storage=storage, principal=principal,
            idempotency_key=args["idempotency_key"], title=args["title"], size_bytes=9, source=BytesIO(b"%PDF-data")))
        try:
            async with asyncio.timeout(4):
                while not entered.is_set():
                    await asyncio.sleep(.001)
                await asyncio.sleep(0)  # Runs while worker is blocked in storage.
                assert not task.done() and thread_ids[0] != main_thread
        finally:
            release.set()
        assert (await task).outcome == HttpOutcome.COMPLETED
    asyncio.run(exercise())


def test_application_recovers_expired_retry_without_caller_orm_lookup(sessions, claim_request):
    args, _, _ = claim_request
    claim = claim_upload(**args).claim
    with sessions.begin() as s:
        s.get(UploadOperation, claim.operation_id).lease_expires_at -= timedelta(days=1)
    result = asyncio.run(execute_keyed_upload(
        engine=sessions.kw["bind"], storage=Storage(sessions),
        principal=TenantPrincipal(args["user_id"], args["tenant_id"]),
        idempotency_key=args["idempotency_key"], title=args["title"],
        size_bytes=9, source=BytesIO(b"%PDF-data")))
    assert result.outcome == HttpOutcome.COMPLETED and result.replay.document_id == claim.document_id


def test_reconciliation_diagnostics_do_not_log_sensitive_messages(sessions, claim_request, caplog):
    args, _, _ = claim_request
    claim = claim_upload(**args).claim
    storage = RecoveryStorage(sessions)
    storage.open_error = OSError("SECRET_CREDENTIAL_OR_OBJECT_KEY")
    assert reconcile_upload(**args, storage=storage, claim=claim).outcome == ReconcileOutcome.UNRESOLVED
    assert "Upload reconciliation failure" in caplog.text
    assert "SECRET_CREDENTIAL_OR_OBJECT_KEY" not in caplog.text
    record = next(r for r in caplog.records if r.message == "Upload reconciliation failure")
    assert record.operation_id == str(claim.operation_id) and record.error_type == "OSError"
