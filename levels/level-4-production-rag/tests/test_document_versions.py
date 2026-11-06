from uuid import uuid4
from datetime import datetime, timezone
import pytest
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text

from app.config import load_test_database_url
from app.database import create_db_engine, create_session_factory
from app.models import Membership, Tenant, User
from app.models.document import Document, DocumentVersion
from services.document_version_service import (
    get_readable_active_version_id,
    publish_document_version,
)
from app.repositories.document import get_accessible_document

@pytest.fixture
def db_session():
    engine = create_db_engine(load_test_database_url())
    session_factory = create_session_factory(engine)

    try:
        with session_factory() as session:
            # Verify the actual connected database
            database_name = session.scalar(text("SELECT current_database()"))
            assert database_name == "rag_level4_test"
            try:
                yield session
            finally:
                session.rollback()
    finally:
        engine.dispose()


@pytest.fixture
def two_session_factory():
    engine = create_db_engine(load_test_database_url())
    session_factory = create_session_factory(engine)
    try:
        yield session_factory
    finally:
        engine.dispose()


@pytest.fixture
def document(db_session):
    user = User(
        id=uuid4(),
        name="Siva",
        email=f"{uuid4().hex}@example.com",
    )
    tenant = Tenant(id=uuid4(), name="Acme")
    db_session.add_all([user, tenant])
    db_session.flush()

    membership = Membership(tenant_id=tenant.id, user_id=user.id)
    db_session.add(membership)
    db_session.flush()

    doc = Document(
        id=uuid4(),
        tenant_id=tenant.id,
        owner_user_id=user.id,
        title="handbook.pdf",
    )
    db_session.add(doc)
    db_session.flush()

    return doc


def test_allows_multiple_versions_for_same_document(db_session, document):
    db_session.add_all(
        [
            DocumentVersion(document_id=document.id, version_number=1),
            DocumentVersion(document_id=document.id, version_number=2),
        ]
    )
    db_session.flush()

    version_numbers = db_session.scalars(
        select(DocumentVersion.version_number)
        .where(DocumentVersion.document_id == document.id)
        .order_by(DocumentVersion.version_number)
    ).all()

    assert version_numbers == [1, 2]


def test_rejects_duplicate_version_number_for_same_document(db_session, document):
    document_id = document.id
    db_session.add(
        DocumentVersion(
            id=uuid4(),
            document_id=document_id,
            version_number=2,
        )
    )
    db_session.flush()

    with pytest.raises(IntegrityError) as error:
        with db_session.begin_nested():
            db_session.add(
                DocumentVersion(
                    id=uuid4(),
                    document_id=document_id,
                    version_number=2,
                )
            )
            db_session.flush()

    assert (
        error.value.orig.diag.constraint_name == "uq_document_versions_document_number"
    )


def test_allows_active_version_from_same_document(db_session, document):
    version = DocumentVersion(document_id=document.id, version_number=1)
    db_session.add(version)
    db_session.flush()

    document.active_version_id = version.id
    db_session.flush()
    db_session.refresh(document)

    assert document.active_version_id == version.id


def test_rejects_active_version_from_another_document(db_session, document):
    other_document = Document(
        id=uuid4(),
        tenant_id=document.tenant_id,
        owner_user_id=document.owner_user_id,
        title="other-handbook.pdf",
    )
    db_session.add(other_document)
    db_session.flush()

    other_version = DocumentVersion(
        document_id=other_document.id,
        version_number=1,
    )
    db_session.add(other_version)
    db_session.flush()

    with pytest.raises(IntegrityError) as error:
        with db_session.begin_nested():
            document.active_version_id = other_version.id
            db_session.flush()

    assert error.value.orig.diag.constraint_name == "fk_documents_active_version"


@pytest.mark.parametrize("status", ["READY", "PENDING", "FAILED"])
def test_publish_document_version(db_session, document, status):
    v1 = DocumentVersion(
        document_id=document.id,
        version_number=1,
        status="READY",
    )
    v2 = DocumentVersion(
        document_id=document.id,
        version_number=2,
        status=status,
    )
    db_session.add_all([v1, v2])
    db_session.flush()

    publish_document_version(
        db_session,
        tenant_id=document.tenant_id,
        user_id=document.owner_user_id,
        document_id=document.id,
        version_id=v1.id,
    )

    if status == "READY":
        publish_document_version(
            db_session,
            tenant_id=document.tenant_id,
            user_id=document.owner_user_id,
            document_id=document.id,
            version_id=v2.id,
        )
        expected_active_version_id = v2.id
    else:
        with pytest.raises(ValueError, match="Only READY versions can be published"):
            publish_document_version(
                db_session,
                tenant_id=document.tenant_id,
                user_id=document.owner_user_id,
                document_id=document.id,
                version_id=v2.id,
            )
        expected_active_version_id = v1.id

    db_session.refresh(document)
    assert document.active_version_id == expected_active_version_id


