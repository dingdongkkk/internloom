"""Auth dependencies & role guards. [OPUS]

Every protected route depends on get_current_user; role-restricted routes add
require_role(...). This is the single choke point that makes "no auth on protected
endpoints" (a disqualifier) impossible to forget — a route without these deps
simply has no `current` to work with.
"""
from dataclasses import dataclass
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.models.enums import Role
from .jwt import decode_token
from .exceptions import ApiError, forbidden


@dataclass
class CurrentUser:
    id: int
    role: Role
    is_email_verified: bool
    user: User


def get_current_user(
    authorization: str = Header(default=None),
    db: Session = Depends(get_db),
) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "MISSING_TOKEN", "Authorization: Bearer <token> required")
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_token(token, expected_type="access")

    user = db.get(User, int(payload["sub"]))
    if not user:
        raise ApiError(401, "USER_NOT_FOUND", "Token subject no longer exists")
    return CurrentUser(id=user.id, role=user.role,
                       is_email_verified=user.is_email_verified, user=user)


def require_role(*allowed: Role):
    """Dependency factory: require_role(Role.company)."""
    def _guard(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current.role not in allowed:
            raise forbidden(f"This endpoint requires role: {', '.join(r.value for r in allowed)}")
        return current
    return _guard


def require_verified_student(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Students may browse while unverified but cannot apply until verified."""
    if current.role != Role.student:
        raise forbidden("Only students may perform this action")
    if not current.is_email_verified:
        raise ApiError(403, "EMAIL_NOT_VERIFIED",
                       "Verify your college email before applying to roles")
    return current
