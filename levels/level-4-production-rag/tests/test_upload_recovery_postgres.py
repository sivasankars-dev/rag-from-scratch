"""Disposable real PostgreSQL recovery ownership; no external storage."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
import os
from threading import Event
import time
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import sessionmaker

from app.models import Document, DocumentVersion, Membership, UploadAttempt, UploadOperation, User
from services.upload_claim_service import claim_upload
from services.fenced_upload_service import _transaction, _finalize, UploadRejected, RejectionReason
from services.upload_recovery_service import recover_upload, RecoveryOutcome as O, RecoveryReceipt
from test_upload_claim_postgres import sessions, claim_request

pytestmark = pytest.mark.skipif(os.getenv("RUN_DISPOSABLE_UPLOAD_CLAIMS") != "1", reason="Disposable PostgreSQL opt-in")


@pytest.fixture
def recovery(sessions, claim_request):
    args, other, tenant = claim_request
    original = claim_upload(**args).claim
    with sessions.begin() as s:
        s.get(UploadOperation, original.operation_id).lease_expires_at -= timedelta(days=1)
    request = dict(session_factory=sessions, tenant_id=args["tenant_id"], user_id=args["user_id"],
                   operation_id=original.operation_id)
    return request, original, args, other, tenant


def snapshot(sessions, original):
    with sessions() as s:
        return (
            dict(s.execute(select(UploadOperation.__table__).where(UploadOperation.id == original.operation_id)).mappings().one()),
            list(s.execute(select(UploadAttempt.__table__).where(UploadAttempt.operation_id == original.operation_id)
                           .order_by(UploadAttempt.lease_generation)).mappings()),
        )


def test_takeover_preserves_history_and_fences_old_worker(sessions, recovery):
    request, old, args, _, _ = recovery
    before, history = snapshot(sessions, old)
    result = recover_upload(**request)
    assert result.outcome == O.CLAIMED
    new = result.claim
    assert new.lease_generation == 2 and new.lease_token != old.lease_token
    assert new.storage_key != old.storage_key and new.attempt_id != old.attempt_id
    assert (new.document_id, new.version_id) == (old.document_id, old.version_id)
    after, attempts = snapshot(sessions, old)
    assert len(attempts) == 2 and attempts[0] == history[0]
    for key in before.keys() - {"lease_generation", "lease_token", "lease_expires_at", "updated_at"}:
        assert before[key] == after[key]
    with pytest.raises(UploadRejected) as error:
        _transaction(sessions, lambda s: _finalize(s, args["tenant_id"], args["user_id"], old, args["fingerprint"], args["title"]))
    assert error.value.reason == RejectionReason.STALE_FENCE
    assert recover_upload(**request).outcome == O.IN_PROGRESS
    assert snapshot(sessions, old) == (after, attempts)


@pytest.mark.parametrize("change,expected", [
    ("failed", O.FAILED), ("legacy", O.LEGACY_UNRESOLVED), ("digest", O.INCONSISTENT),
    ("canonical", O.INCONSISTENT), ("token", O.INCONSISTENT),
    ("revoked", O.ACCESS_DENIED), ("disabled", O.ACCESS_DENIED),
    ("wrong_user", O.ACCESS_DENIED), ("cross_tenant", O.ACCESS_DENIED),
])
def test_rejected_recovery_never_mutates(sessions, recovery, change, expected):
    request, old, _, other, tenant = recovery
    with sessions.begin() as s:
        op = s.get(UploadOperation, old.operation_id)
        if change == "failed": op.status = "FAILED"
        elif change == "legacy":
            for key in ("requesting_user_id", "fingerprint_version", "request_title", "request_size_bytes", "request_content_sha256"):
                setattr(op, key, None)
        elif change == "digest": s.get(UploadAttempt, old.attempt_id).expected_sha256 = "f" * 64
        elif change == "canonical": s.get(UploadAttempt, old.attempt_id).reserved_document_id = uuid4()
        elif change == "token": op.lease_token = uuid4()
        elif change == "revoked": s.get(Membership, (request["tenant_id"], request["user_id"])).status = "REVOKED"
        elif change == "disabled": s.get(User, request["user_id"]).status = "DISABLED"
    if change == "wrong_user": request = dict(request, user_id=other)
    if change == "cross_tenant": request = dict(request, tenant_id=tenant)
    before = snapshot(sessions, old)
    result = recover_upload(**request)
    assert result.outcome == expected and result.claim is None and result.replay is None
    assert snapshot(sessions, old) == before


def test_completed_replay_validates_result_and_authorization(sessions, recovery):
    request, old, args, other, _ = recovery
    new = recover_upload(**request).claim
    replay = _transaction(sessions, lambda s: _finalize(s, args["tenant_id"], args["user_id"], new, args["fingerprint"], args["title"]))
    before = snapshot(sessions, old)
    assert recover_upload(**request).replay == replay
    assert recover_upload(**dict(request, user_id=other)).outcome == O.ACCESS_DENIED
    assert snapshot(sessions, old) == before
    with sessions.begin() as s:
        s.get(Document, new.document_id).deleted_at = s.scalar(select(func.clock_timestamp()))
    assert recover_upload(**request).outcome == O.RESULT_UNAVAILABLE


@pytest.mark.parametrize("committed", [True, False])
def test_uncertain_r1_reconciles_without_new_attempt(sessions, recovery, committed):
    request, old, _, _, _ = recovery
    def factory():
        s = sessions()
        commit, rollback, close = s.commit, s.rollback, s.close
        def fail_commit():
            if committed: commit()
            raise RuntimeError("ack lost")
        def fail_rollback():
            rollback()
            raise RuntimeError("secondary rollback error")
        def fail_close():
            close()
            raise RuntimeError("secondary close error")
        s.commit, s.rollback, s.close = fail_commit, fail_rollback, fail_close
        return s
    result = recover_upload(**dict(request, session_factory=factory))
    assert result.outcome == O.UNRESOLVED and result.claim is None
    assert result.receipt is not None
    before = snapshot(sessions, old)
    resolved = recover_upload(**request, receipt=result.receipt)
    assert resolved.outcome == (O.CLAIMED if committed else O.NOT_COMMITTED)
    assert snapshot(sessions, old) == before
    if committed:
        assert resolved.claim.attempt_id == result.receipt.attempt_id


@pytest.mark.parametrize("committed", [True, False])
@pytest.mark.parametrize("reconcile", [True, False])
def test_overlapping_r1_waits_for_authoritative_commit(sessions, recovery, committed, reconcile):
    request, old, _, _, _ = recovery
    ready, connected, release = Event(), Event(), Event()
    pids, receipt = {}, []
    def factory(label):
        def make():
            s = sessions()
            def began(session, transaction, connection):
                pids[label] = connection.scalar(text("select pg_backend_pid()"))
                if label == "contender": connected.set()
            event.listen(s, "after_begin", began)
            if label == "winner":
                commit = s.commit
                def finish():
                    attempt = s.scalar(select(UploadAttempt).where(UploadAttempt.operation_id == old.operation_id,
                                                                   UploadAttempt.lease_generation == 2))
                    receipt.append(RecoveryReceipt(old.operation_id, attempt.id, 2, attempt.lease_token))
                    ready.set()
                    assert release.wait(5)
                    if committed: commit()
                    else: raise RuntimeError("commit not sent")
                s.commit = finish
            return s
        return make
    with ThreadPoolExecutor(max_workers=2) as pool:
        winner = pool.submit(recover_upload, **dict(request, session_factory=factory("winner")))
        try:
            assert ready.wait(5)
            extra = {"receipt": receipt[0]} if reconcile else {}
            contender = pool.submit(recover_upload, **dict(request, session_factory=factory("contender")), **extra)
            assert connected.wait(5)
            assert pids["winner"] != pids["contender"]
            with sessions() as observer:
                deadline = time.monotonic() + .8
                while time.monotonic() < deadline:
                    if pids["winner"] in observer.scalar(text("select pg_blocking_pids(:p)"), {"p": pids["contender"]}):
                        break
                    time.sleep(.005)
                else: pytest.fail("No observed R1 blocking")
            assert not contender.done()
        finally: release.set()
        assert winner.result(timeout=5).outcome == (O.CLAIMED if committed else O.UNRESOLVED)
        expected = (O.CLAIMED if committed else O.NOT_COMMITTED) if reconcile else (O.IN_PROGRESS if committed else O.CLAIMED)
        assert contender.result(timeout=5).outcome == expected
    _, attempts = snapshot(sessions, old)
    assert len(attempts) == (1 if reconcile and not committed else 2)


def test_expired_and_superseded_receipts_cannot_authorize(sessions, recovery):
    request, old, _, _, _ = recovery
    new = recover_upload(**request).claim
    receipt = RecoveryReceipt(old.operation_id, new.attempt_id, new.lease_generation, new.lease_token)
    with sessions.begin() as s:
        s.get(UploadOperation, old.operation_id).lease_expires_at -= timedelta(days=1)
    assert recover_upload(**request, receipt=receipt).outcome == O.EXPIRED
    assert recover_upload(**request).claim.lease_generation == 3
    assert recover_upload(**request, receipt=receipt).outcome == O.SUPERSEDED
    assert recover_upload(**request, receipt=replace(receipt, operation_id=uuid4())).outcome == O.ACCESS_DENIED


def test_lease_consumed_by_commit_and_close(sessions, recovery, monkeypatch):
    import services.upload_recovery_service as service
    request, old, _, _, _ = recovery
    clock = [0.]
    monkeypatch.setattr(service.time, "monotonic", lambda: clock[0])
    def factory():
        s = sessions()
        close = s.close
        def delayed():
            close()
            clock[0] += 3600
        s.close = delayed
        return s
    result = recover_upload(**dict(request, session_factory=factory))
    assert result.outcome == O.EXPIRED and result.claim is None
    assert len(snapshot(sessions, old)[1]) == 2


def test_attempt_insert_failure_is_atomic(sessions, recovery):
    request, old, _, _, _ = recovery
    before = snapshot(sessions, old)
    def fail(*args): raise RuntimeError("attempt failure")
    event.listen(UploadAttempt, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="attempt failure"): recover_upload(**request)
    finally: event.remove(UploadAttempt, "before_insert", fail)
    assert snapshot(sessions, old) == before


def test_wrong_isolation_rejected(sessions, recovery):
    request, _, _, _, _ = recovery
    engine = create_engine(sessions.kw["bind"].url, isolation_level="REPEATABLE READ")
    try:
        wrong = sessionmaker(engine)
        with wrong() as s:
            assert s.scalar(text("show transaction_isolation")) == "repeatable read"
        with pytest.raises(ValueError, match="READ COMMITTED"):
            recover_upload(**dict(request, session_factory=wrong))
    finally:
        engine.dispose()


def test_authorization_lock_precedes_operation_lock(sessions, recovery):
    request, old, _, _, _ = recovery
    # Hold membership exclusively. Recovery must wait there without locking op.
    connected = Event()
    pids = {}
    def factory():
        s = sessions()
        def began(session, transaction, connection):
            pids["worker"] = connection.scalar(text("select pg_backend_pid()"))
            connected.set()
        event.listen(s, "after_begin", began)
        return s
    with sessions.begin() as blocker:
        blocker.scalar(select(Membership).where(Membership.tenant_id == request["tenant_id"],
            Membership.user_id == request["user_id"]).with_for_update())
        blocker_pid = blocker.scalar(text("select pg_backend_pid()"))
        with ThreadPoolExecutor(max_workers=1) as pool:
            worker = pool.submit(recover_upload, **dict(request, session_factory=factory))
            assert connected.wait(5)
            with sessions() as observer:
                deadline = time.monotonic() + .8
                while time.monotonic() < deadline:
                    if blocker_pid in observer.scalar(text("select pg_blocking_pids(:p)"), {"p": pids["worker"]}):
                        break
                    time.sleep(.005)
                else: pytest.fail("Recovery did not wait on authorization")
                # NOWAIT proves it has not acquired the operation lock first.
                observer.scalar(select(UploadOperation).where(UploadOperation.id == old.operation_id).with_for_update(nowait=True))
                observer.rollback()
            assert worker.result(timeout=3).outcome == O.BUSY
    assert len(snapshot(sessions, old)[1]) == 1
