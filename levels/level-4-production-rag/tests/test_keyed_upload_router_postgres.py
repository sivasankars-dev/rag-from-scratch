"""Actual FastAPI dependency graphs, RS256 JWTs and disposable PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
import os
from threading import Event
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI
from fastapi.testclient import TestClient
import jwt
import pytest
from sqlalchemy import select, text

from app.models import Membership, UploadOperation, UploadAttempt, User
from app.routers import documents
from app.dependencies import get_db_session
from services.upload_claim_service import claim_upload
from services.upload_http_contract import HttpDecision, HttpOutcome, STATUS
from test_upload_claim_postgres import sessions, claim_request
from test_verified_recovery_postgres import RecoveryStorage

pytestmark = pytest.mark.skipif(os.getenv("RUN_DISPOSABLE_UPLOAD_CLAIMS") != "1", reason="Disposable PostgreSQL opt-in")


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def api(sessions, claim_request, signing_key):
    args, other, other_tenant = claim_request
    app = FastAPI()
    app.include_router(documents.router)
    @app.get("/ping")
    async def ping(): return {"ok": True}
    storage = RecoveryStorage(sessions)
    app.state.db_engine = sessions.kw["bind"]
    app.state.session_factory = sessions
    app.state.document_storage = storage
    app.state.jwt_public_key = signing_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    app.state.jwt_issuer = "router-tests"
    app.state.jwt_audience = "upload"
    def token(user=args["user_id"], **overrides):
        now = datetime.now(timezone.utc)
        claims = dict(sub=str(user), iss="router-tests", aud="upload", iat=now,
                      exp=now + timedelta(minutes=5))
        claims.update(overrides)
        return jwt.encode(claims, signing_key, algorithm="RS256")
    with TestClient(app) as client:
        yield client, app, storage, args, token, other, other_tenant


def post(api, key="key", content=b"%PDF-data", filename="source.pdf", token=None, path=None):
    client, _, _, args, make_token, _, _ = api
    headers = {"Authorization": "Bearer " + (make_token() if token is None else token)}
    if key is not None: headers["Idempotency-Key"] = key
    return client.post(path or f"/tenants/{args['tenant_id']}/documents/upload",
                       headers=headers, files={"file": (filename, content, "application/pdf")})


def test_upload_replay_conflict_and_auth_transaction_closure(api, sessions):
    client, app, storage, args, _, _, _ = api
    def forbidden_dependency():
        pytest.fail("Keyed route instantiated request-scoped database dependency")
    app.dependency_overrides[get_db_session] = forbidden_dependency
    first = post(api)
    assert first.status_code == 200
    assert set(first.json()) == {"status", "document_id", "version_id", "tenant_id", "filename", "size_bytes"}
    assert post(api).json() == first.json()
    conflict = post(api, content=b"%PDF-else")
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "conflict"
    assert storage.saves == 1  # Fake storage checks pg_stat_activity during PUT.
    assert "storage_key" not in first.text and "lease_token" not in first.text


@pytest.mark.parametrize("key", ["", " ", "two words", "x" * 256, "\tbad"])
def test_invalid_key_never_falls_back_to_f01(api, key):
    assert post(api, key=key).status_code == 400
    assert api[2].saves == 0


def test_duplicate_header_rejected(api):
    client, _, storage, args, token, _, _ = api
    response = client.post(f"/tenants/{args['tenant_id']}/documents/upload",
        headers=[("Authorization", "Bearer " + token()), ("Idempotency-Key", "a"), ("Idempotency-Key", "b")],
        files={"file": ("source.pdf", b"%PDF-data")})
    assert response.status_code == 400 and not storage.saves


@pytest.mark.parametrize("key", ["key", None])
@pytest.mark.parametrize("mode,status", [("bad_token", 401), ("expired", 401), ("wrong_audience", 401),
                                         ("revoked", 403), ("disabled", 401)])
def test_verified_jwt_and_membership(api, sessions, mode, status, key):
    _, _, storage, args, token, _, _ = api
    signed = token()
    if mode == "bad_token": signed = "not-a-jwt"
    elif mode == "expired": signed = token(exp=datetime.now(timezone.utc)-timedelta(seconds=10))
    elif mode == "wrong_audience": signed = token(aud="other")
    else:
        with sessions.begin() as s:
            if mode == "revoked": s.get(Membership, (args["tenant_id"], args["user_id"])).status = "REVOKED"
            else: s.get(User, args["user_id"]).status = "DISABLED"
    assert post(api, key=key, token=signed).status_code == status
    assert not storage.saves


def test_owner_and_tenant_isolation(api):
    _, _, _, args, token, other, tenant = api
    first = post(api)
    assert first.status_code == 200
    assert post(api, token=token(other)).status_code == 403
    # Other tenant membership exists: same key is a distinct authorized operation.
    second = post(api, path=f"/tenants/{tenant}/documents/upload")
    assert second.status_code == 200
    assert second.json()["document_id"] != first.json()["document_id"]


def test_expired_retry_recovers_canonical_ids(api, sessions):
    _, _, _, args, _, _, _ = api
    claim = claim_upload(**dict(args, idempotency_key="key")).claim
    with sessions.begin() as s:
        s.get(UploadOperation, claim.operation_id).lease_expires_at -= timedelta(days=1)
    result = post(api)
    assert result.status_code == 200 and result.json()["document_id"] == str(claim.document_id)
    with sessions() as s:
        assert s.get(UploadOperation, claim.operation_id).lease_generation == 2


def test_live_retry_returns_in_progress(api):
    args = api[3]
    claim_upload(**dict(args, idempotency_key="key"))
    response = post(api)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "in_progress"
    assert response.headers["Retry-After"] == "1" and not api[2].saves


def test_uncertain_put_is_safe_public_503(api, sessions):
    storage = api[2]
    def fail(): raise TimeoutError("SECRET SDK DETAILS")
    storage.after_save = fail
    response = post(api)
    assert response.status_code == 503 and response.json()["detail"]["code"] == "unresolved"
    assert "SECRET" not in response.text and not storage.deletes
    with sessions() as s:
        op = s.scalar(select(UploadOperation).where(UploadOperation.tenant_id == api[3]["tenant_id"]))
        assert op.status == "PROCESSING"


def test_no_key_retains_f01_response_and_duplicate_behavior(api):
    storage = api[2]
    # F01 intentionally retains its original transaction-during-upload semantics.
    storage.no_open_transactions = lambda: None
    first, second = post(api, key=None), post(api, key=None)
    assert first.status_code == second.status_code == 200
    assert first.json()["document_id"] != second.json()["document_id"]
    assert set(first.json()) == {"status", "document_id", "version_id", "tenant_id", "filename", "size_bytes"}
    assert storage.saves == 2


@pytest.mark.parametrize("content,name,status", [(b"bad", "source.pdf", 400),
    (b"%PDF-data", "source.txt", 400), (b"", "source.pdf", 400),
    (b"%PDF-" + b"x" * (10 * 1024 * 1024), "source.pdf", 413)])
def test_multipart_validation(api, content, name, status):
    assert post(api, content=content, filename=name).status_code == status
    assert not api[2].saves


@pytest.mark.parametrize("outcome", [x for x in HttpOutcome if x != HttpOutcome.COMPLETED])
def test_typed_outcomes_have_stable_http_mapping(api, monkeypatch, outcome):
    async def result(**kwargs): return HttpDecision(outcome)
    monkeypatch.setattr(documents, "execute_keyed_upload", result)
    response = post(api)
    assert response.status_code == STATUS[outcome]
    assert response.json() == {"detail": {"code": outcome.value}}


def test_blocked_storage_does_not_block_event_loop_or_close_upload(api, monkeypatch):
    import starlette.formparsers as parsers
    files = []
    original = parsers.SpooledTemporaryFile
    def tracked(*args, **kwargs):
        file = original(*args, **kwargs)
        files.append(file)
        return file
    monkeypatch.setattr(parsers, "SpooledTemporaryFile", tracked)
    client, _, storage, _, _, _, _ = api
    entered, release = Event(), Event()
    original_save = storage.save
    def blocked(**kwargs):
        entered.set()
        assert release.wait(5)
        assert files and not files[0].closed
        original_save(**kwargs)
    storage.save = blocked
    with ThreadPoolExecutor(max_workers=2) as pool:
        upload = pool.submit(post, api)
        try:
            assert entered.wait(5)
            ping = pool.submit(client.get, "/ping")
            assert ping.result(timeout=2).json() == {"ok": True}
            duplicate = pool.submit(post, api).result(timeout=2)
            assert duplicate.status_code == 409
            assert duplicate.json()["detail"]["code"] == "in_progress"
            assert not upload.done() and not files[0].closed
        finally:
            release.set()
        assert upload.result(timeout=5).status_code == 200
    assert all(file.closed for file in files)


def test_missing_bearer_is_401_for_both_paths(api):
    client, _, storage, args, _, _, _ = api
    path = f"/tenants/{args['tenant_id']}/documents/upload"
    for headers in ({}, {"Idempotency-Key": "key"}):
        response = client.post(path, headers=headers, files={"file": ("source.pdf", b"%PDF-data")})
        assert response.status_code == 401
    assert not storage.saves


def test_maximum_length_key_is_accepted_and_filename_conflicts(api):
    key = "x" * 255
    assert post(api, key=key).status_code == 200
    changed = post(api, key=key, filename="renamed.pdf")
    assert changed.status_code == 409 and changed.json()["detail"]["code"] == "conflict"
