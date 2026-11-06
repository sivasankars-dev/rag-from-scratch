import uuid
import pytest
from sqlalchemy.exc import IntegrityError

from app.config import load_test_database_url
from app.database import create_db_engine, create_session_factory
from app.models import Membership, Tenant, User


def test_creates_user_tenant_and_membership():
    engine = create_db_engine(load_test_database_url())

    try:
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            try:
                user = User(
                    name="Test User",
                    email=f"{uuid.uuid4()}@example.com",
                )
                tenant = Tenant(name="Test Workspace")

                session.add_all([user, tenant])
                session.flush()

                membership = Membership(
                    tenant_id=tenant.id,
                    user_id=user.id,
                )

                session.add(membership)
                session.flush()

                session.expire_all()

                saved = session.get(
                    Membership,
                    (tenant.id, user.id),
                )

                assert saved is not None
                assert saved.status == "ACTIVE"
            finally:
                session.rollback()
    finally:
        engine.dispose()

def test_rejects_duplicate_membership():
    engine = create_db_engine(load_test_database_url())

    try:
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            try:
                user = User(
                    name="Test User",
                    email=f"{uuid.uuid4()}@example.com",
                )
                tenant = Tenant(name="Test Workspace")

                session.add_all([user, tenant])
                session.flush()

                session.add(
                    Membership(
                        tenant_id=tenant.id,
                        user_id=user.id,
                    )
                )
                session.flush()

                duplicate = Membership(
                    tenant_id=tenant.id,
                    user_id=user.id,
                )

                with pytest.raises(IntegrityError) as error:
                    session.add(duplicate)
                    session.flush()

                assert error.value.orig.sqlstate == "23505"
            finally:
                session.rollback()
    finally:
        engine.dispose()

def test_rejects_membership_for_missing_user():
    engine = create_db_engine(load_test_database_url())

    try:
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            try:
                tenant = Tenant(name="Test Workspace")
                session.add(tenant)
                session.flush()

                membership = Membership(
                    tenant_id=tenant.id,
                    user_id=uuid.uuid4(),  # User was never inserted.
                )

                with pytest.raises(IntegrityError) as error:
                    session.add(membership)
                    session.flush()

                assert error.value.orig.sqlstate == "23503"
            finally:
                session.rollback()
    finally:
        engine.dispose()

def test_rejects_membership_for_missing_tenant():
    engine = create_db_engine(load_test_database_url())

    try:
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            try:
                user = User(
                    name="Test User",
                    email=f"{uuid.uuid4()}@example.com",
                )
                session.add(user)
                session.flush()

                membership = Membership(
                    user_id=user.id,
                    tenant_id=uuid.uuid4(),  # Tenant was never inserted.
                )

                with pytest.raises(IntegrityError) as error:
                    session.add(membership)
                    session.flush()

                assert error.value.orig.sqlstate == "23503"
            finally:
                session.rollback()
    finally:
        engine.dispose()