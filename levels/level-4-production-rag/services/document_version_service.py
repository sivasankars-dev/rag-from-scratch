from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.document import Document, DocumentVersion
from app.models import Membership, Tenant, User
from app.repositories.document import get_accessible_document

def publish_document_version(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    document_id: UUID,
    version_id: UUID,
) -> None:
    document = get_accessible_document(
        session,
        document_id=document_id,
        tenant_id=tenant_id,
        user_id=user_id,
        for_update=True,
    )

    if document is None:
        raise ValueError("Access denied")

    version = session.scalar(
        select(DocumentVersion)
        .where(
            DocumentVersion.id == version_id,
            DocumentVersion.document_id == document_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if version is None:
        raise ValueError("Version does not belong to this document")

    if version.status != "READY":
        raise ValueError("Only READY versions can be published")

    document.active_version_id = version.id
    session.flush()

def get_readable_active_version_id(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    document_id: UUID,
) -> UUID | None:
    statement = (
        select(Document.active_version_id)
        .join(
            Membership,
            (Membership.tenant_id == Document.tenant_id)
            & (Membership.user_id == Document.owner_user_id),
        )
        .join(Tenant, Tenant.id == Document.tenant_id)
        .join(User, User.id == Document.owner_user_id)
        .where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
            Document.owner_user_id == user_id,
            Document.deleted_at.is_(None),
            Membership.status == "ACTIVE",
            Tenant.status == "ACTIVE",
            User.status == "ACTIVE",
        )
    )
    return session.scalar(statement)