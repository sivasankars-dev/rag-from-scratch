import uuid

from app.config import load_database_url
from app.database import create_db_engine, create_session_factory
from app.models import Document, Membership, Tenant, User
from app.repositories.document import get_accessible_document


def test_only_owner_can_read_document_within_tenant():
    engine = create_db_engine(load_database_url())

    try:
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            try:
                owner = User(
                    name="Owner",
                    email=f"{uuid.uuid4()}@example.com",
                )
                other_member = User(
                    name="Other member",
                    email=f"{uuid.uuid4()}@example.com",
                )
                tenant = Tenant(name="Test Workspace")

                session.add_all([owner, other_member, tenant])
                session.flush()

                session.add_all([
                    Membership(tenant_id=tenant.id, user_id=owner.id),
                    Membership(tenant_id=tenant.id, user_id=other_member.id),
                ])
                session.flush()

                document = Document(
                    tenant_id=tenant.id,
                    owner_user_id=owner.id,
                    title="Employee Handbook",
                )
                session.add(document)
                session.flush()

                other_tenant = Tenant(name="Other Workspace")
                session.add(other_tenant)
                session.flush()

                session.add(
                    Membership(tenant_id=other_tenant.id, user_id=owner.id)
                )
                session.flush()

                denied_in_other_tenant = get_accessible_document(
                    session,
                    document_id=document.id,
                    tenant_id=other_tenant.id,
                    user_id=owner.id,
                )

                assert denied_in_other_tenant is None

                allowed = get_accessible_document(
                    session,
                    document_id=document.id,
                    tenant_id=tenant.id,
                    user_id=owner.id,
                )
                denied = get_accessible_document(
                    session,
                    document_id=document.id,
                    tenant_id=tenant.id,
                    user_id=other_member.id,
                )

                assert allowed is not None
                assert allowed.id == document.id
                assert denied is None
            finally:
                session.rollback()
    finally:
        engine.dispose()