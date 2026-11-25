"""Add durable upload ownership, replay metadata and physical attempts.

Legacy operations retain NULL request metadata; never guess an original caller
or digest. New claim logic must reject/quarantine these rows until reconciled.
"""
from alembic import op
import sqlalchemy as sa

revision = "7b9c2d4e6f80"
down_revision = "183436ed67c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("upload_operations", sa.Column("requesting_user_id", sa.Uuid(), nullable=True))
    op.add_column("upload_operations", sa.Column("fingerprint_version", sa.Integer(), nullable=True))
    op.add_column("upload_operations", sa.Column("request_title", sa.String(255), nullable=True))
    op.add_column("upload_operations", sa.Column("request_size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("upload_operations", sa.Column("request_content_sha256", sa.String(64), nullable=True))
    op.add_column("upload_operations", sa.Column("lease_token", sa.Uuid(), nullable=True))
    op.add_column("upload_operations", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("upload_operations", sa.Column("lease_generation", sa.BigInteger(), nullable=False, server_default="0"))
    op.create_unique_constraint("uq_upload_operations_id_tenant", "upload_operations", ["id", "tenant_id"])
    op.create_foreign_key("fk_upload_operations_requester_membership", "upload_operations", "memberships", ["tenant_id", "requesting_user_id"], ["tenant_id", "user_id"])
    op.create_check_constraint('ck_upload_operations_request_metadata', "upload_operations", '(requesting_user_id IS NULL AND fingerprint_version IS NULL AND request_title IS NULL AND request_size_bytes IS NULL AND request_content_sha256 IS NULL) OR (requesting_user_id IS NOT NULL AND fingerprint_version IS NOT NULL AND request_title IS NOT NULL AND request_size_bytes IS NOT NULL AND request_content_sha256 IS NOT NULL)')
    op.create_check_constraint('ck_upload_operations_fingerprint_version', "upload_operations", 'fingerprint_version > 0')
    op.create_check_constraint('ck_upload_operations_request_size', "upload_operations", 'request_size_bytes > 0')
    op.create_check_constraint('ck_upload_operations_content_digest', "upload_operations", "request_content_sha256 ~ '^[0-9a-f]{64}$'")
    op.create_check_constraint('ck_upload_operations_lease_generation', "upload_operations", 'lease_generation >= 0')
    op.create_check_constraint('ck_upload_operations_lease_pair', "upload_operations", '(lease_token IS NULL AND lease_expires_at IS NULL) OR (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND lease_generation > 0)')
    op.create_table(
        "upload_attempts",
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('operation_id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('reserved_document_id', sa.Uuid(), nullable=False),
        sa.Column('reserved_version_id', sa.Uuid(), nullable=False),
        sa.Column('storage_key', sa.String(1024), nullable=False),
        sa.Column('expected_size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('expected_sha256', sa.String(64), nullable=False),
        sa.Column('lease_token', sa.Uuid(), nullable=False),
        sa.Column('lease_generation', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["operation_id", "tenant_id"], ["upload_operations.id", "upload_operations.tenant_id"], name="fk_upload_attempts_operation_tenant"),
        sa.UniqueConstraint("operation_id", "lease_generation", name="uq_upload_attempts_operation_generation"),
        sa.UniqueConstraint("storage_key", name="uq_upload_attempts_storage_key"),
        sa.CheckConstraint("expected_sha256 ~ '^[0-9a-f]{64}$'", name='ck_upload_attempts_digest'),
        sa.CheckConstraint('lease_generation > 0', name='ck_upload_attempts_generation'),
        sa.CheckConstraint('expected_size_bytes > 0', name='ck_upload_attempts_size'),
        sa.CheckConstraint('length(trim(storage_key)) > 0', name='ck_upload_attempts_storage_key'),
    )


def downgrade() -> None:
    op.drop_table("upload_attempts")
    op.drop_constraint("ck_upload_operations_lease_pair", "upload_operations", type_="check")
    op.drop_constraint("ck_upload_operations_lease_generation", "upload_operations", type_="check")
    op.drop_constraint("ck_upload_operations_content_digest", "upload_operations", type_="check")
    op.drop_constraint("ck_upload_operations_request_size", "upload_operations", type_="check")
    op.drop_constraint("ck_upload_operations_fingerprint_version", "upload_operations", type_="check")
    op.drop_constraint("ck_upload_operations_request_metadata", "upload_operations", type_="check")
    op.drop_constraint("fk_upload_operations_requester_membership", "upload_operations", type_="foreignkey")
    op.drop_constraint("uq_upload_operations_id_tenant", "upload_operations", type_="unique")
    op.drop_column("upload_operations", 'lease_generation')
    op.drop_column("upload_operations", 'lease_expires_at')
    op.drop_column("upload_operations", 'lease_token')
    op.drop_column("upload_operations", 'request_content_sha256')
    op.drop_column("upload_operations", 'request_size_bytes')
    op.drop_column("upload_operations", 'request_title')
    op.drop_column("upload_operations", 'fingerprint_version')
    op.drop_column("upload_operations", 'requesting_user_id')
