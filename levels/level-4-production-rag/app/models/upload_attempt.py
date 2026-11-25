"""Durable physical upload intents; fencing is enforced by conditional DB updates."""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKeyConstraint, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UploadAttempt(Base):
    __tablename__ = "upload_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["operation_id", "tenant_id"],
            ["upload_operations.id", "upload_operations.tenant_id"],
            name="fk_upload_attempts_operation_tenant",
        ),
        UniqueConstraint("operation_id", "lease_generation", name="uq_upload_attempts_operation_generation"),
        UniqueConstraint("storage_key", name="uq_upload_attempts_storage_key"),
        CheckConstraint("lease_generation > 0", name="ck_upload_attempts_generation"),
        CheckConstraint("expected_size_bytes > 0", name="ck_upload_attempts_size"),
        CheckConstraint("expected_sha256 ~ '^[0-9a-f]{64}$'", name="ck_upload_attempts_digest"),
        CheckConstraint("length(trim(storage_key)) > 0", name="ck_upload_attempts_storage_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    operation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    # Intent identifiers deliberately have no FK: result rows do not exist at T1.
    reserved_document_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    reserved_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    expected_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expected_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_token: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    lease_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
