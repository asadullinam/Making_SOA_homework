from fastapi import Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from core.db import get_db
from core.errors import ApiError
from core.security import verify_token
from models.user import User


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> User:
    if not credentials or not credentials.credentials:
        raise ApiError("TOKEN_INVALID", 401, "Missing access token")

    token = credentials.credentials.strip()
    payload = verify_token(token, "access")

    user = db.query(User).filter(User.id == payload.get("sub")).one_or_none()
    if not user:
        raise ApiError("TOKEN_INVALID", 401, "User not found")

    request.state.user_id = str(user.id)

    return user


def require_roles(*roles: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role.value not in roles:
            raise ApiError("ACCESS_DENIED", 403, "Access denied")
        return user

    return checker
