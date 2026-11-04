from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import load_database_url
from app.database import create_db_engine, create_session_factory
from app.models import Membership, Tenant, User
from app.models.document import Document, DocumentVersion
from services.document_version_service import (
    get_readable_active_version_id,
    publish_document_version,
)

@pytest.fixture
def db_session():
    engine = create_db_engine(load_database_url())
    session_factory = create_session_factory(engine)

    try:
        with session_factory() as session:
            try:
                yield session
            finally:
                session.rollback()
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
        error.value.orig.diag.constraint_name
        == "uq_document_versions_document_number"
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
        db_session, document_id=document.id, version_id=v1.id
    )

    if status == "READY":
        publish_document_version(
            db_session, document_id=document.id, version_id=v2.id
        )
        expected_active_version_id = v2.id
    else:
        with pytest.raises(ValueError, match="Only READY versions can be published"):
            publish_document_version(
                db_session, document_id=document.id, version_id=v2.id
            )
        expected_active_version_id = v1.id

    db_session.refresh(document)
    assert document.active_version_id == expected_active_version_id

def test_reads_only_the_published_version(db_session, document):
    v1 = DocumentVersion(
        document_id=document.id, version_number=1, status="READY"
    )
    v2 = DocumentVersion(
        document_id=document.id, version_number=2, status="READY"
    )
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
        db_session, document_id=document.id, version_id=v1.id
    )
    assert get_readable_active_version_id(db_session, **scope) == v1.id

    publish_document_version(
        db_session, document_id=document.id, version_id=v2.id
    )
    assert get_readable_active_version_id(db_session, **scope) == v2.id