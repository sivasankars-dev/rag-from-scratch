import uuid
from datetime import datetime
from app.models.base import Base
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    DateTime,
    String,
    func,
    UniqueConstraint,
    CheckConstraint,
    Uuid,
    Integer,
    BigInteger,
    ForeignKeyConstraint
)


class UploadOperation(Base):
    __tablename__ = "upload_operations"

    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_upload_operations_id_tenant"),
        ForeignKeyConstraint(
            ["tenant_id", "requesting_user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            name="fk_upload_operations_requester_membership",
        ),
        CheckConstraint(
            "(requesting_user_id IS NULL AND fingerprint_version IS NULL "
            "AND request_title IS NULL AND request_size_bytes IS NULL "
            "AND request_content_sha256 IS NULL) OR "
            "(requesting_user_id IS NOT NULL AND fingerprint_version IS NOT NULL "
            "AND request_title IS NOT NULL AND request_size_bytes IS NOT NULL "
            "AND request_content_sha256 IS NOT NULL)",
            name="ck_upload_operations_request_metadata",
        ),
        CheckConstraint("fingerprint_version > 0", name="ck_upload_operations_fingerprint_version"),
        CheckConstraint("request_size_bytes > 0", name="ck_upload_operations_request_size"),
        CheckConstraint("request_content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_upload_operations_content_digest"),
        CheckConstraint("lease_generation >= 0", name="ck_upload_operations_lease_generation"),
        CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND lease_generation > 0)",
            name="ck_upload_operations_lease_pair",
        ),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_upload_operations_tenant_key",
        ),
        CheckConstraint(
            "status IN ('PROCESSING', 'COMPLETED', 'FAILED')",
            name="ck_upload_operations_status",
        ),
        CheckConstraint(
            """
            status <> 'COMPLETED'
            OR (
                document_id IS NOT NULL
                AND version_id IS NOT NULL
            )
            """,
            name="ck_upload_operations_completed_references",
        ),
        CheckConstraint(
            """
        (document_id IS NULL AND version_id IS NULL)
        OR
        (document_id IS NOT NULL AND version_id IS NOT NULL)
        """,
            name="ck_upload_operations_reference_pair",
        ),
        ForeignKeyConstraint(
            ["document_id", "version_id"],
            ["document_versions.document_id", "document_versions.id"],
            name="fk_upload_operations_document_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            name="fk_upload_operations_tenant_document",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="PROCESSING",
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )

    version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )
    # Nullable as a group for legacy operations; new claims must populate all fields.
    requesting_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    fingerprint_version: Mapped[int | None] = mapped_column(Integer)
    request_title: Mapped[str | None] = mapped_column(String(255))
    request_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    request_content_sha256: Mapped[str | None] = mapped_column(String(64))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
