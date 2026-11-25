"""Opt-in T1 integration tests; create/drop only a unique local disposable DB."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
import os
from pathlib import Path
from threading import Barrier, Event
import time
from types import SimpleNamespace
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker

from app.models import Document, DocumentVersion, Membership, Tenant, UploadAttempt, UploadOperation, User
from app.database import create_claim_session_factory
from services.upload_claim_service import ClaimCommitUncertain, ClaimOutcome, claim_upload
from services.upload_idempotency import fingerprint_pdf_upload

pytestmark = pytest.mark.skipif(os.getenv("RUN_DISPOSABLE_UPLOAD_CLAIMS") != "1", reason="Explicit disposable PostgreSQL opt-in required")


@pytest.fixture(scope="module")
def sessions():
    from app.config import load_database_url, load_test_database_url
    source = make_url(load_test_database_url())
    assert source.host in {"127.0.0.1", "localhost", "::1"}
    name = f"rag_claim_verify_{uuid4().hex}_test"
    assert name not in {source.database, make_url(load_database_url()).database}
    admin = create_engine(source, isolation_level="AUTOCOMMIT", hide_parameters=True)
    target = source.set(database=name)
    engine = create_engine(target, hide_parameters=True)
    created = False
    patch = pytest.MonkeyPatch()
    try:
        with admin.connect() as c:
            assert c.scalar(text("select current_database()")) == source.database
            c.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE template0')
            created = True
        with engine.connect() as c:
            assert c.scalar(text("select current_database()")) == name
            print("CLAIM TEST DATABASE:", name)
        patch.setenv("TEST_DATABASE_URL", target.render_as_string(hide_password=False))
        cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
        # Do not let migrations/env.py reconfigure logging for unrelated tests.
        cfg.config_file_name = None
        cfg.cmd_opts = SimpleNamespace(x=["database=test"])
        def guard(connection, record):
            with connection.cursor() as cursor:
                cursor.execute("select current_database()")
                assert cursor.fetchone()[0] == name
            connection.rollback()
        event.listen(Engine, "connect", guard)
        try:
            command.upgrade(cfg, "7b9c2d4e6f80")
        finally:
            event.remove(Engine, "connect", guard)
        yield create_claim_session_factory(engine)
    finally:
        patch.undo()
        engine.dispose()
        if created:
            with admin.connect() as c:
                c.exec_driver_sql(f'DROP DATABASE "{name}"')
                assert not c.scalar(text("select 1 from pg_database where datname=:n"), {"n": name})
            print("CLAIM TEST DATABASE REMOVED:", name)
        admin.dispose()


@pytest.fixture
def claim_request(sessions):
    user, other_user, tenant, other_tenant = (uuid4() for _ in range(4))
    with sessions.begin() as s:
        s.add_all([User(id=u, name="Claim test", email=f"{u}@example.test") for u in (user, other_user)])
        s.add_all([Tenant(id=t, name="Claim test") for t in (tenant, other_tenant)])
        s.flush()
        s.add_all([Membership(tenant_id=t, user_id=u) for t in (tenant, other_tenant) for u in (user, other_user)])
    args = dict(session_factory=sessions, tenant_id=tenant, user_id=user, idempotency_key=str(uuid4()), title="source.pdf",
                fingerprint=fingerprint_pdf_upload(source=BytesIO(b"%PDF-data"), size_bytes=9, title="source.pdf"))
    return args, other_user, other_tenant


def test_claim_commits_both_records_and_no_result_rows(sessions, claim_request):
    args, _, _ = claim_request
    decision = claim_upload(**args)
    assert decision.outcome == ClaimOutcome.CLAIMED
    claim = decision.claim
    with sessions() as s:
        op = s.get(UploadOperation, claim.operation_id)
        attempt = s.get(UploadAttempt, claim.attempt_id)
        assert op.status == "PROCESSING"
        assert op.requesting_user_id == args["user_id"]
        assert op.lease_token == attempt.lease_token == claim.lease_token
        assert op.lease_generation == attempt.lease_generation == 1
        assert attempt.expected_sha256 == args["fingerprint"].content_sha256
        assert attempt.expected_size_bytes == 9
        assert attempt.reserved_document_id == claim.document_id
        assert attempt.reserved_version_id == claim.version_id
        assert attempt.storage_key == claim.storage_key
        assert f"/attempts/{claim.attempt_id}/" in claim.storage_key
        assert s.get(Document, claim.document_id) is None
        assert s.get(DocumentVersion, claim.version_id) is None
        assert op.lease_expires_at > s.scalar(select(func.clock_timestamp()))


def test_retries_preserve_canonical_ids_and_metadata(sessions, claim_request):
    args, _, _ = claim_request
    first = claim_upload(**args).claim
    assert claim_upload(**args).outcome == ClaimOutcome.IN_PROGRESS
    changed = dict(args, title="other.pdf", fingerprint=fingerprint_pdf_upload(source=BytesIO(b"%PDF-data"), size_bytes=9, title="other.pdf"))
    assert claim_upload(**changed).outcome == ClaimOutcome.CONFLICT
    with sessions() as s:
        rows = s.scalars(select(UploadAttempt).where(UploadAttempt.operation_id == first.operation_id)).all()
        assert len(rows) == 1
        assert rows[0].reserved_document_id == first.document_id
        assert rows[0].reserved_version_id == first.version_id
        assert s.get(UploadOperation, first.operation_id).request_title == "source.pdf"


def test_owner_and_tenant_isolation(claim_request):
    args, other, tenant = claim_request
    claim_upload(**args)
    denied = claim_upload(**dict(args, user_id=other))
    assert denied.outcome == ClaimOutcome.ACCESS_DENIED
    assert denied.claim is None and denied.replay is None
    assert claim_upload(**dict(args, tenant_id=tenant)).outcome == ClaimOutcome.CLAIMED


@pytest.mark.parametrize("entity", ["user", "tenant", "membership"])
def test_revocation_denies_retry(sessions, claim_request, entity):
    args, _, _ = claim_request
    claim_upload(**args)
    with sessions.begin() as s:
        if entity == "user":
            s.get(User, args["user_id"]).status = "DISABLED"
        elif entity == "tenant":
            s.get(Tenant, args["tenant_id"]).status = "DISABLED"
        else:
            s.get(Membership, (args["tenant_id"], args["user_id"])).status = "REVOKED"
    assert claim_upload(**args).outcome == ClaimOutcome.ACCESS_DENIED


def test_legacy_expired_failed_decisions(sessions, claim_request):
    args, _, _ = claim_request
    with sessions.begin() as s:
        s.add(UploadOperation(id=uuid4(), tenant_id=args["tenant_id"], idempotency_key=args["idempotency_key"], request_fingerprint="a" * 64))
    assert claim_upload(**args).outcome == ClaimOutcome.LEGACY_UNRESOLVED
    args = dict(args, idempotency_key=str(uuid4()))
    claim = claim_upload(**args).claim
    with sessions.begin() as s:
        op = s.get(UploadOperation, claim.operation_id)
        op.lease_expires_at -= timedelta(days=1)
    assert claim_upload(**args).outcome == ClaimOutcome.RECOVERY_REQUIRED
    with sessions.begin() as s:
        op = s.get(UploadOperation, claim.operation_id)
        assert op.lease_generation == 1 and op.lease_token == claim.lease_token
        op.status = "FAILED"
    assert claim_upload(**args).outcome == ClaimOutcome.FAILED


def test_completed_replay_and_deleted_result(sessions, claim_request):
    args, other, _ = claim_request
    claim = claim_upload(**args).claim
    # Fixture-only completion, not production T2 implementation.
    with sessions.begin() as s:
        s.add(Document(id=claim.document_id, tenant_id=args["tenant_id"], owner_user_id=args["user_id"], title="edited title.pdf"))
        s.flush()
        s.add(DocumentVersion(id=claim.version_id, document_id=claim.document_id, version_number=1, status="READY", storage_key=claim.storage_key))
        s.flush()
        op = s.get(UploadOperation, claim.operation_id)
        op.document_id, op.version_id, op.status = claim.document_id, claim.version_id, "COMPLETED"
    result = claim_upload(**args)
    assert result.outcome == ClaimOutcome.REPLAY
    assert result.replay.document_id == claim.document_id
    assert result.replay.version_id == claim.version_id
    assert result.replay.filename == "source.pdf" and result.replay.size_bytes == 9
    assert claim_upload(**dict(args, user_id=other)).replay is None
    with sessions.begin() as s:
        s.get(Document, claim.document_id).deleted_at = s.scalar(select(func.clock_timestamp()))
    assert claim_upload(**args).outcome == ClaimOutcome.RESULT_UNAVAILABLE


@pytest.mark.parametrize("different_payload", [False, True])
def test_concurrent_claims_use_independent_connections(sessions, claim_request, different_payload):
    args, _, _ = claim_request
    barrier = Barrier(2)
    def run(number):
        local = dict(args)
        if number and different_payload:
            local["fingerprint"] = fingerprint_pdf_upload(source=BytesIO(b"%PDF-else"), size_bytes=9, title="source.pdf")
        barrier.wait(timeout=5)
        return claim_upload(**local)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, [0, 1]))
    expected = ClaimOutcome.CONFLICT if different_payload else ClaimOutcome.IN_PROGRESS
    assert sorted(r.outcome.value for r in results) == sorted([ClaimOutcome.CLAIMED.value, expected.value])
    with sessions() as s:
        operations = s.scalars(select(UploadOperation).where(UploadOperation.tenant_id == args["tenant_id"])).all()
        assert len(operations) == 1
        assert s.scalar(select(func.count()).select_from(UploadAttempt).where(UploadAttempt.operation_id == operations[0].id)) == 1


def test_bounded_wait_on_uncommitted_unique_conflict(sessions, claim_request):
    args, _, _ = claim_request
    with sessions.begin() as blocker:
        blocker.add(UploadOperation(id=uuid4(), tenant_id=args["tenant_id"], idempotency_key=args["idempotency_key"], request_fingerprint="a" * 64))
        blocker.flush()
        assert claim_upload(**dict(args, lock_timeout_ms=100, statement_timeout_ms=1000)).outcome == ClaimOutcome.BUSY


def test_attempt_failure_rolls_back_operation(sessions, claim_request):
    args, _, _ = claim_request
    def fail(mapper, connection, target):
        raise RuntimeError("attempt insert failed")
    event.listen(UploadAttempt, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="attempt insert failed"):
            claim_upload(**args)
    finally:
        event.remove(UploadAttempt, "before_insert", fail)
    with sessions() as s:
        assert s.scalar(select(UploadOperation.id).where(UploadOperation.idempotency_key == args["idempotency_key"])) is None


def test_commit_acknowledgment_loss_returns_no_claim(sessions, claim_request):
    args, _, _ = claim_request
    def factory():
        s = sessions()
        original = s.commit
        def commit_then_raise():
            original()
            raise RuntimeError("ack lost")
        s.commit = commit_then_raise
        return s
    with pytest.raises(ClaimCommitUncertain):
        claim_upload(**dict(args, session_factory=factory))
    assert claim_upload(**args).outcome == ClaimOutcome.IN_PROGRESS


def test_rejects_inconsistent_fingerprint_before_session(claim_request):
    args, _, _ = claim_request
    with pytest.raises(ValueError, match="Fingerprint"):
        claim_upload(**dict(args, title="different.pdf"))


def test_claim_factory_overrides_server_isolation_and_rejects_wrong_factory(sessions, claim_request):
    args, _, _ = claim_request
    repeatable = create_engine(sessions.kw["bind"].url, isolation_level="REPEATABLE READ")
    try:
        wrong = sessionmaker(repeatable)
        with wrong() as s:
            assert s.scalar(text("show transaction_isolation")) == "repeatable read"
        dedicated = create_claim_session_factory(repeatable)
        with dedicated() as s:
            assert s.scalar(text("show transaction_isolation")) == "read committed"
        assert claim_upload(**dict(args, session_factory=dedicated)).outcome == ClaimOutcome.CLAIMED
        with pytest.raises(ValueError, match="READ COMMITTED"):
            claim_upload(**dict(args, session_factory=wrong))
        with wrong() as s:
            assert s.scalar(text("show transaction_isolation")) == "repeatable read"
    finally:
        repeatable.dispose()


@pytest.mark.parametrize("winner_commits", [True, False])
def test_deterministic_overlapping_transactions(sessions, claim_request, winner_commits):
    args, _, _ = claim_request
    winner_ready, contender_connected, release = Event(), Event(), Event()
    pids = {}
    def factory(label):
        def make():
            s = sessions()
            def connected(session, transaction, connection):
                pids[label] = connection.scalar(text("select pg_backend_pid()"))
                if label == "contender":
                    contender_connected.set()
            event.listen(s, "after_begin", connected)
            if label == "winner":
                original = s.commit
                def commit():
                    winner_ready.set()  # Operation AND attempt are flushed, not committed.
                    assert release.wait(8), "Test did not release winner"
                    if not winner_commits:
                        raise RuntimeError("simulated rejection before commit")
                    original()
                s.commit = commit
            return s
        return make
    with ThreadPoolExecutor(max_workers=2) as executor:
        winner = executor.submit(claim_upload, **dict(args, session_factory=factory("winner"), lock_timeout_ms=5000, statement_timeout_ms=7000))
        try:
            assert winner_ready.wait(5)
            contender = executor.submit(claim_upload, **dict(args, session_factory=factory("contender"), lock_timeout_ms=5000, statement_timeout_ms=7000))
            assert contender_connected.wait(5)
            assert pids["winner"] != pids["contender"]
            deadline = time.monotonic() + 3
            with sessions() as observer:
                while time.monotonic() < deadline:
                    blockers = observer.scalar(text("select pg_blocking_pids(:pid)"), {"pid": pids["contender"]})
                    if pids["winner"] in blockers:
                        break
                    time.sleep(0.01)
                else:
                    pytest.fail("Contender never blocked on the uncommitted winner")
            assert not contender.done()
        finally:
            release.set()
        if winner_commits:
            assert winner.result(timeout=5).outcome == ClaimOutcome.CLAIMED
            assert contender.result(timeout=5).outcome == ClaimOutcome.IN_PROGRESS
        else:
            with pytest.raises(ClaimCommitUncertain):
                winner.result(timeout=5)
            assert contender.result(timeout=5).outcome == ClaimOutcome.CLAIMED
    with sessions() as s:
        operations = s.scalars(select(UploadOperation).where(UploadOperation.tenant_id == args["tenant_id"])).all()
        assert len(operations) == 1
        assert s.scalar(select(func.count()).select_from(UploadAttempt).where(UploadAttempt.operation_id == operations[0].id)) == 1


@pytest.mark.parametrize("committed", [True, False])
def test_commit_uncertainty_survives_both_cleanup_failures(sessions, claim_request, committed, caplog):
    args, _, _ = claim_request
    cleaned = []
    primary = RuntimeError("original commit failure")
    def factory():
        s = sessions()
        commit, rollback, close = s.commit, s.rollback, s.close
        def fail_commit():
            if committed:
                commit()
            raise primary
        def fail_rollback():
            rollback()
            cleaned.append("rollback")
            raise RuntimeError("secondary rollback failure")
        def fail_close():
            close()
            cleaned.append("close")
            raise RuntimeError("secondary close failure")
        s.commit, s.rollback, s.close = fail_commit, fail_rollback, fail_close
        return s
    with pytest.raises(ClaimCommitUncertain) as error:
        claim_upload(**dict(args, session_factory=factory))
    assert error.value.__cause__ is primary
    assert cleaned == ["rollback", "close"]
    assert "secondary rollback failure" in caplog.text
    assert "secondary close failure" in caplog.text
    expected = ClaimOutcome.IN_PROGRESS if committed else ClaimOutcome.CLAIMED
    assert claim_upload(**args).outcome == expected


@pytest.mark.parametrize("delay_phase", ["before_commit", "after_commit"])
def test_expired_during_delayed_t1_never_returns_usable_claim(sessions, claim_request, delay_phase):
    args, _, _ = claim_request
    def factory():
        s = sessions()
        original = s.commit
        def delayed_commit():
            if delay_phase == "before_commit":
                s.execute(text("select pg_sleep(1.1)"))
            original()
            if delay_phase == "after_commit":
                time.sleep(1.1)
        s.commit = delayed_commit
        return s
    result = claim_upload(**dict(args, session_factory=factory, lease_seconds=1))
    assert result.outcome == ClaimOutcome.RECOVERY_REQUIRED
    assert result.claim is None and result.replay is None
    with sessions() as s:
        op = s.scalar(select(UploadOperation).where(UploadOperation.idempotency_key == args["idempotency_key"]))
        assert op.status == "PROCESSING" and op.lease_generation == 1
        assert op.lease_expires_at <= s.scalar(select(func.clock_timestamp()))
        assert s.scalar(select(func.count()).select_from(UploadAttempt).where(UploadAttempt.operation_id == op.id)) == 1
    assert claim_upload(**args).outcome == ClaimOutcome.RECOVERY_REQUIRED


def complete_fixture(sessions, args):
    claim = claim_upload(**args).claim
    with sessions.begin() as s:
        s.add(Document(id=claim.document_id, tenant_id=args["tenant_id"], owner_user_id=args["user_id"], title=args["title"]))
        s.flush()
        s.add(DocumentVersion(id=claim.version_id, document_id=claim.document_id, version_number=1, status="READY", storage_key=claim.storage_key))
        s.flush()
        op = s.get(UploadOperation, claim.operation_id)
        op.document_id, op.version_id, op.status = claim.document_id, claim.version_id, "COMPLETED"
    return claim


@pytest.mark.parametrize("change", ["user", "tenant", "membership", "different_caller", "wrong_owner", "pending", "failed", "deleted"])
def test_completed_replay_negatives(sessions, claim_request, change):
    args, other_user, _ = claim_request
    claim = complete_fixture(sessions, args)
    with sessions.begin() as s:
        if change == "user":
            s.get(User, args["user_id"]).status = "DISABLED"
        elif change == "tenant":
            s.get(Tenant, args["tenant_id"]).status = "DISABLED"
        elif change == "membership":
            s.get(Membership, (args["tenant_id"], args["user_id"])).status = "REVOKED"
        elif change == "wrong_owner":
            s.get(Document, claim.document_id).owner_user_id = other_user
        elif change in ("pending", "failed"):
            s.get(DocumentVersion, claim.version_id).status = change.upper()
        elif change == "deleted":
            s.get(Document, claim.document_id).deleted_at = s.scalar(select(func.clock_timestamp()))
    if change == "different_caller":
        args = dict(args, user_id=other_user)
    result = claim_upload(**args)
    expected = ClaimOutcome.ACCESS_DENIED if change in ("user", "tenant", "membership", "different_caller") else ClaimOutcome.RESULT_UNAVAILABLE
    assert result.outcome == expected
    assert result.claim is None and result.replay is None


def test_retry_decisions_preserve_entire_durable_records(sessions, claim_request):
    args, other_user, _ = claim_request
    claim = claim_upload(**args).claim
    def snapshot():
        with sessions() as s:
            op = dict(s.execute(select(UploadOperation.__table__).where(UploadOperation.id == claim.operation_id)).mappings().one())
            attempt = dict(s.execute(select(UploadAttempt.__table__).where(UploadAttempt.id == claim.attempt_id)).mappings().one())
            return op, attempt
    before = snapshot()
    assert claim_upload(**args).outcome == ClaimOutcome.IN_PROGRESS
    assert claim_upload(**dict(args, user_id=other_user)).outcome == ClaimOutcome.ACCESS_DENIED
    changed = dict(args, fingerprint=fingerprint_pdf_upload(source=BytesIO(b"%PDF-else"), size_bytes=9, title=args["title"]))
    assert claim_upload(**changed).outcome == ClaimOutcome.CONFLICT
    assert snapshot() == before  # Includes timestamps, tokens, metadata and both reserved IDs.
    with sessions.begin() as s:
        s.get(UploadOperation, claim.operation_id).lease_expires_at -= timedelta(days=1)
    expired = snapshot()
    assert claim_upload(**args).outcome == ClaimOutcome.RECOVERY_REQUIRED
    assert snapshot() == expired


def test_replay_does_not_mutate_completed_records(sessions, claim_request):
    args, _, _ = claim_request
    claim = complete_fixture(sessions, args)
    def snapshot():
        with sessions() as s:
            return (
                dict(s.execute(select(UploadOperation.__table__).where(UploadOperation.id == claim.operation_id)).mappings().one()),
                dict(s.execute(select(UploadAttempt.__table__).where(UploadAttempt.id == claim.attempt_id)).mappings().one()),
            )
    before = snapshot()
    assert claim_upload(**args).outcome == ClaimOutcome.REPLAY
    assert claim_upload(**args).outcome == ClaimOutcome.REPLAY
    assert snapshot() == before


def test_claim_acknowledged_commit_close_failure_returns_known_decision(sessions, claim_request, caplog):
    args, _, _ = claim_request
    def factory():
        s = sessions()
        close = s.close
        def fail_close():
            close()
            raise RuntimeError("close failed after commit")
        s.close = fail_close
        return s
    result = claim_upload(**dict(args, session_factory=factory))
    assert result.outcome == ClaimOutcome.CLAIMED
    assert claim_upload(**args).outcome == ClaimOutcome.IN_PROGRESS
    assert "Committed claim session cleanup failed" in caplog.text