def test_reads_only_the_published_version(db_session, document):
    v1 = DocumentVersion(document_id=document.id, version_number=1, status="READY")
    v2 = DocumentVersion(document_id=document.id, version_number=2, status="READY")
    db_session.add_all([v1, v2])
    db_session.flush()

    scope = {
        "tenant_id": document.tenant_id,
        "user_id": document.owner_user_id,
        "document_id": document.id,
    }

    # Both versions are READY, but neither is published yet.
    assert get_readable_active_version_id(db_session, **scope) is None

    publish_document_version(
        db_session,
        tenant_id=document.tenant_id,
        user_id=document.owner_user_id,
        document_id=document.id,
        version_id=v1.id,
    )
    assert get_readable_active_version_id(db_session, **scope) == v1.id

    publish_document_version(
        db_session,
        tenant_id=document.tenant_id,
        user_id=document.owner_user_id,
        document_id=document.id,
        version_id=v2.id,
    )
    assert get_readable_active_version_id(db_session, **scope) == v2.id


def test_revoked_member_cannot_read_published_version(db_session, document):
    # First, create and publish a readable version.
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        status="READY",
    )
    db_session.add(version)
    db_session.flush()

    publish_document_version(
        db_session,
        tenant_id=document.tenant_id,
        user_id=document.owner_user_id,
        document_id=document.id,
        version_id=version.id,
    )

    scope = {
        "tenant_id": document.tenant_id,
        "user_id": document.owner_user_id,
        "document_id": document.id,
    }

    # Before revocation, the owner can read it.
    assert get_readable_active_version_id(db_session, **scope) == version.id

    # Cancel the owner's membership in this tenant.
    membership = db_session.get(
        Membership,
        (document.tenant_id, document.owner_user_id),
    )
    assert membership is not None

    membership.status = "REVOKED"
    db_session.flush()

    # The published version still exists, but access is denied.
    assert get_readable_active_version_id(db_session, **scope) is None


def test_deleted_document_has_no_readable_published_version(db_session, document):
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        status="READY",
    )
    db_session.add(version)
    db_session.flush()

    publish_document_version(
        db_session,
        tenant_id=document.tenant_id,
        user_id=document.owner_user_id,
        document_id=document.id,
        version_id=version.id,
    )

    scope = {
        "tenant_id": document.tenant_id,
        "user_id": document.owner_user_id,
        "document_id": document.id,
    }

    # Before deletion, the owner can read the published version.
    assert get_readable_active_version_id(db_session, **scope) == version.id

    document.deleted_at = datetime.now(timezone.utc)
    db_session.flush()

    # After soft deletion, the version is no longer readable.
    assert get_readable_active_version_id(db_session, **scope) is None


def test_disabled_owner_cannot_publish_version(db_session, document):
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        status="READY",
    )
    db_session.add(version)
    db_session.flush()

    owner = db_session.get(User, document.owner_user_id)
    assert owner is not None

    owner.status = "DISABLED"
    db_session.flush()

    with pytest.raises(ValueError, match="Access denied"):
        publish_document_version(
            db_session,
            tenant_id=document.tenant_id,
            user_id=document.owner_user_id,
            document_id=document.id,
            version_id=version.id,
        )
    db_session.refresh(document)
    assert document.active_version_id is None


def test_disabled_tenant_cannot_publish_version(db_session, document):
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        status="READY",
    )
    db_session.add(version)
    db_session.flush()

    tenant = db_session.get(Tenant, document.tenant_id)
    assert tenant is not None

    tenant.status = "DISABLED"
    db_session.flush()

    with pytest.raises(ValueError, match="Access denied"):
        publish_document_version(
            db_session,
            tenant_id=document.tenant_id,
            user_id=document.owner_user_id,
            document_id=document.id,
            version_id=version.id,
        )

    db_session.refresh(document)
    assert document.active_version_id is None


def test_revoked_member_cannot_publish_version(db_session, document):
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        status="READY",
    )
    db_session.add(version)
    db_session.flush()

    membership = db_session.get(
        Membership,
        (document.tenant_id, document.owner_user_id),
    )
    assert membership is not None

    membership.status = "REVOKED"
    db_session.flush()

    with pytest.raises(ValueError, match="Access denied"):
        publish_document_version(
            db_session,
            tenant_id=document.tenant_id,
            user_id=document.owner_user_id,
            document_id=document.id,
            version_id=version.id,
        )

    db_session.refresh(document)
    assert document.active_version_id is None


