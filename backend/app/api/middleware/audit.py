"""Audit middleware (Bonus C).

Logs every successful (2xx) mutation — POST/PUT/PATCH/DELETE — to audit_log:
actor (decoded from the bearer token, unverified requests logged as anonymous),
action, resource type/id parsed from the path, before-state (a compact DB
snapshot fetched just before dispatch for PATCH/PUT/DELETE on known resources)
and after-state (the response envelope's `data` object).

Audit rows are written with their OWN short-lived session so an audit failure
can never roll back — or be rolled back by — the business transaction.
"""
from __future__ import annotations

import json
import re
from typing import Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_PATH_RE = re.compile(r"^/(listings|applications|profile|notifications|auth)(?:/(\d+))?")
_MAX_BODY = 20_000  # don't stuff huge payloads into the log


def _parse_resource(path: str) -> Tuple[Optional[str], Optional[int]]:
    m = _PATH_RE.match(path)
    if not m:
        return None, None
    singular = {"listings": "listing", "applications": "application",
                "profile": "profile", "notifications": "notification", "auth": "auth"}
    return singular[m.group(1)], int(m.group(2)) if m.group(2) else None


def _actor_from_request(request) -> Tuple[Optional[int], Optional[str]]:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None, None
    try:
        from app.core.jwt import decode_token
        payload = decode_token(auth.split(" ", 1)[1].strip(), expected_type="access")
        return int(payload["sub"]), payload.get("role")
    except Exception:
        return None, None  # invalid token -> anonymous; the route will 401 anyway


def _snapshot_before(resource_type: Optional[str], resource_id: Optional[int]) -> Optional[dict]:
    """Compact pre-mutation snapshot for resources where before-state matters."""
    if resource_type not in {"listing", "application"} or resource_id is None:
        return None
    from app.db.session import SessionLocal
    from app.models.listing import Listing
    from app.models.application import Application
    db = SessionLocal()
    try:
        if resource_type == "listing":
            row = db.get(Listing, resource_id)
            if row:
                return {"status": row.status.value,
                        "closed_reason": row.closed_reason.value if row.closed_reason else None,
                        "applicant_count": row.applicant_count,
                        "max_applicants": row.max_applicants,
                        "target_branch": row.target_branch,
                        "target_graduation_year": row.target_graduation_year}
        else:
            row = db.get(Application, resource_id)
            if row:
                return {"status": row.status.value}
        return None
    except Exception:
        return None
    finally:
        db.close()


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method not in MUTATING:
            return await call_next(request)

        resource_type, resource_id = _parse_resource(request.url.path)
        actor_id, actor_role = _actor_from_request(request)
        before = _snapshot_before(resource_type, resource_id)

        response = await call_next(request)
        if not (200 <= response.status_code < 300):
            return response  # only successful mutations enter the trail

        # Drain the streaming body to capture `after`, then rebuild the response.
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        after = None
        if body and len(body) <= _MAX_BODY:
            try:
                after = json.loads(body).get("data")
            except Exception:
                after = None

        self._write_row(actor_id, actor_role, request.method,
                        resource_type or "unknown", resource_id, before, after)

        return Response(content=body, status_code=response.status_code,
                        headers=dict(response.headers), media_type=response.media_type)

    @staticmethod
    def _write_row(actor_id, actor_role, action, resource_type, resource_id, before, after):
        from app.db.session import SessionLocal
        from app.models.audit import AuditLog
        db = SessionLocal()
        try:
            db.add(AuditLog(actor_user_id=actor_id, actor_role=actor_role, action=action,
                            resource_type=resource_type, resource_id=resource_id,
                            before=before, after=after))
            db.commit()
        except Exception:
            db.rollback()  # auditing must never break the request itself
        finally:
            db.close()
