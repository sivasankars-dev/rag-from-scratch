"""Offline schema checks: no engine, application startup or external services."""
import importlib.util
from pathlib import Path
from unittest.mock import Mock

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models import UploadOperation, UploadAttempt


def test_attempt_constraints_and_reserved_identifiers():
    table = UploadAttempt.__table__
    assert not table.c.reserved_document_id.foreign_keys
    assert not table.c.reserved_version_id.foreign_keys
    unique_sets = {tuple(c.columns.keys()) for c in table.constraints if isinstance(c, UniqueConstraint)}
    assert ("storage_key",) in unique_sets
    assert ("operation_id", "lease_generation") in unique_sets
    fk = next(iter(table.foreign_key_constraints))
    assert tuple(fk.columns.keys()) == ("operation_id", "tenant_id")
    assert len(table.foreign_key_constraints) == 1
    assert "CREATE TABLE upload_attempts" in str(CreateTable(table).compile(dialect=postgresql.dialect()))


def test_operation_has_no_redundant_individual_result_foreign_keys():
    fks = {tuple(c.columns.keys()) for c in UploadOperation.__table__.constraints if isinstance(c, ForeignKeyConstraint)}
    assert fks == {("document_id", "version_id"), ("tenant_id", "document_id"), ("tenant_id", "requesting_user_id")}


def test_additive_migration_matches_new_model_metadata():
    path = Path(__file__).resolve().parents[1] / "migrations/versions/7b9c2d4e6f80_add_durable_upload_attempts.py"
    spec = importlib.util.spec_from_file_location("upload_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "183436ed67c3"
    migration.op = Mock()
    migration.upgrade()
    migration.op.drop_table.assert_not_called()
    migration.op.drop_column.assert_not_called()
    args = migration.op.create_table.call_args.args
    from sqlalchemy import MetaData, Table
    migrated = Table(args[0], MetaData(), *args[1:])
    model = UploadAttempt.__table__
    assert set(migrated.columns.keys()) == set(model.columns.keys())
    def constraints(table):
        return {(type(c).__name__, c.name, str(c.sqltext) if isinstance(c, CheckConstraint) else tuple(c.columns.keys())) for c in table.constraints}
    assert constraints(migrated) == constraints(model)
    for call in migration.op.add_column.call_args_list:
        table_name, column = call.args
        expected = UploadOperation.__table__.c[column.name]
        assert table_name == "upload_operations"
        assert column.nullable == expected.nullable
        assert str(column.type) == str(expected.type)
    checks = {c.name: str(c.sqltext) for c in UploadOperation.__table__.constraints if isinstance(c, CheckConstraint)}
    for call in migration.op.create_check_constraint.call_args_list:
        name, table_name, expression = call.args
        assert expression == checks[name]
