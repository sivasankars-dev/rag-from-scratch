"""Real PostgreSQL transactions, fake object storage; no MinIO access."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from io import BytesIO
import os
from threading import Barrier, Event, local
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, text

from app.models import Document, DocumentVersion, Membership, UploadAttempt, UploadOperation
from services.upload_claim_service import claim_upload, ClaimOutcome
from services.fenced_upload_service import execute_claimed_upload, UploadCommitUncertain, UploadRejected, RejectionReason, UploadWriteUncertain
from test_upload_claim_postgres import sessions, claim_request

pytestmark = pytest.mark.skipif(os.getenv("RUN_DISPOSABLE_UPLOAD_CLAIMS") != "1", reason="Disposable PostgreSQL opt-in required")


class Storage:
    def __init__(self, sessions):
        self.sessions = sessions
        self.objects = {}
        self.saves = 0
        self.deletes = []
        self.after_save = None
        self.fail_delete = False
        self.concurrent = False
        self.worker = local()

    def session_factory(self):
        s = self.sessions()
        if not hasattr(self.worker, "sessions"):
            self.worker.sessions = []
        self.worker.sessions.append(s)
        return s

    def no_open_transactions(self):
        assert all(not s.in_transaction() for s in getattr(self.worker, "sessions", []))
        if self.concurrent:
            return  # Other workers may legitimately be in preflight/T2.
        with self.sessions() as s:
            assert s.scalar(text("select count(*) from pg_stat_activity where datname=current_database() and pid<>pg_backend_pid() and backend_type='client backend' and xact_start is not null")) == 0

    def save(self, *, key, source):
        self.no_open_transactions()
        self.saves += 1
        self.objects[key] = source.read()
        if self.after_save:
            self.after_save()

    def delete(self, *, key):
        self.no_open_transactions()
        self.deletes.append(key)
        if self.fail_delete:
            raise RuntimeError("delete failed")
        self.objects.pop(key, None)


@pytest.fixture
def upload(sessions, claim_request):
    args, other, tenant = claim_request
    claim = claim_upload(**args).claim
    storage = Storage(sessions)
    values = dict(session_factory=storage.session_factory, storage=storage, tenant_id=args["tenant_id"], user_id=args["user_id"],
                  claim=claim, fingerprint=args["fingerprint"], title=args["title"])
    return values, storage, args


def run(values):
    return execute_claimed_upload(**values, source=BytesIO(b"%PDF-data"))


def assert_no_results(sessions, claim):
    with sessions() as s:
        assert s.get(Document, claim.document_id) is None
        assert s.get(DocumentVersion, claim.version_id) is None


def test_success_and_duplicate_execution(sessions, upload):
    values, storage, args = upload
    first = run(values)
    assert run(values) == first
    assert storage.saves == 1 and not storage.deletes
    claim = values["claim"]
    with sessions() as s:
        op = s.get(UploadOperation, claim.operation_id)
        doc = s.get(Document, claim.document_id)
        version = s.get(DocumentVersion, claim.version_id)
        assert op.status == "COMPLETED"
        assert (op.document_id, op.version_id) == (doc.id, version.id)
        assert doc.owner_user_id == args["user_id"] and doc.tenant_id == args["tenant_id"]
        assert doc.active_version_id is None
        assert version.status == "READY" and version.storage_key == claim.storage_key
    assert claim_upload(**args).outcome == ClaimOutcome.REPLAY


@pytest.mark.parametrize("change", ["token", "generation", "expiry", "revoked", "attempt_digest", "reserved", "key", "failed"])
def test_preflight_rejects_authoritative_changes(sessions, upload, change):
    values, storage, _ = upload
    claim = values["claim"]
    with sessions.begin() as s:
        op = s.get(UploadOperation, claim.operation_id)
        if change == "token": op.lease_token = uuid4()
        elif change == "generation": op.lease_generation += 1
        elif change == "expiry": op.lease_expires_at -= timedelta(days=1)
        elif change == "revoked": s.get(Membership, (values["tenant_id"], values["user_id"])).status = "REVOKED"
        elif change == "attempt_digest": s.get(UploadAttempt, claim.attempt_id).expected_sha256 = "f" * 64
        elif change == "reserved": s.get(UploadAttempt, claim.attempt_id).reserved_document_id = uuid4()
        elif change == "key": s.get(UploadAttempt, claim.attempt_id).storage_key = "wrong/key"
        else: op.status = "FAILED"
    with pytest.raises(UploadRejected) as error: run(values)
    expected = {
        "token": RejectionReason.STALE_FENCE, "generation": RejectionReason.STALE_FENCE,
        "expiry": RejectionReason.LEASE_EXPIRED, "revoked": RejectionReason.AUTHORIZATION_DENIED,
        "attempt_digest": RejectionReason.METADATA_MISMATCH, "reserved": RejectionReason.METADATA_MISMATCH,
        "key": RejectionReason.METADATA_MISMATCH, "failed": RejectionReason.TERMINAL_OPERATION,
    }
    assert error.value.reason == expected[change]
    assert storage.saves == 0
    assert_no_results(sessions, claim)


def test_forged_dataclass_and_different_bytes_rejected(upload):
    values, storage, _ = upload
    with pytest.raises(UploadRejected):
        run(dict(values, claim=replace(values["claim"], document_id=uuid4())))
    with pytest.raises(UploadRejected):
        execute_claimed_upload(**values, source=BytesIO(b"%PDF-else"))
    assert storage.saves == 0


@pytest.mark.parametrize("delete_fails", [False, True])
def test_known_t2_failure_fences_cleanup(sessions, upload, delete_fails, caplog):
    values, storage, _ = upload
    def fail(*args): raise RuntimeError("known T2 insert failure")
    storage.fail_delete = delete_fails
    event.listen(DocumentVersion, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="known T2 insert failure"): run(values)
    finally:
        event.remove(DocumentVersion, "before_insert", fail)
    assert storage.deletes == [values["claim"].storage_key]
    with sessions() as s:
        assert s.get(UploadOperation, values["claim"].operation_id).status == "FAILED"
    assert_no_results(sessions, values["claim"])
    if delete_fails: assert "cleanup deferred or failed" in caplog.text


def test_t2_insert_failure_rolls_back_both_result_rows(sessions, upload):
    values, storage, _ = upload
    def fail(*args): raise RuntimeError("version insert failed")
    event.listen(DocumentVersion, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="version insert failed"): run(values)
    finally:
        event.remove(DocumentVersion, "before_insert", fail)
    assert_no_results(sessions, values["claim"])
    assert storage.deletes == [values["claim"].storage_key]


@pytest.mark.parametrize("change", ["expiry", "token", "revoked"])
def test_fence_change_during_storage_preserves_object(sessions, upload, change):
    values, storage, _ = upload
    def mutate():
        with sessions.begin() as s:
            op = s.get(UploadOperation, values["claim"].operation_id)
            if change == "expiry": op.lease_expires_at -= timedelta(days=1)
            elif change == "token": op.lease_token = uuid4()
            else: s.get(Membership, (values["tenant_id"], values["user_id"])).status = "REVOKED"
    storage.after_save = mutate
    with pytest.raises(UploadRejected): run(values)
    assert storage.objects and not storage.deletes
    assert_no_results(sessions, values["claim"])


def test_final_conditional_expiry_check_rolls_back_inserted_results(sessions, upload):
    values, storage, _ = upload
    def expire(mapper, connection, target):
        connection.execute(text("update upload_operations set lease_expires_at=clock_timestamp()-interval '1 second' where id=:id"), {"id": values["claim"].operation_id})
    event.listen(DocumentVersion, "before_insert", expire)
    try:
        with pytest.raises(UploadRejected, match="before completion"): run(values)
    finally:
        event.remove(DocumentVersion, "before_insert", expire)
    assert_no_results(sessions, values["claim"])
    assert storage.objects and not storage.deletes


@pytest.mark.parametrize("commit_succeeded", [True, False])
def test_t2_uncertain_commit_never_deletes(sessions, upload, commit_succeeded):
    values, storage, args = upload
    calls = 0
    def factory():
        nonlocal calls
        calls += 1
        s = sessions()
        if calls == 2:  # T2, after successful preflight.
            original = s.commit
            def fail():
                if commit_succeeded: original()
                raise RuntimeError("commit acknowledgment lost")
            s.commit = fail
        return s
    with pytest.raises(UploadCommitUncertain): run(dict(values, session_factory=factory))
    assert storage.objects and not storage.deletes
    if commit_succeeded:
        assert claim_upload(**args).outcome == ClaimOutcome.REPLAY
        assert run(values).document_id == values["claim"].document_id
        assert storage.saves == 1
    else:
        assert_no_results(sessions, values["claim"])


def test_concurrent_execution_completes_one_logical_result(sessions, upload):
    values, storage, _ = upload
    barrier = Barrier(2)
    storage.concurrent = True
    # Each save executes after its own preflight commits. The barrier forces
    # both uploads to finish before either caller enters T2.
    storage.after_save = lambda: barrier.wait(timeout=5)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, values) for _ in range(2)]
        results = [f.result(timeout=10) for f in futures]
    assert results[0] == results[1]
    assert storage.saves == 2 and not storage.deletes
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(Document).where(Document.id == values["claim"].document_id)) == 1
        assert s.scalar(select(func.count()).select_from(DocumentVersion).where(DocumentVersion.id == values["claim"].version_id)) == 1


def test_late_upload_error_cannot_delete_completed_result(sessions, upload):
    values, storage, _ = upload
    waiting, release = Event(), Event()
    class LateFailure:
        def save(self, *, key, source):
            storage.objects[key] = source.read()
            waiting.set()
            assert release.wait(5)
            raise RuntimeError("late upload failure")
        def delete(self, **kwargs): storage.delete(**kwargs)
    with ThreadPoolExecutor(max_workers=1) as pool:
        late = pool.submit(run, dict(values, storage=LateFailure()))
        try:
            assert waiting.wait(5)
            successful = run(values)
        finally: release.set()
        with pytest.raises(UploadWriteUncertain): late.result(timeout=5)
    assert storage.objects and not storage.deletes
    assert run(values) == successful


def test_cleanup_commit_uncertainty_preserves_original_error_and_object(sessions, upload):
    values, storage, _ = upload
    calls = 0
    def factory():
        nonlocal calls
        calls += 1
        s = sessions()
        if calls == 3:  # Cleanup reservation after known T2 rollback.
            original = s.commit
            def uncertain():
                original()
                raise RuntimeError("cleanup commit ack lost")
            s.commit = uncertain
        return s
    def fail(*args): raise RuntimeError("primary T2 failure")
    event.listen(DocumentVersion, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="primary T2 failure"):
            run(dict(values, session_factory=factory))
    finally:
        event.remove(DocumentVersion, "before_insert", fail)
    assert storage.objects and not storage.deletes
    assert_no_results(sessions, values["claim"])


def test_t2_rollback_failure_preserves_object(sessions, upload):
    from services.fenced_upload_service import UploadRollbackUncertain
    values, storage, _ = upload
    calls = 0
    def factory():
        nonlocal calls
        calls += 1
        s = sessions()
        if calls == 2:
            def fail_rollback(): raise RuntimeError("rollback failed")
            s.rollback = fail_rollback
        return s
    def fail(*args): raise RuntimeError("version failed")
    event.listen(DocumentVersion, "before_insert", fail)
    try:
        with pytest.raises(UploadRollbackUncertain): run(dict(values, session_factory=factory))
    finally:
        event.remove(DocumentVersion, "before_insert", fail)
    assert storage.objects and not storage.deletes
    assert_no_results(sessions, values["claim"])


def test_terminal_cleanup_fences_late_success(sessions, upload):
    values, storage, _ = upload
    waiting, release = Event(), Event()
    class LateSuccess:
        def save(self, *, key, source):
            content = source.read()
            waiting.set()
            assert release.wait(5)
            storage.objects[key] = content  # Arrives after the other caller's cleanup.
        def delete(self, **kwargs): storage.delete(**kwargs)
    def fail(*args): raise RuntimeError("competing T2 failed")
    with ThreadPoolExecutor(max_workers=1) as pool:
        late = pool.submit(run, dict(values, storage=LateSuccess()))
        try:
            assert waiting.wait(5)
            event.listen(DocumentVersion, "before_insert", fail)
            try:
                with pytest.raises(RuntimeError, match="competing T2 failed"): run(values)
            finally:
                event.remove(DocumentVersion, "before_insert", fail)
        finally:
            release.set()
        with pytest.raises(UploadRejected): late.result(timeout=5)
    assert_no_results(sessions, values["claim"])
    with sessions() as s:
        assert s.get(UploadOperation, values["claim"].operation_id).status == "FAILED"
    assert storage.objects  # Known limitation: late physical writes need reconciliation.


@pytest.mark.parametrize("phase", ["commit", "close"])
def test_preflight_deadline_includes_transaction_completion(sessions, upload, monkeypatch, phase):
    import services.fenced_upload_service as service
    values, storage, _ = upload
    clock = [0.0]
    monkeypatch.setattr(service.time, "monotonic", lambda: clock[0])
    def factory():
        s = sessions()
        original = getattr(s, phase)
        def delayed():
            original()
            clock[0] += 3600
        setattr(s, phase, delayed)
        return s
    with pytest.raises(service.UploadRejected) as error:
        run(dict(values, session_factory=factory))
    assert error.value.reason == service.RejectionReason.LEASE_EXPIRED
    assert storage.saves == 0 and not storage.deletes
    with sessions() as s:
        assert s.get(UploadOperation, values["claim"].operation_id).status == "PROCESSING"


@pytest.mark.parametrize("sqlstate", ["55P03", "40P01", "40001"])
def test_retryable_t2_rollback_preserves_processing_and_can_complete(sessions, upload, sqlstate):
    from services.fenced_upload_service import UploadRetryable
    values, storage, _ = upload
    def fail(mapper, connection, target):
        # Real PostgreSQL error aborts the transaction after Document was flushed.
        connection.exec_driver_sql(
            f"DO $$ BEGIN RAISE EXCEPTION 'injected transient' USING ERRCODE = '{sqlstate}'; END $$"
        )
    event.listen(DocumentVersion, "before_insert", fail)
    try:
        with pytest.raises(UploadRetryable) as error:
            run(values)
        assert error.value.sqlstate == sqlstate
    finally:
        event.remove(DocumentVersion, "before_insert", fail)
    assert storage.objects and not storage.deletes and storage.saves == 1
    assert_no_results(sessions, values["claim"])
    with sessions() as s:
        assert s.get(UploadOperation, values["claim"].operation_id).status == "PROCESSING"
    assert run(values).document_id == values["claim"].document_id


@pytest.mark.parametrize("transaction_number", [1, 2, 3])
def test_acknowledged_commit_close_failure_is_not_uncertainty(sessions, upload, caplog, transaction_number):
    values, storage, _ = upload
    calls = 0
    def factory():
        nonlocal calls
        calls += 1
        s = sessions()
        if calls == transaction_number:
            close = s.close
            def fail_close():
                close()
                raise RuntimeError("close after acknowledged commit")
            s.close = fail_close
        return s
    if transaction_number == 3:
        # T2 known rollback -> cleanup is transaction three.
        def fail(*args): raise RuntimeError("terminal T2 failure")
        event.listen(DocumentVersion, "before_insert", fail)
        try:
            with pytest.raises(RuntimeError, match="terminal T2 failure"):
                run(dict(values, session_factory=factory))
        finally:
            event.remove(DocumentVersion, "before_insert", fail)
        assert storage.deletes == [values["claim"].storage_key]
    else:
        assert run(dict(values, session_factory=factory)).document_id == values["claim"].document_id
        assert storage.objects and not storage.deletes
    assert "Committed upload session cleanup failed" in caplog.text


@pytest.mark.parametrize("winner_commits", [True, False])
def test_t2_overlap_observes_distinct_backends_and_row_blocking(sessions, upload, winner_commits):
    import time
    from services.fenced_upload_service import _transaction, _finalize, UploadRetryable
    values, storage, _ = upload
    # Both workers have uploaded identical content before entering the T2 helper.
    storage.objects[values["claim"].storage_key] = b"%PDF-data"
    ready, connected, release = Event(), Event(), Event()
    pids = {}
    def finalize(label):
        def work(s):
            pids[label] = s.scalar(text("select pg_backend_pid()"))
            if label == "contender":
                connected.set()
            result = _finalize(s, values["tenant_id"], values["user_id"],
                               values["claim"], values["fingerprint"], values["title"])
            if label == "winner":
                ready.set()  # Holds operation lock and uncommitted result rows.
                assert release.wait(5)
                if not winner_commits:
                    s.execute(text("DO $$ BEGIN RAISE EXCEPTION 'rollback winner' USING ERRCODE = '40001'; END $$"))
            return result
        return _transaction(sessions, work, t2=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        winner = pool.submit(finalize, "winner")
        try:
            assert ready.wait(5)
            contender = pool.submit(finalize, "contender")
            assert connected.wait(5)
            assert pids["winner"] != pids["contender"]
            deadline = time.monotonic() + 0.8  # Below service's 1s lock timeout.
            with sessions() as observer:
                while time.monotonic() < deadline:
                    blockers = observer.scalar(text("select pg_blocking_pids(:pid)"), {"pid": pids["contender"]})
                    if pids["winner"] in blockers:
                        break
                    time.sleep(0.005)
                else:
                    pytest.fail("T2 contender never blocked on winner")
            assert not contender.done()
        finally:
            release.set()
        if winner_commits:
            assert winner.result(timeout=5) == contender.result(timeout=5)
        else:
            with pytest.raises(UploadRetryable):
                winner.result(timeout=5)
            assert contender.result(timeout=5).document_id == values["claim"].document_id
    with sessions() as s:
        assert s.get(UploadOperation, values["claim"].operation_id).status == "COMPLETED"
        assert s.scalar(select(func.count()).select_from(Document).where(Document.id == values["claim"].document_id)) == 1
        assert s.scalar(select(func.count()).select_from(DocumentVersion).where(DocumentVersion.id == values["claim"].version_id)) == 1
    assert storage.objects and not storage.deletes


@pytest.mark.parametrize("committed", [True, False])
def test_t2_uncertainty_survives_cleanup_errors(sessions, upload, committed):
    values, storage, _ = upload
    calls = 0
    primary = RuntimeError("original commit failure")
    def factory():
        nonlocal calls
        calls += 1
        s = sessions()
        if calls == 2:
            commit, rollback, close = s.commit, s.rollback, s.close
            def fail_commit():
                if committed: commit()
                raise primary
            def fail_rollback():
                rollback()
                raise RuntimeError("secondary rollback failure")
            def fail_close():
                close()
                raise RuntimeError("secondary close failure")
            s.commit, s.rollback, s.close = fail_commit, fail_rollback, fail_close
        return s
    with pytest.raises(UploadCommitUncertain) as error:
        run(dict(values, session_factory=factory))
    assert error.value.__cause__ is primary
    assert storage.objects and not storage.deletes and storage.saves == 1


@pytest.mark.parametrize("legacy", [True, False])
def test_legacy_and_unavailable_result_have_structured_reasons(sessions, upload, legacy):
    values, storage, _ = upload
    if legacy:
        with sessions.begin() as s:
            op = s.get(UploadOperation, values["claim"].operation_id)
            for field in ("requesting_user_id", "fingerprint_version", "request_title",
                          "request_size_bytes", "request_content_sha256"):
                setattr(op, field, None)
        expected = RejectionReason.LEGACY_UNRESOLVED
    else:
        run(values)
        with sessions.begin() as s:
            s.get(Document, values["claim"].document_id).deleted_at = s.scalar(select(func.clock_timestamp()))
        expected = RejectionReason.RESULT_UNAVAILABLE
    saves = storage.saves
    with pytest.raises(UploadRejected) as error:
        run(values)
    assert error.value.reason == expected
    assert storage.saves == saves and not storage.deletes


@pytest.mark.parametrize("phase", ["commit", "rollback"])
def test_retryable_sqlstate_never_overrides_uncertain_outcome(sessions, upload, phase):
    from sqlalchemy.exc import DBAPIError
    from psycopg.errors import SerializationFailure
    from services.fenced_upload_service import UploadRollbackUncertain
    values, storage, _ = upload
    calls = 0
    def transient():
        raise DBAPIError(None, None, SerializationFailure("injected serialization failure"))
    def factory():
        nonlocal calls
        calls += 1
        s = sessions()
        if calls == 2:
            if phase == "commit":
                s.commit = transient
            else:
                rollback = s.rollback
                def fail_rollback():
                    rollback()
                    raise RuntimeError("rollback acknowledgment unavailable")
                s.rollback = fail_rollback
        return s
    def fail(*args): transient()
    if phase == "rollback":
        event.listen(DocumentVersion, "before_insert", fail)
    try:
        expected = UploadCommitUncertain if phase == "commit" else UploadRollbackUncertain
        with pytest.raises(expected):
            run(dict(values, session_factory=factory))
    finally:
        if phase == "rollback":
            event.remove(DocumentVersion, "before_insert", fail)
    assert storage.objects and not storage.deletes and storage.saves == 1
    assert_no_results(sessions, values["claim"])
