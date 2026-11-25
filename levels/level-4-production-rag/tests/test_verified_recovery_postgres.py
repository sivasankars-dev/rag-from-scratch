"""Verified recovery with disposable PostgreSQL and instrumented fake storage."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
import os
from threading import Barrier, Event

import pytest
from sqlalchemy import func, select

from app.models import DocumentVersion, Membership, UploadAttempt, UploadOperation
from services.document_storage import ObjectMissing, ObjectAccessDenied
from services.fenced_upload_service import UploadRejected, UploadCommitUncertain, RejectionReason
from services.upload_recovery_service import recover_upload
from services.verified_recovery_service import (
    execute_recovery_upload, SourceOutcome, RecoveryReadFailure, ReadFailureReason, RecoveryWriteUncertain,
)
from test_upload_claim_postgres import sessions, claim_request
from test_upload_recovery_postgres import recovery
from test_fenced_upload_postgres import Storage

pytestmark = pytest.mark.skipif(os.getenv("RUN_DISPOSABLE_UPLOAD_CLAIMS") != "1", reason="Disposable PostgreSQL opt-in")


class RecoveryStorage(Storage):
    def __init__(self, sessions):
        super().__init__(sessions)
        self.opens = []
        self.streams = []
        self.open_error = None
        self.read_error = False
        self.after_read = None

    def open(self, *, key):
        self.no_open_transactions()
        self.opens.append(key)
        if self.open_error:
            raise self.open_error
        if key not in self.objects:
            raise ObjectMissing()
        owner = self
        class Stream(BytesIO):
            def read(self, size=-1):
                owner.no_open_transactions()
                if owner.read_error:
                    raise OSError("connection interrupted")
                return super().read(size)
            def close(self):
                owner.no_open_transactions()
                super().close()
                if owner.after_read:
                    owner.after_read()
        stream = Stream(self.objects[key])
        self.streams.append(stream)
        return stream


@pytest.fixture
def recovered(sessions, recovery):
    request, old, args, _, _ = recovery
    new = recover_upload(**request).claim
    storage = RecoveryStorage(sessions)
    storage.objects[old.storage_key] = b"%PDF-data"
    values = dict(session_factory=storage.session_factory, storage=storage,
                  tenant_id=args["tenant_id"], user_id=args["user_id"], claim=new,
                  fingerprint=args["fingerprint"], title=args["title"])
    return values, storage, old, request


def test_historical_recovery_publishes_new_key(sessions, recovered):
    values, storage, old, _ = recovered
    result = execute_recovery_upload(**values)
    assert result.outcome == SourceOutcome.COMPLETED
    assert result.replay.document_id == old.document_id
    assert storage.opens == [old.storage_key]
    assert all(s.closed for s in storage.streams)
    assert storage.objects[values["claim"].storage_key] == b"%PDF-data"
    assert storage.objects[old.storage_key] == b"%PDF-data" and not storage.deletes
    with sessions() as s:
        assert s.get(DocumentVersion, old.version_id).storage_key == values["claim"].storage_key
    assert execute_recovery_upload(**values) == result
    assert storage.saves == 1


@pytest.mark.parametrize("content", [None, b"%PDF-else", b"%PDF-", b"%PDF-dataEXTRA", b"not-a-pdf"])
def test_missing_or_corrupt_sources_require_body_without_takeover(sessions, recovered, content):
    values, storage, old, _ = recovered
    if content is None: del storage.objects[old.storage_key]
    else: storage.objects[old.storage_key] = content
    result = execute_recovery_upload(**values)
    assert result.outcome == SourceOutcome.SOURCE_REQUIRED
    assert (result.missing, result.corrupted) == ((1, 0) if content is None else (0, 1))
    assert all(s.closed for s in storage.streams)
    assert not storage.saves and not storage.deletes
    with sessions() as s:
        assert s.get(UploadOperation, old.operation_id).status == "PROCESSING"
        assert s.scalar(select(func.count()).select_from(UploadAttempt).where(UploadAttempt.operation_id == old.operation_id)) == 2


@pytest.mark.parametrize("valid", [True, False])
def test_retry_body_preferred_and_invalid_body_falls_back(recovered, valid):
    values, storage, old, _ = recovered
    source = BytesIO(b"%PDF-data" if valid else b"%PDF-else")
    source.seek(3)
    assert execute_recovery_upload(**values, retry_source=source).outcome == SourceOutcome.COMPLETED
    assert source.tell() == 3 and not source.closed
    assert storage.opens == ([] if valid else [old.storage_key])


@pytest.mark.parametrize("kind", ["access", "unavailable", "interrupted"])
def test_infrastructure_failure_is_not_source_required(recovered, kind):
    values, storage, _, _ = recovered
    if kind == "access": storage.open_error = ObjectAccessDenied()
    elif kind == "unavailable": storage.open_error = OSError("service unavailable")
    else: storage.read_error = True
    with pytest.raises(RecoveryReadFailure) as error:
        execute_recovery_upload(**values)
    assert error.value.reason == ReadFailureReason(kind if kind != "access" else "access_denied")
    assert not storage.saves and not storage.deletes
    assert all(s.closed for s in storage.streams)


@pytest.mark.parametrize("change", ["expiry", "revoked", "takeover"])
def test_rechecks_after_download_before_put(sessions, recovered, change):
    values, storage, old, request = recovered
    def change_state():
        with sessions.begin() as s:
            if change == "revoked":
                s.get(Membership, (values["tenant_id"], values["user_id"])).status = "REVOKED"
            else:
                s.get(UploadOperation, old.operation_id).lease_expires_at -= timedelta(days=1)
        if change == "takeover":
            recover_upload(**request)
    storage.after_read = change_state
    with pytest.raises(UploadRejected):
        execute_recovery_upload(**values)
    assert not storage.saves and not storage.deletes
    assert all(s.closed for s in storage.streams)


def test_put_failure_preserves_processing_and_all_objects(sessions, recovered):
    values, storage, old, _ = recovered
    def fail(): raise OSError("ack lost after PUT")
    storage.after_save = fail
    with pytest.raises(RecoveryWriteUncertain):
        execute_recovery_upload(**values)
    assert len(storage.objects) == 2 and not storage.deletes
    with sessions() as s:
        assert s.get(UploadOperation, old.operation_id).status == "PROCESSING"
        assert s.get(DocumentVersion, old.version_id) is None


@pytest.mark.parametrize("committed", [True, False])
def test_ambiguous_t2_preserves_both_objects(sessions, recovered, committed):
    values, storage, old, _ = recovered
    calls = 0
    def factory():
        nonlocal calls
        calls += 1
        s = storage.session_factory()
        if calls == 3:  # candidate discovery, preflight, T2
            commit = s.commit
            def fail():
                if committed: commit()
                raise RuntimeError("commit ack lost")
            s.commit = fail
        return s
    with pytest.raises(UploadCommitUncertain):
        execute_recovery_upload(**dict(values, session_factory=factory))
    assert len(storage.objects) == 2 and not storage.deletes
    with sessions() as s:
        assert s.get(UploadOperation, old.operation_id).status == ("COMPLETED" if committed else "PROCESSING")


def test_concurrent_execution_has_one_result(sessions, recovered):
    values, storage, old, _ = recovered
    storage.concurrent = True
    barrier = Barrier(2)
    storage.after_save = lambda: barrier.wait(5)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(execute_recovery_upload, **values) for _ in range(2)]
        results = [f.result(timeout=10) for f in futures]
    assert results[0] == results[1]
    assert storage.saves == 2 and not storage.deletes
    assert all(s.closed for s in storage.streams)
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(DocumentVersion).where(DocumentVersion.id == old.version_id)) == 1


def test_delayed_put_from_superseded_worker_cannot_publish_or_delete_new_key(sessions, recovered):
    values, storage, old, request = recovered
    waiting, release = Event(), Event()
    storage.concurrent = True
    class DelayedStorage:
        def open(self, **kwargs):
            return storage.open(**kwargs)
        def save(self, *, key, source):
            storage.no_open_transactions()
            content = source.read()
            waiting.set()
            assert release.wait(5)
            storage.objects[key] = content  # Physical PUT completes after deletion.
        def delete(self, **kwargs):
            storage.delete(**kwargs)
    with ThreadPoolExecutor(max_workers=1) as pool:
        stale = pool.submit(execute_recovery_upload, **dict(values, storage=DelayedStorage()))
        try:
            assert waiting.wait(5)
            with sessions.begin() as s:
                s.get(UploadOperation, old.operation_id).lease_expires_at -= timedelta(days=1)
            latest = recover_upload(**request).claim
            storage.after_save = None
            result = execute_recovery_upload(**dict(values, claim=latest), retry_source=BytesIO(b"%PDF-data"))
            assert result.outcome == SourceOutcome.COMPLETED
            # A delayed old cleanup is scoped to the old key, never latest's key.
            storage.delete(key=values["claim"].storage_key)
        finally:
            release.set()
        with pytest.raises(UploadRejected) as error:
            stale.result(timeout=5)
        assert error.value.reason == RejectionReason.STALE_FENCE
    assert storage.objects[latest.storage_key] == b"%PDF-data"
    assert latest.storage_key not in storage.deletes
    assert values["claim"].storage_key in storage.objects  # Late orphan, not published.
    with sessions() as s:
        assert s.get(DocumentVersion, old.version_id).storage_key == latest.storage_key


def test_forged_key_and_cross_tenant_rejected_before_open(recovered):
    from dataclasses import replace
    from uuid import uuid4
    values, storage, _, _ = recovered
    for changed in (dict(values, tenant_id=uuid4()),
                    dict(values, claim=replace(values["claim"], storage_key="arbitrary/key"))):
        with pytest.raises(UploadRejected):
            execute_recovery_upload(**changed)
    assert not storage.opens and not storage.saves


@pytest.mark.parametrize("change", ["expiry", "revoked"])
def test_state_change_after_put_prevents_finalization(sessions, recovered, change):
    values, storage, old, _ = recovered
    def mutate():
        with sessions.begin() as s:
            if change == "expiry":
                s.get(UploadOperation, old.operation_id).lease_expires_at -= timedelta(days=1)
            else:
                s.get(Membership, (values["tenant_id"], values["user_id"])).status = "REVOKED"
    storage.after_save = mutate
    with pytest.raises(UploadRejected):
        execute_recovery_upload(**values)
    assert len(storage.objects) == 2 and not storage.deletes
    with sessions() as s:
        assert s.get(DocumentVersion, old.version_id) is None


def test_retryable_t2_preserves_recovery_objects(sessions, recovered):
    from sqlalchemy import event, text
    from services.fenced_upload_service import UploadRetryable
    values, storage, old, _ = recovered
    def fail(mapper, connection, target):
        connection.execute(text("DO $$ BEGIN RAISE EXCEPTION 'deadlock' USING ERRCODE = '40P01'; END $$"))
    event.listen(DocumentVersion, "before_insert", fail)
    try:
        with pytest.raises(UploadRetryable):
            execute_recovery_upload(**values)
    finally:
        event.remove(DocumentVersion, "before_insert", fail)
    assert len(storage.objects) == 2 and not storage.deletes
    with sessions() as s:
        assert s.get(UploadOperation, old.operation_id).status == "PROCESSING"
        assert s.get(DocumentVersion, old.version_id) is None


def test_corrupt_newer_history_falls_back_to_verified_older_attempt(sessions, recovered):
    values, storage, old, request = recovered
    storage.objects[values["claim"].storage_key] = b"%PDF-else"
    with sessions.begin() as s:
        s.get(UploadOperation, old.operation_id).lease_expires_at -= timedelta(days=1)
    latest = recover_upload(**request).claim
    assert execute_recovery_upload(**dict(values, claim=latest)).outcome == SourceOutcome.COMPLETED
    assert storage.opens == [values["claim"].storage_key, old.storage_key]
    assert all(s.closed for s in storage.streams)
    assert storage.objects[latest.storage_key] == b"%PDF-data"


def test_snapshot_read_bound_and_spooled_resource_closure():
    from tempfile import SpooledTemporaryFile
    from services.upload_idempotency import fingerprint_pdf_upload
    from services.verified_recovery_service import _verify
    fp = fingerprint_pdf_upload(source=BytesIO(b"%PDF-data"), size_bytes=9, title="source.pdf")
    source = BytesIO(b"%PDF-data" + b"x" * 100000)
    with SpooledTemporaryFile(max_size=4, mode="w+b") as snapshot:
        assert not _verify(source, snapshot, fp, "source.pdf")
        assert source.tell() == 10  # Never drain an oversized object.
    assert snapshot.closed
