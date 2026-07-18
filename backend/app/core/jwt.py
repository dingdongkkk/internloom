"""Self-implemented JWT access + refresh tokens. [OPUS]

No third-party auth. Access tokens expire in 1h; refresh tokens in 7d and carry
a distinct token_type so a refresh token can never be replayed as an access token
(and vice-versa). /auth/refresh mints a fresh access token from a valid refresh.
"""
from datetime import datetime, timedelta, timezone
import jwt as pyjwt

from .config import settings
from .exceptions import ApiError


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _encode(sub: str, role: str, token_type: str, ttl: timedelta) -> str:
    payload = {
        "sub": str(sub),
        "role": role,
        "type": token_type,
        "iat": int(_now().timestamp()),
        "exp": int((_now() + ttl).timestamp()),
    }
    return pyjwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id, role: str) -> str:
    return _encode(user_id, role, "access", timedelta(minutes=settings.ACCESS_TOKEN_TTL_MIN))


def create_refresh_token(user_id, role: str) -> str:
    return _encode(user_id, role, "refresh", timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS))


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = pyjwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except pyjwt.ExpiredSignatureError:
        raise ApiError(401, "TOKEN_EXPIRED", "Token has expired")
    except pyjwt.InvalidTokenError:
        raise ApiError(401, "INVALID_TOKEN", "Token is invalid")
    if payload.get("type") != expected_type:
        raise ApiError(401, "WRONG_TOKEN_TYPE",
                       f"Expected a {expected_type} token")
    return payload
