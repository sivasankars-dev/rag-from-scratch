"""Opt-in real MinIO + disposable PostgreSQL. Fault wrappers are test-only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
import json
import os
import subprocess
import sys
from threading import Event
from urllib.parse import urlparse
from uuid import uuid4

import boto3
from botocore.config import Config
import pytest
from sqlalchemy import select, text

from app.models import Membership, Tenant, User, UploadAttempt, UploadOperation, DocumentVersion
from services.storage_factory import load_storage_settings
from services.minio_storage import MinIOStorage
from services.document_storage import ObjectMissing, ObjectAccessDenied
from services.upload_claim_service import claim_upload
from services.upload_recovery_service import recover_upload
from services.verified_recovery_service import execute_recovery_upload, SourceOutcome
from services.upload_reconciliation_service import reconcile_upload, ReconcileOutcome
from test_upload_claim_postgres import sessions, claim_request
from test_keyed_upload_router_postgres import api as fake_api, signing_key, post

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_REAL_MINIO_E2E") != "1" or os.getenv("RUN_DISPOSABLE_UPLOAD_CLAIMS") != "1",
    reason="Explicit real MinIO and disposable PostgreSQL opt-ins required")


@pytest.fixture(scope="module")
def real_storage():
    settings = load_storage_settings()
    assert urlparse(settings.endpoint).hostname in {"localhost", "127.0.0.1", "::1"}
    bucket = "rag-f02-e2e-" + uuid4().hex
    assert bucket != settings.bucket
    client = boto3.client("s3", endpoint_url=settings.endpoint,
        aws_access_key_id=settings.access_key, aws_secret_access_key=settings.secret_key,
        region_name=settings.region, config=Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 0}))
    created = False
    try:
        client.create_bucket(Bucket=bucket)
        created = True
        print("E2E MINIO BUCKET:", bucket)
        yield MinIOStorage(client, bucket)
    finally:
        if created:
            # Teardown is restricted to this run's random bucket, never configured data.
            for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
                objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
                if objects:
                    result = client.delete_objects(Bucket=bucket, Delete={"Objects": objects})
                    assert not result.get("Errors")
            client.delete_bucket(Bucket=bucket)
            print("E2E MINIO BUCKET REMOVED:", bucket)
        client.close()


@pytest.fixture
def real_api(fake_api, real_storage, sessions):
    client, app, _, args, token, other, tenant = fake_api
    class CheckedStorage:
        check_transactions = True
        after_save = None
        def check(self):
            if self.check_transactions:
                with sessions() as s:
                    assert s.scalar(text("select count(*) from pg_stat_activity where datname=current_database() and pid<>pg_backend_pid() and backend_type='client backend' and xact_start is not null")) == 0
        def save(self, **kwargs):
            self.check()
            real_storage.save(**kwargs)
            if self.after_save: self.after_save()
        def open(self, **kwargs):
            self.check()
            return real_storage.open(**kwargs)
        def delete(self, **kwargs):
            self.check()
            return real_storage.delete(**kwargs)
    storage = CheckedStorage()
    app.state.document_storage = storage
    return client, app, storage, args, token, other, tenant


def operation(sessions, api):
    with sessions() as s:
        op = s.scalar(select(UploadOperation).where(UploadOperation.tenant_id == api[3]["tenant_id"],
                                                  UploadOperation.idempotency_key == "key"))
        attempt = s.scalar(select(UploadAttempt).where(UploadAttempt.operation_id == op.id,
                                                       UploadAttempt.lease_generation == op.lease_generation))
        return op, attempt


def test_real_http_replay_conflict_bytes(real_api, real_storage, sessions):
    first = post(real_api)
    assert first.status_code == 200
    assert post(real_api).json() == first.json()
    assert post(real_api, content=b"%PDF-else").status_code == 409
    op, attempt = operation(sessions, real_api)
    with real_storage.open(key=attempt.storage_key) as stream: content = stream.read()
    assert content == b"%PDF-data" and len(content) == op.request_size_bytes
    assert sha256(content).hexdigest() == op.request_content_sha256
    with sessions() as s:
        assert s.get(DocumentVersion, op.version_id).storage_key == attempt.storage_key
    assert "/attempts/" in attempt.storage_key and attempt.storage_key not in first.text


def test_real_concurrent_same_key(real_api):
    entered, release = Event(), Event()
    def delayed():
        entered.set()
        assert release.wait(5)
    real_api[2].after_save = delayed
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(post, real_api)
        try:
            assert entered.wait(5)
            assert post(real_api).json()["detail"]["code"] == "in_progress"
        finally: release.set()
        assert first.result(timeout=5).status_code == 200
    real_api[2].after_save = None
    assert post(real_api).status_code == 200


@pytest.mark.parametrize("entity", ["membership", "user", "tenant"])
def test_real_authorization(real_api, sessions, entity):
    args = real_api[3]
    with sessions.begin() as s:
        if entity == "membership": s.get(Membership, (args["tenant_id"], args["user_id"])).status = "REVOKED"
        elif entity == "user": s.get(User, args["user_id"]).status = "DISABLED"
        else: s.get(Tenant, args["tenant_id"]).status = "DISABLED"
    assert post(real_api).status_code == (401 if entity == "user" else 403)


def test_real_tenant_isolation_and_f01(real_api):
    assert post(real_api).status_code == 200
    assert post(real_api, token=real_api[4](real_api[5])).status_code == 403
    other = post(real_api, path=f"/tenants/{real_api[6]}/documents/upload")
    assert other.status_code == 200
    real_api[2].check_transactions = False  # F01 retains its original transaction policy.
    a, b = post(real_api, key=None), post(real_api, key=None)
    assert a.status_code == b.status_code == 200
    assert a.json()["document_id"] != b.json()["document_id"]


def test_real_historical_recovery(real_api, real_storage, sessions):
    args = dict(real_api[3], idempotency_key="key")
    old = claim_upload(**args).claim
    real_storage.save(key=old.storage_key, source=BytesIO(b"%PDF-data"))
    with sessions.begin() as s:
        s.get(UploadOperation, old.operation_id).lease_expires_at -= timedelta(days=1)
    new = recover_upload(session_factory=sessions, tenant_id=args["tenant_id"], user_id=args["user_id"],
                         operation_id=old.operation_id).claim
    result = execute_recovery_upload(session_factory=sessions, storage=real_api[2],
        tenant_id=args["tenant_id"], user_id=args["user_id"], claim=new,
        fingerprint=args["fingerprint"], title=args["title"])
    assert result.outcome == SourceOutcome.COMPLETED and new.document_id == old.document_id
    assert new.storage_key != old.storage_key
    for key in (new.storage_key, old.storage_key):
        with real_storage.open(key=key) as stream: assert stream.read() == b"%PDF-data"
    assert post(real_api).json()["document_id"] == str(old.document_id)


def test_real_missing_and_access_denied(real_storage):
    with pytest.raises(ObjectMissing): real_storage.open(key="missing-" + uuid4().hex)
    settings = load_storage_settings()
    from botocore import UNSIGNED
    anonymous = boto3.client("s3", endpoint_url=settings.endpoint,
        config=Config(signature_version=UNSIGNED, connect_timeout=2, read_timeout=3, retries={"max_attempts": 0}))
    key = "private-" + uuid4().hex
    real_storage.save(key=key, source=BytesIO(b"%PDF-data"))
    try:
        with pytest.raises(ObjectAccessDenied):
            MinIOStorage(anonymous, real_storage.bucket).open(key=key)
    finally: anonymous.close()


def test_real_put_ack_loss_preserves_and_reconciles(real_api, real_storage, sessions):
    def lost(): raise TimeoutError("SECRET_FAULT_DETAILS")
    real_api[2].after_save = lost
    response = post(real_api)
    assert response.status_code == 503 and "SECRET" not in response.text
    op, attempt = operation(sessions, real_api)
    from services.upload_recovery_service import _claim
    result = reconcile_upload(**dict(real_api[3], idempotency_key="key"),
                              storage=real_api[2], claim=_claim(op, attempt))
    assert result.outcome == ReconcileOutcome.COMPLETED
    with real_storage.open(key=attempt.storage_key) as stream: assert stream.read() == b"%PDF-data"


@pytest.mark.parametrize("kind", ["timeout", "interrupted"])
def test_real_get_with_test_only_read_fault(real_api, real_storage, sessions, kind):
    args = dict(real_api[3], idempotency_key="key")
    claim = claim_upload(**args).claim
    real_storage.save(key=claim.storage_key, source=BytesIO(b"%PDF-data"))
    closed = []
    class Fault:
        def open(self, **kwargs):
            source = real_storage.open(**kwargs)
            class Stream:
                def read(self, size):
                    source.read(1)
                    raise TimeoutError("SECRET") if kind == "timeout" else OSError("SECRET")
                def close(self):
                    source.close()
                    closed.append(True)
            return Stream()
    result = reconcile_upload(**args, storage=Fault(), claim=claim)
    assert result.outcome == ReconcileOutcome.UNRESOLVED and closed
    with real_storage.open(key=claim.storage_key) as stream: assert stream.read() == b"%PDF-data"


@pytest.mark.parametrize("committed", [True, False])
def test_real_t2_ack_loss(real_api, real_storage, sessions, committed):
    args = dict(real_api[3], idempotency_key="key")
    claim = claim_upload(**args).claim
    from services.fenced_upload_service import execute_claimed_upload, UploadCommitUncertain
    calls = 0
    def factory():
        nonlocal calls
        calls += 1
        s = sessions()
        if calls == 2:
            commit = s.commit
            def lose():
                if committed: commit()
                raise RuntimeError("ack lost")
            s.commit = lose
        return s
    with pytest.raises(UploadCommitUncertain):
        execute_claimed_upload(session_factory=factory, storage=real_api[2],
            tenant_id=args["tenant_id"], user_id=args["user_id"], claim=claim,
            fingerprint=args["fingerprint"], title=args["title"], source=BytesIO(b"%PDF-data"))
    assert reconcile_upload(**args, storage=real_api[2], claim=claim).outcome == ReconcileOutcome.COMPLETED


@pytest.mark.parametrize("phase", ["t1", "put", "before_commit", "after_commit"])
def test_process_death_with_real_storage(real_api, real_storage, sessions, phase):
    args = real_api[3]
    # Child creates its own DB/SDK connections. Only disposable target/bucket supplied.
    payload = dict(url=sessions.kw["bind"].url.render_as_string(hide_password=False),
                   tenant=str(args["tenant_id"]), user=str(args["user_id"]),
                   bucket=real_storage.bucket, phase=phase)
    script = r"""
