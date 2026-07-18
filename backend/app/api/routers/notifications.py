"""Notifications router. Services create the rows; this router exposes the read side.

  GET   /notifications       own notifications, paginated, filterable by ?is_read=
  PATCH /notifications/read  mark read — single/bulk via {"ids":[...]} or {"all":true}

Every query is scoped to Notification.user_id == current.id — one actor can never
read or mutate another actor's notifications.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.envelope import ok, paginated, clamp_pagination
from app.core.deps import get_current_user, CurrentUser
from app.core.exceptions import bad_request
from app.models.notification import Notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    is_read: Optional[bool] = Query(None),
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    page, page_size = clamp_pagination(page, page_size)

    q = db.query(Notification).filter(Notification.user_id == current.id)
    if is_read is not None:
        q = q.filter(Notification.is_read == is_read)
    q = q.order_by(Notification.created_at.desc(), Notification.id.desc())

    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()  # never unbounded
    data = [{
        "id": n.id,
        "type": n.type,
        "message": n.message,
        "resource_type": n.resource_type,
        "resource_id": n.resource_id,
        "is_read": n.is_read,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    } for n in rows]
    return paginated(data, total, page, page_size)


class MarkReadIn(BaseModel):
    ids: Optional[List[int]] = None
    all: Optional[bool] = None


@router.patch("/read")
def mark_read(body: MarkReadIn,
              current: CurrentUser = Depends(get_current_user),
              db: Session = Depends(get_db)):
    if not body.all and not body.ids:
        raise bad_request("NOTHING_TO_MARK",
                          'Provide {"ids": [...]} or {"all": true}')

    q = db.query(Notification).filter(
        Notification.user_id == current.id,        # own notifications only
        Notification.is_read.is_(False),
    )
    if not body.all:
        q = q.filter(Notification.id.in_(body.ids))

    updated = q.update({Notification.is_read: True}, synchronize_session=False)
    db.commit()
    return ok({"marked_read": updated})
