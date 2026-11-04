import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Membership(Base):
    __tablename__ = "memberships"

    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'REVOKED')",
            name="ck_memberships_status",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        primary_key=True,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        primary_key=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="ACTIVE",
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