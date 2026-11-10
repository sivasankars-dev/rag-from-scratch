from dataclasses import dataclass
from uuid import UUID
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from services.jwt_verifier import verify_access_token
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_db_session
from app.models.user import User


bearer_scheme = HTTPBearer(auto_error=False)

@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: UUID

def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
    session: Session = Depends(get_db_session),
) -> AuthenticatedUser:

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = verify_access_token(
            token=credentials.credentials,
            public_key=request.app.state.jwt_public_key,
            issuer=request.app.state.jwt_issuer,
            audience=request.app.state.jwt_audience,
        )

        user_id = UUID(claims["sub"])

    except (
        jwt.InvalidTokenError,
        ValueError,
        TypeError,
        KeyError,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = session.scalar(
        select(User).where(
            User.id == user_id,
            User.status == "ACTIVE",
        )
    )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive user",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return AuthenticatedUser(user_id=user.id)