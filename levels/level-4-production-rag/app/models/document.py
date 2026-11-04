import uuid
from uuid import UUID, uuid4
from datetime import datetime
from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    func,
    CheckConstraint,
    ForeignKey,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class Document(Base):
    __tablename__ = "documents"

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "owner_user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            name="fk_documents_owner_membership",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["id", "active_version_id"],
            ["document_versions.document_id", "document_versions.id"],
            name="fk_documents_active_version",
            use_alter=True,
        ),
        Index("ix_documents_tenant_owner", "tenant_id", "owner_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    active_version_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
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


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_document_versions_document_number",
        ),
        CheckConstraint(
            "version_number >= 1",
            name="ck_document_versions_positive_number",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'READY', 'FAILED')",
            name="ck_document_versions_status",
        ),
        UniqueConstraint(
            "document_id",
            "id",
            name="uq_document_versions_document_id_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="PENDING"
    )
