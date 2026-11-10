from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser, get_current_user
from app.dependencies import get_db_session
from app.models import Membership, Tenant


@dataclass(frozen=True)
class TenantPrincipal:
    user_id: UUID
    tenant_id: UUID


def get_current_tenant_member(
    tenant_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> TenantPrincipal:

    membership = session.scalar(
        select(Membership)
        .join(
            Tenant,
            Tenant.id == Membership.tenant_id,
        )
        .where(
            Membership.tenant_id == tenant_id,
            Membership.user_id == current_user.user_id,
            Membership.status == "ACTIVE",
            Tenant.status == "ACTIVE",
        )
    )

    if membership is None:
        raise HTTPException(
            status_code=403,
            detail="Tenant access denied",
        )

    return TenantPrincipal(
        user_id=current_user.user_id,
        tenant_id=tenant_id,
    )