"""Opt-in migration verification in a newly created, uniquely named local database.

RUN_DISPOSABLE_UPLOAD_MIGRATION=1 enables creation and teardown. Existing
configured databases are used only for a read-only identity/privilege connection.
"""
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

PREVIOUS = "183436ed67c3"
TARGET = "7b9c2d4e6f80"
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DISPOSABLE_UPLOAD_MIGRATION") != "1",
    reason="Requires explicit disposable PostgreSQL verification opt-in",
)


def test_disposable_postgres_migration_cycle(monkeypatch):
    from app.config import load_database_url, load_test_database_url
    from app.models import UploadOperation, UploadAttempt

    source = make_url(load_test_database_url())
    development = make_url(load_database_url())
    assert source.host in {"127.0.0.1", "localhost", "::1"}
    name = f"rag_upload_verify_{uuid4().hex}_test"
    assert name not in {source.database, development.database}
    admin = create_engine(source, isolation_level="AUTOCOMMIT", hide_parameters=True)
    target = source.set(database=name)
    engine = create_engine(target, hide_parameters=True)
    created = False
    try:
        with admin.connect() as connection:
            assert connection.scalar(text("select current_database()")) == source.database
            assert connection.scalar(text("select rolcreatedb or rolsuper from pg_roles where rolname=current_user"))
            # name contains only fixed ASCII and uuid4 hex; never user-supplied SQL.
            connection.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE template0')
            created = True
        with engine.connect() as connection:
            identity = connection.execute(text("select current_database(), current_user, version()" )).one()
            assert identity[0] == name
            assert not inspect(connection).has_table("alembic_version")
            print("DISPOSABLE IDENTITY:", identity)
        monkeypatch.setenv("TEST_DATABASE_URL", target.render_as_string(hide_password=False))
        cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        cfg.cmd_opts = SimpleNamespace(x=["database=test"])

        # Every SQLAlchemy connection opened by Alembic must be our exact database.
        def guard(dbapi_connection, connection_record):
            with dbapi_connection.cursor() as cursor:
                cursor.execute("select current_database()")
                assert cursor.fetchone()[0] == name
            dbapi_connection.rollback()

        from sqlalchemy.engine import Engine
        event.listen(Engine, "connect", guard)
        try:
            command.upgrade(cfg, PREVIOUS)
            tenant, other_tenant, user, legacy, doc, version = [uuid4() for _ in range(6)]
            with engine.begin() as connection:
                assert connection.scalar(text("select version_num from alembic_version")) == PREVIOUS
                print("CONFIRMED PREDECESSOR:", PREVIOUS)
                connection.execute(text("insert into users(id,name,email) values (:id,'Migration test',:email)"), {"id": user, "email": f"{user}@example.test"})
                for tid in (tenant, other_tenant):
                    connection.execute(text("insert into tenants(id,name) values (:id,'Migration test')"), {"id": tid})
                connection.execute(text("insert into memberships(tenant_id,user_id) values (:t,:u)"), {"t": tenant, "u": user})
                connection.execute(text("insert into documents(id,tenant_id,owner_user_id,title) values (:d,:t,:u,'legacy.pdf')"), {"d": doc, "t": tenant, "u": user})
                connection.execute(text("insert into document_versions(id,document_id,version_number,status,storage_key) values (:v,:d,1,'READY','legacy/source.pdf')"), {"v": version, "d": doc})
                for status in ("PROCESSING", "FAILED", "COMPLETED"):
                    connection.execute(text("insert into upload_operations(id,tenant_id,idempotency_key,request_fingerprint,status,document_id,version_id) values (:id,:t,:key,:fp,:s,:d,:v)"), {"id": legacy if status == "PROCESSING" else uuid4(), "t": tenant, "key": status, "fp": "a" * 64, "s": status, "d": doc if status == "COMPLETED" else None, "v": version if status == "COMPLETED" else None})
                before = connection.execute(text("select * from upload_operations order by id")).mappings().all()

            command.upgrade(cfg, TARGET)
            for cycle in ("upgrade", "re-upgrade"):
                with engine.begin() as connection:
                    assert connection.scalar(text("select version_num from alembic_version")) == TARGET
                    inspector = inspect(connection)
                    for model in (UploadOperation, UploadAttempt):
                        table = model.__table__
                        columns = {c["name"]: c for c in inspector.get_columns(table.name)}
                        assert set(columns) == set(table.columns.keys())
                        for column in table.columns:
                            actual = columns[column.name]
                            assert actual["nullable"] == column.nullable
                            assert actual["type"]._type_affinity == column.type._type_affinity
                            assert getattr(actual["type"], "length", None) == getattr(column.type, "length", None)
                            assert getattr(actual["type"], "timezone", None) == getattr(column.type, "timezone", None)
                            assert (actual["default"] is not None) == (column.server_default is not None)
                        expected_fks = {(tuple(fk.column_keys), tuple(e.target_fullname for e in fk.elements)) for fk in table.foreign_key_constraints}
                        actual_fks = {(tuple(fk["constrained_columns"]), tuple(f'{fk["referred_table"]}.{c}' for c in fk["referred_columns"])) for fk in inspector.get_foreign_keys(table.name)}
                        assert actual_fks == expected_fks
                        from sqlalchemy import CheckConstraint, UniqueConstraint
                        assert {c.name for c in table.constraints if isinstance(c, CheckConstraint)} == {c["name"] for c in inspector.get_check_constraints(table.name)}
                        assert {tuple(c.columns.keys()) for c in table.constraints if isinstance(c, UniqueConstraint)} == {tuple(c["column_names"]) for c in inspector.get_unique_constraints(table.name)}
                    after = connection.execute(text("select * from upload_operations order by id")).mappings().all()
                    assert len(after) == len(before)
                    for old, new in zip(before, after):
                        assert all(new[k] == value for k, value in old.items())
                        assert new["lease_generation"] == 0
                        assert all(new[k] is None for k in ("requesting_user_id", "fingerprint_version", "request_title", "request_size_bytes", "request_content_sha256", "lease_token", "lease_expires_at"))
                    print(cycle, "catalog parity and 3 legacy rows preserved")

                    metadata = MetaData()
                    metadata.reflect(bind=connection)
                    operations, attempts = metadata.tables["upload_operations"], metadata.tables["upload_attempts"]
                    operation_id = uuid4()
                    valid = dict(id=operation_id, tenant_id=tenant, idempotency_key="new", request_fingerprint="b" * 64, requesting_user_id=user, fingerprint_version=1, request_title="new.pdf", request_size_bytes=9, request_content_sha256="c" * 64)
                    # All behavior probes roll back, preserving the legacy snapshot.
                    probe = connection.begin_nested()
                    connection.execute(operations.insert().values(**valid))
                    saved = connection.execute(operations.select().where(operations.c.id == operation_id)).mappings().one()
                    assert saved["status"] == "PROCESSING" and saved["lease_generation"] == 0
                    assert saved["created_at"] is not None and saved["updated_at"] is not None
                    attempt = dict(id=uuid4(), operation_id=operation_id, tenant_id=tenant, reserved_document_id=uuid4(), reserved_version_id=uuid4(), storage_key=f"test/{uuid4()}/source.pdf", expected_size_bytes=9, expected_sha256="c" * 64, lease_token=uuid4(), lease_generation=1)
                    connection.execute(attempts.insert().values(**attempt))
                    assert connection.scalar(attempts.select().with_only_columns(attempts.c.created_at)) is not None

                    def reject(table, values, constraint):
                        with pytest.raises(IntegrityError) as error:
                            with connection.begin_nested():
                                connection.execute(table.insert().values(**values))
                        assert error.value.orig.diag.constraint_name == constraint

                    operation_cases = [
                        ({"request_title": None}, "ck_upload_operations_request_metadata"),
                        ({"fingerprint_version": 0}, "ck_upload_operations_fingerprint_version"),
                        ({"request_size_bytes": 0}, "ck_upload_operations_request_size"),
                        ({"request_content_sha256": "invalid"}, "ck_upload_operations_content_digest"),
                        ({"lease_generation": -1}, "ck_upload_operations_lease_generation"),
                        ({"lease_token": uuid4()}, "ck_upload_operations_lease_pair"),
                        ({"requesting_user_id": uuid4()}, "fk_upload_operations_requester_membership"),
                        ({"status": "COMPLETED"}, "ck_upload_operations_completed_references"),
                        ({"status": "BAD"}, "ck_upload_operations_status"),
                        ({"document_id": doc}, "ck_upload_operations_reference_pair"),
                        ({"idempotency_key": "new"}, "uq_upload_operations_tenant_key"),
                    ]
                    for changes, constraint in operation_cases:
                        reject(operations, {**valid, "id": uuid4(), "idempotency_key": str(uuid4()), **changes}, constraint)
                    attempt_cases = [
                        ({"lease_generation": 1}, "uq_upload_attempts_operation_generation"),
                        ({"storage_key": attempt["storage_key"]}, "uq_upload_attempts_storage_key"),
                        ({"tenant_id": other_tenant}, "fk_upload_attempts_operation_tenant"),
                        ({"operation_id": uuid4()}, "fk_upload_attempts_operation_tenant"),
                        ({"expected_size_bytes": 0}, "ck_upload_attempts_size"),
                        ({"expected_sha256": "invalid"}, "ck_upload_attempts_digest"),
                        ({"lease_generation": 0}, "ck_upload_attempts_generation"),
                        ({"storage_key": "   "}, "ck_upload_attempts_storage_key"),
                    ]
                    for changes, constraint in attempt_cases:
                        reject(attempts, {**attempt, "id": uuid4(), "lease_generation": 2, "storage_key": str(uuid4()), **changes}, constraint)
                    probe.rollback()
                    print(cycle, "19 invalid writes rejected by named PostgreSQL constraints; defaults verified")
                if cycle == "upgrade":
                    command.downgrade(cfg, PREVIOUS)
                    with engine.connect() as connection:
                        assert connection.scalar(text("select version_num from alembic_version")) == PREVIOUS
                        assert not inspect(connection).has_table("upload_attempts")
                        assert "lease_token" not in {c["name"] for c in inspect(connection).get_columns("upload_operations")}
                        assert connection.execute(text("select * from upload_operations order by id")).mappings().all() == before
                    print("DOWNGRADE VERIFIED:", PREVIOUS)
                    command.upgrade(cfg, TARGET)
        finally:
            event.remove(Engine, "connect", guard)
    finally:
        engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}"')
                assert not connection.scalar(text("select 1 from pg_database where datname=:name"), {"name": name})
            print("DISPOSABLE DATABASE REMOVED:", name)
        admin.dispose()
