from fastapi import APIRouter, Depends
from app.auth import AuthenticatedUser, get_current_user
from uuid import UUID
from app.tenant_auth import TenantPrincipal, get_current_tenant_member


router = APIRouter(prefix="/debug/auth", tags=["auth"])

@router.get("/me")
def read_current_user(current_user: AuthenticatedUser = Depends(get_current_user)):
    return {
        "user_id": str(current_user.user_id),
    }

@router.get("/tenants/{tenant_id}/me")
def read_tenant_identity(
    principal: TenantPrincipal = Depends(get_current_tenant_member),
):
    return {
        "user_id": str(principal.user_id),
        "tenant_id": str(principal.tenant_id),
    }