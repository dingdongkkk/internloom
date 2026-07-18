"""Audit router (Bonus C).

GET /audit — admin only. Admin is out of scope as a full actor, so per the spec
the admin token is mocked: send header  X-Admin-Token: internloom-admin-demo
(or a JWT whose role is `admin`, so real admin auth can be added later without
touching this endpoint). Paginated; filterable by actor type and date range.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.envelope import paginated, clamp_pagination
from app.core.exceptions import ApiError, bad_request
from app.models.audit import AuditLog

router = APIRouter(prefix="/audit", tags=["audit"])

MOCK_ADMIN_TOKEN = "internloom-admin-demo"


def require_admin(
    x_admin_token: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> None:
    """Mock admin gate: shared header token, or a JWT carrying role=admin."""
    if x_admin_token == MOCK_ADMIN_TOKEN:
        return
    if authorization and authorization.lower().startswith("bearer "):
        try:
            from app.core.jwt import decode_token
            payload = decode_token(authorization.split(" ", 1)[1].strip(), "access")
            if payload.get("role") == "admin":
                return
        except ApiError:
            pass
    raise ApiError(403, "ADMIN_ONLY", "Audit log requires the admin token")


def _parse_date(value: Optional[str], name: str) -> Optional[datetime]:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise bad_request("INVALID_DATE", f"{name} must be YYYY-MM-DD", {name: value})


@router.get("")
def get_audit_log(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    actor_type: Optional[str] = Query(None, description="student | company | admin"),
    date_from: Optional[str] = Query(None, alias="from", description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, alias="to", description="YYYY-MM-DD"),
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
):
    page, page_size = clamp_pagination(page, page_size)

    q = db.query(AuditLog)
    if actor_type:
        q = q.filter(AuditLog.actor_role == actor_type)
    start = _parse_date(date_from, "from")
    end = _parse_date(date_to, "to")
    if start:
        q = q.filter(AuditLog.created_at >= start)
    if end:
        q = q.filter(AuditLog.created_at < end + timedelta(days=1))  # inclusive end date
    q = q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())

    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    data = [{
        "id": r.id,
        "actor_user_id": r.actor_user_id,
        "actor_role": r.actor_role,
        "action": r.action,
        "resource_type": r.resource_type,
        "resource_id": r.resource_id,
        "before": r.before,
        "after": r.after,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]
    return paginated(data, total, page, page_size)
