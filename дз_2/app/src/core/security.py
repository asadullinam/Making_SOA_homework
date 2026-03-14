from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError
from passlib.context import CryptContext

from core.config import settings
from core.errors import ApiError

pwd_context = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    try:
        return pwd_context.hash(password)
    except ValueError as exc:
        raise ApiError(
            "VALIDATION_ERROR",
            400,
            "Validation error",
            {"fields": [{"field": "password", "message": "Invalid password value"}]},
        ) from exc


def verify_password(password: str, hashed_password: str) -> bool:
    return pwd_context.verify(password, hashed_password)


def _create_token(subject: str, role: str, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "role": role,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    secret = settings.jwt_secret_key if token_type == "access" else settings.jwt_refresh_secret_key
    return jwt.encode(payload, secret, algorithm="HS256")


def create_access_token(user_id: str, role: str) -> str:
    expires = timedelta(minutes=settings.access_token_expires_minutes)
    return _create_token(user_id, role, "access", expires)


def create_refresh_token(user_id: str, role: str) -> str:
    expires = timedelta(days=settings.refresh_token_expires_days)
    return _create_token(user_id, role, "refresh", expires)


def verify_token(token: str, token_type: str) -> dict[str, Any]:
    secret = settings.jwt_secret_key if token_type == "access" else settings.jwt_refresh_secret_key
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except ExpiredSignatureError as exc:
        code = "TOKEN_EXPIRED" if token_type == "access" else "REFRESH_TOKEN_INVALID"
        raise ApiError(code, 401, "Token expired") from exc
    except JWTError as exc:
        code = "TOKEN_INVALID" if token_type == "access" else "REFRESH_TOKEN_INVALID"
        raise ApiError(code, 401, "Token invalid") from exc

    if payload.get("type") != token_type:
        code = "TOKEN_INVALID" if token_type == "access" else "REFRESH_TOKEN_INVALID"
        raise ApiError(code, 401, "Token type mismatch")

    return payload