import json, os, sys
from io import BytesIO
from uuid import UUID
from sqlalchemy import create_engine
from app.database import create_claim_session_factory
from services.storage_factory import load_storage_settings, create_document_storage
from services.upload_claim_service import claim_upload
from services.upload_idempotency import fingerprint_pdf_upload
from services.fenced_upload_service import execute_claimed_upload
p=json.load(sys.stdin)
assert p["bucket"].startswith("rag-f02-e2e-")
engine=create_engine(p["url"])
assert engine.url.database.startswith("rag_claim_verify_") and engine.url.database.endswith("_test")
factory=create_claim_session_factory(engine)
settings=load_storage_settings()
from dataclasses import replace
storage=create_document_storage(replace(settings,bucket=p["bucket"]))
fp=fingerprint_pdf_upload(source=BytesIO(b"%PDF-data"),size_bytes=9,title="source.pdf")
claim=claim_upload(session_factory=factory,tenant_id=UUID(p["tenant"]),user_id=UUID(p["user"]),
 idempotency_key="key",title="source.pdf",fingerprint=fp).claim
if p["phase"]=="t1": os._exit(73)
save=storage.save
def put(**kw):
 save(**kw)
 if p["phase"]=="put": os._exit(73)
storage.save=put
calls=0
def sf():
 global calls
 calls+=1
 s=factory()
 if calls==2:
  commit=s.commit
  def finish():
   if p["phase"]=="before_commit": os._exit(73)
   commit()
   if p["phase"]=="after_commit": os._exit(73)
  s.commit=finish
 return s
