"""Opt-in short-lived auth dependency; existing F01 dependencies remain unchanged."""
from uuid import UUID
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from app.auth import bearer_scheme, get_current_user
from app.tenant_auth import get_current_tenant_member


def get_keyed_upload_principal(
    request: Request, tenant_id: UUID,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    # Normal synchronous dependency: creation, reads and closure in one worker.
    with request.app.state.session_factory() as session:
        user = get_current_user(request=request, credentials=credentials, session=session)
        principal = get_current_tenant_member(tenant_id=tenant_id, current_user=user, session=session)
    return principal  # Frozen IDs only; no live ORM objects or session escape.