def test_non_owner_cannot_publish_version(db_session, document):
    other_user = User(
        id=uuid4(),
        name="Bala",
        email=f"{uuid4().hex}@example.com",
    )
    db_session.add(other_user)
    db_session.flush()

    db_session.add(
        Membership(
            tenant_id=document.tenant_id,
            user_id=other_user.id,
        )
    )

    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        status="READY",
    )
    db_session.add(version)
    db_session.flush()

    with pytest.raises(ValueError, match="Access denied"):
        publish_document_version(
            db_session,
            tenant_id=document.tenant_id,
            user_id=other_user.id,
            document_id=document.id,
            version_id=version.id,
        )

    db_session.refresh(document)
    assert document.active_version_id is None


def test_cross_tenant_user_cannot_publish_version(db_session, document):
    other_user = User(
        id=uuid4(),
        name="Kumar",
        email=f"{uuid4().hex}@example.com",
    )
    other_tenant = Tenant(
        id=uuid4(),
        name="Beta",
    )

    db_session.add_all([other_user, other_tenant])
    db_session.flush()

    db_session.add(
        Membership(
            tenant_id=other_tenant.id,
            user_id=other_user.id,
        )
    )

    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        status="READY",
    )
    db_session.add(version)
    db_session.flush()

    with pytest.raises(ValueError, match="Access denied"):
        publish_document_version(
            db_session,
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            document_id=document.id,
            version_id=version.id,
        )

    db_session.refresh(document)
    assert document.active_version_id is None


def test_document_publication_stale_orm_read(two_session_factory):
    user_id = uuid4()
    tenant_id = uuid4()
    document_id = uuid4()
    try:
        with two_session_factory() as setup_session:
            user = User(id=user_id, name="Siva", email=f"{uuid4().hex}@email.com")
            tenant = Tenant(id=tenant_id, name="Acme")
            setup_session.add_all([user, tenant])
            setup_session.flush()

            membership = Membership(tenant_id=tenant.id, user_id=user.id)
            setup_session.add(membership)
            setup_session.flush()

            doc1 = Document(
                id=document_id,
                tenant_id=tenant.id,
                owner_user_id=user.id,
                title="handbook.pdf",
            )
            setup_session.add(doc1)
            setup_session.flush()

            version1 = DocumentVersion(
                document_id=doc1.id,
                version_number=1,
                status="READY",
            )

            version2 = DocumentVersion(
                document_id=doc1.id,
                version_number=2,
                status="READY",
            )

            setup_session.add_all([version1, version2])
            setup_session.flush()

            doc1.active_version_id = version1.id

            document_id = doc1.id
            version1_id = version1.id
            version2_id = version2.id
            setup_session.commit()

        with two_session_factory() as session_a:
            document_a = session_a.get(Document, document_id)

            assert document_a is not None
            assert document_a.active_version_id == version1_id

            with two_session_factory() as session_b:
                document_b = session_b.get(Document, document_id)

                assert document_b is not None
                assert document_b.active_version_id == version1_id

                document_b.active_version_id = version2_id
                session_b.commit()

            assert document_a.active_version_id == version1_id

            # identity-mapped object without refreshing it.
            queried_document = session_a.scalar(
                select(Document).where(Document.id == document_id)
            )

            assert queried_document is document_a
            assert queried_document.active_version_id == version1_id

            fresh_document = get_accessible_document(
                session_a,
                document_id=document_id,
                tenant_id=tenant_id,
                user_id=user_id,
                for_update=True,
            )

            assert fresh_document is document_a
            assert fresh_document.active_version_id == version2_id

            session_a.refresh(document_a)
            assert document_a.active_version_id == version2_id
    finally:
        # cleanup commited test data
        with two_session_factory() as cleanup_session:
            document = cleanup_session.get(Document, document_id)
            if document is not None:
                document.active_version_id = None
                cleanup_session.flush()
            cleanup_session.execute(
                delete(DocumentVersion).where(
                    DocumentVersion.document_id == document_id
                )
            )
            cleanup_session.execute(delete(Document).where(Document.id == document_id))
            cleanup_session.execute(
                delete(Membership).where(
                    Membership.tenant_id == tenant_id,
                    Membership.user_id == user_id,
                )
            )
            cleanup_session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            cleanup_session.execute(delete(User).where(User.id == user_id))
            cleanup_session.commit()
