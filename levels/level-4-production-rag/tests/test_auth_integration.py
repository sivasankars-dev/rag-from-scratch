import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient

from app.config import load_test_database_url
from app.database import create_db_engine
from app.main import create_app
from app.models import User, Tenant, Membership


ISSUER = "https://auth.example.test"
AUDIENCE = "production-rag-api"


class FakeEmbeddingService:
    def embed_text(self, text):
        return [0.1, 0.2, 0.3]


@pytest.fixture
def auth_environment():
    engine = create_db_engine(load_test_database_url())

    connection = engine.connect()
    transaction = connection.begin()

    # Both setup and API sessions use the same test connection.
    from sqlalchemy.orm import Session

    def test_session_factory():
        return Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    @contextmanager
    def test_database_resources():
        yield engine, test_session_factory

    app = create_app(
        embedding_service_factory=FakeEmbeddingService,
        database_resources_factory=test_database_resources,
    )

    try:
        with TestClient(app) as client:
            app.state.jwt_public_key = public_key
            app.state.jwt_issuer = ISSUER
            app.state.jwt_audience = AUDIENCE

            yield client, test_session_factory, private_key

    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()


def make_token(private_key, user_id):
    now = datetime.now(timezone.utc)

    return jwt.encode(
        {
            "sub": str(user_id),
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        private_key,
        algorithm="RS256",
    )

def create_user_and_tenant(
    session,
    *,
    user_status="ACTIVE",
    tenant_status="ACTIVE",
    membership_status="ACTIVE",
):
    user = User(
        name="Integration Test User",
        email=f"{uuid.uuid4()}@example.com",
        status=user_status,
    )

    tenant = Tenant(
        name="Integration Test Workspace",
        status=tenant_status,
    )

    session.add_all([user, tenant])
    session.flush()

    session.add(
        Membership(
            tenant_id=tenant.id,
            user_id=user.id,
            status=membership_status,
        )
    )
    session.flush()

    return user, tenant


def pdf_upload_files(content=None):
    if content is None:
        content = b"%PDF-1.7\nSample PDF content"

    return {
        "file": (
            "test.pdf",
            content,
            "application/pdf",
        )
    }


def test_active_user_can_access_protected_endpoint(auth_environment):
    client, session_factory, private_key = auth_environment

    with session_factory() as session:
        user = User(
            name="Active User",
            email=f"{uuid.uuid4()}@example.com",
            status="ACTIVE",
        )

        session.add(user)
        session.flush()

        token = make_token(private_key, user.id)

        response = client.get(
            "/debug/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.json()["user_id"] == str(user.id)

        session.rollback()


def test_disabled_user_cannot_access_protected_endpoint(auth_environment):
    client, session_factory, private_key = auth_environment

    with session_factory() as session:
        user = User(
            name="Disabled User",
            email=f"{uuid.uuid4()}@example.com",
            status="DISABLED",
        )

        session.add(user)
        session.flush()

        token = make_token(private_key, user.id)

        response = client.get(
            "/debug/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 401

        session.rollback()


def test_unknown_user_cannot_access_protected_endpoint(auth_environment):
    client, _, private_key = auth_environment

    unknown_user_id = uuid.uuid4()
    token = make_token(private_key, unknown_user_id)

    response = client.get(
        "/debug/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401

def test_active_tenant_member_can_access(auth_environment):
    client, session_factory, private_key = auth_environment

    with session_factory() as session:
        user, tenant = create_user_and_tenant(session)

        token = make_token(private_key, user.id)

        response = client.get(
            f"/debug/auth/tenants/{tenant.id}/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "user_id": str(user.id),
            "tenant_id": str(tenant.id),
        }


def test_revoked_membership_denied(auth_environment):
    client, session_factory, private_key = auth_environment

    with session_factory() as session:
        user, tenant = create_user_and_tenant(
            session,
            membership_status="REVOKED",
        )

        token = make_token(private_key, user.id)

        response = client.get(
            f"/debug/auth/tenants/{tenant.id}/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 403


def test_disabled_tenant_denied(auth_environment):
    client, session_factory, private_key = auth_environment

    with session_factory() as session:
        user, tenant = create_user_and_tenant(
            session,
            tenant_status="DISABLED",
        )

        token = make_token(private_key, user.id)

        response = client.get(
            f"/debug/auth/tenants/{tenant.id}/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 403


def test_revoked_tenant_does_not_block_other_tenant(auth_environment):
    client, session_factory, private_key = auth_environment

    with session_factory() as session:
        user = User(
            name="Multi Tenant User",
            email=f"{uuid.uuid4()}@example.com",
            status="ACTIVE",
        )

        tenant_a = Tenant(name="Tenant A", status="ACTIVE")
        tenant_b = Tenant(name="Tenant B", status="ACTIVE")

        session.add_all([user, tenant_a, tenant_b])
        session.flush()

        session.add_all([
            Membership(
                tenant_id=tenant_a.id,
                user_id=user.id,
                status="ACTIVE",
            ),
            Membership(
                tenant_id=tenant_b.id,
                user_id=user.id,
                status="REVOKED",
            ),
        ])
        session.flush()

        token = make_token(private_key, user.id)
        headers = {"Authorization": f"Bearer {token}"}

        response_a = client.get(
            f"/debug/auth/tenants/{tenant_a.id}/me",
            headers=headers,
        )
        response_b = client.get(
            f"/debug/auth/tenants/{tenant_b.id}/me",
            headers=headers,
        )

        assert response_a.status_code == 200
        assert response_b.status_code == 403

def test_upload_without_jwt_returns_401(auth_environment):
    client, _, _ = auth_environment

    tenant_id = uuid.uuid4()

    response = client.post(
        f"/tenants/{tenant_id}/documents/upload",
        files=pdf_upload_files(),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer token"


def test_active_tenant_member_can_upload_pdf(auth_environment):
    client, session_factory, private_key = auth_environment

    with session_factory() as session:
        user, tenant = create_user_and_tenant(session)

        token = make_token(private_key, user.id)
        content = b"%PDF-1.7\nSample PDF content"

        response = client.post(
            f"/tenants/{tenant.id}/documents/upload",
            headers={"Authorization": f"Bearer {token}"},
            files=pdf_upload_files(content),
        )

        assert response.status_code == 200
        assert response.json() == {
            "status": "validated",
            "tenant_id": str(tenant.id),
            "user_id": str(user.id),
            "filename": "test.pdf",
            "size_bytes": len(content),
        }


def test_revoked_member_cannot_upload_pdf(auth_environment):
    client, session_factory, private_key = auth_environment

    with session_factory() as session:
        user, tenant = create_user_and_tenant(
            session,
            membership_status="REVOKED",
        )

        token = make_token(private_key, user.id)

        response = client.post(
            f"/tenants/{tenant.id}/documents/upload",
            headers={"Authorization": f"Bearer {token}"},
            files=pdf_upload_files(),
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "Tenant access denied"

def test_invalid_jwt_cannot_upload(auth_environment):
    client, _, _ = auth_environment

    response = client.post(
        f"/tenants/{uuid.uuid4()}/documents/upload",
        headers={"Authorization": "Bearer invalid.token.value"},
        files=pdf_upload_files(),
    )

    assert response.status_code == 401


def test_cross_tenant_upload_denied(auth_environment):
    client, session_factory, private_key = auth_environment

    with session_factory() as session:
        user, tenant_a = create_user_and_tenant(session)

        tenant_b = Tenant(name="Other Workspace", status="ACTIVE")
        session.add(tenant_b)
        session.flush()

        token = make_token(private_key, user.id)

        response = client.post(
            f"/tenants/{tenant_b.id}/documents/upload",
            headers={"Authorization": f"Bearer {token}"},
            data={"tenant_id": str(tenant_a.id), "user_id": str(user.id)},
            files=pdf_upload_files(),
        )

        assert response.status_code == 403


def test_fake_pdf_upload_rejected(auth_environment):
    client, session_factory, private_key = auth_environment

    with session_factory() as session:
        user, tenant = create_user_and_tenant(session)
        token = make_token(private_key, user.id)

        response = client.post(
            f"/tenants/{tenant.id}/documents/upload",
            headers={"Authorization": f"Bearer {token}"},
            files=pdf_upload_files(b"MZ executable content"),
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid PDF signature"


def test_oversized_pdf_upload_rejected(auth_environment):
    client, session_factory, private_key = auth_environment

    with session_factory() as session:
        user, tenant = create_user_and_tenant(session)
        token = make_token(private_key, user.id)

        content = b"%PDF-1.7\n" + b"A" * (10 * 1024 * 1024)

        response = client.post(
            f"/tenants/{tenant.id}/documents/upload",
            headers={"Authorization": f"Bearer {token}"},
            files=pdf_upload_files(content),
        )

        assert response.status_code == 413
        assert response.json()["detail"] == "File too large"


def test_empty_pdf_upload_rejected(auth_environment):
    client, session_factory, private_key = auth_environment

    with session_factory() as session:
        user, tenant = create_user_and_tenant(session)
        token = make_token(private_key, user.id)

        response = client.post(
            f"/tenants/{tenant.id}/documents/upload",
            headers={"Authorization": f"Bearer {token}"},
            files=pdf_upload_files(b""),
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Empty file"


@pytest.mark.parametrize("settings,expected", [
    ({"user_status": "DISABLED"}, 401),
    ({"tenant_status": "DISABLED"}, 403),
])
def test_disabled_identity_cannot_upload(auth_environment, settings, expected):
    client, session_factory, private_key = auth_environment
    with session_factory() as session:
        user, tenant = create_user_and_tenant(session, **settings)
        response = client.post(
            f"/tenants/{tenant.id}/documents/upload",
            headers={"Authorization": f"Bearer {make_token(private_key, user.id)}"},
            files=pdf_upload_files(),
        )
        assert response.status_code == expected


def test_upload_boundary_and_spoofed_identity_fields(auth_environment):
    client, session_factory, private_key = auth_environment
    with session_factory() as session:
        user, tenant = create_user_and_tenant(session)
        content = b"%PDF-" + b"A" * (10 * 1024 * 1024 - 5)
        response = client.post(
            f"/tenants/{tenant.id}/documents/upload",
            headers={"Authorization": f"Bearer {make_token(private_key, user.id)}"},
            data={"tenant_id": str(uuid.uuid4()), "user_id": str(uuid.uuid4())},
            files=pdf_upload_files(content),
        )
        assert response.status_code == 200
        assert response.json()["size_bytes"] == len(content)
        assert response.json()["tenant_id"] == str(tenant.id)
        assert response.json()["user_id"] == str(user.id)