execute_claimed_upload(session_factory=sf,storage=storage,tenant_id=UUID(p["tenant"]),user_id=UUID(p["user"]),
 claim=claim,fingerprint=fp,title="source.pdf",source=BytesIO(b"%PDF-data"))
"""
    result = subprocess.run([sys.executable, "-c", script], input=json.dumps(payload),
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 73, "Child did not reach requested crash boundary"
    op, attempt = operation(sessions, real_api)
    assert op.status == ("COMPLETED" if phase == "after_commit" else "PROCESSING")
    if phase == "t1":
        with pytest.raises(ObjectMissing): real_storage.open(key=attempt.storage_key)
        with sessions.begin() as s:
            s.get(UploadOperation, op.id).lease_expires_at -= timedelta(days=1)
        assert post(real_api).json()["document_id"] == str(attempt.reserved_document_id)
    else:
        from services.upload_recovery_service import _claim
        decision = reconcile_upload(**dict(args, idempotency_key="key"),
                                    storage=real_api[2], claim=_claim(op, attempt))
        assert decision.outcome == ReconcileOutcome.COMPLETED


def test_tcp_http_pdf_and_disconnect_after_put(real_api, real_storage, sessions):
    """Real uvicorn TCP listener; disconnect after real PUT but before T2."""
    import socket
    import time
    from threading import Thread
    import httpx
    import uvicorn
    from pypdf import PdfWriter
    _, app, storage, args, token, _, _ = real_api
    pdf = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(pdf)
    content = pdf.getvalue()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False, lifespan="off"))
    thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    entered, release = Event(), Event()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        path = f"/tenants/{args['tenant_id']}/documents/upload"
        headers = {"Authorization": "Bearer " + token(), "Idempotency-Key": "tcp"}
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
            response = client.post(path, headers=headers, files={"file": ("actual.pdf", content, "application/pdf")})
            assert response.status_code == 200
            assert client.post(path, headers=headers, files={"file": ("actual.pdf", content)}).json() == response.json()
        with sessions() as s:
            op = s.scalar(select(UploadOperation).where(UploadOperation.tenant_id == args["tenant_id"],
                                                       UploadOperation.idempotency_key == "tcp"))
            key = s.get(DocumentVersion, op.version_id).storage_key
        with real_storage.open(key=key) as stream:
            stored = stream.read()
        assert stored == content and sha256(stored).hexdigest() == op.request_content_sha256
        assert len(stored) == op.request_size_bytes
        def pause():
            entered.set()
            assert release.wait(5)
        storage.after_save = pause
        boundary = "f02-disconnect"
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="actual.pdf"\r\n'
                'Content-Type: application/pdf\r\n\r\n').encode() + content + f"\r\n--{boundary}--\r\n".encode()
        request = (f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {token()}\r\n"
                   f"Idempotency-Key: disconnected\r\nContent-Type: multipart/form-data; boundary={boundary}\r\n"
                   f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode() + body
        connection = socket.create_connection(("127.0.0.1", port), timeout=5)
        try:
            connection.sendall(request)
            assert entered.wait(5)
        finally:
            connection.close()
            release.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with sessions() as s:
                disconnected = s.scalar(select(UploadOperation).where(
                    UploadOperation.tenant_id == args["tenant_id"],
                    UploadOperation.idempotency_key == "disconnected"))
                if disconnected and disconnected.status == "COMPLETED":
                    break
            time.sleep(.01)
        else:
            pytest.fail("Disconnected request did not finish fenced T2")
        assert disconnected.document_id is not None
    finally:
        release.set()
        server.should_exit = True
        thread.join(timeout=8)
        listener.close()
        assert not thread.is_alive()
