from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models import Document, Membership, Tenant, User


def get_accessible_document(
    session: Session,
    *,
    document_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    for_update: bool = False,
) -> Document | None:
    statement = (
        select(Document)
        .join(
            Membership,
            and_(
                Membership.tenant_id == Document.tenant_id,
                Membership.user_id == Document.owner_user_id,
            ),
        )
        .join(User, User.id == Membership.user_id)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
            Document.owner_user_id == user_id,
            Document.deleted_at.is_(None),
            Membership.status == "ACTIVE",
            User.status == "ACTIVE",
            Tenant.status == "ACTIVE",
        )
    )

    if for_update:
        statement = statement.with_for_update(
            of=Document
        ).execution_options(populate_existing=True)

    return session.execute(statement).scalar_one_or_none()