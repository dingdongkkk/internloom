"""Applications router. [OPUS]

  POST  /applications/{id}/withdraw   student, from `submitted` only (reopens cap-closed listing)
  PATCH /applications/{id}/status     company moves an application forward
  PATCH /applications/bulk-status     company bulk transition (single endpoint, not 50 calls)
"""
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.envelope import ok
from app.core.deps import require_role, CurrentUser
from app.core.exceptions import not_found, forbidden, bad_request
from app.models.enums import Role, ApplicationStatus
from app.models.application import Application
from app.models.listing import Listing
from app.services import apply as apply_service, application_state, notifications

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("/mine")
def my_applications(
    current: CurrentUser = Depends(require_role(Role.student)),
    db: Session = Depends(get_db),
):
    """Spec 2.1: a student sees the status of their OWN applications only."""
    rows = (
        db.query(Application)
        .filter(Application.student_id == current.id)
        .order_by(Application.created_at.desc())
        .limit(100)
        .all()
    )
    data = [{
        "application_id": a.id,
        "listing_id": a.listing_id,
        "listing_title": a.listing.title if a.listing else None,
        "status": a.status.value,
        "match_score": float(a.match_score_snapshot) if a.match_score_snapshot is not None else None,
        "applied_at": a.created_at.isoformat() if a.created_at else None,
        "can_withdraw": a.status == ApplicationStatus.submitted,
    } for a in rows]
    return ok(data)


@router.post("/{application_id}/withdraw")
def withdraw(application_id: int,
             current: CurrentUser = Depends(require_role(Role.student)),
             db: Session = Depends(get_db)):
    app_obj = apply_service.withdraw_application(
        db, student_id=current.id, application_id=application_id)
    return ok({"application_id": app_obj.id, "status": app_obj.status.value})


class AppStatusIn(BaseModel):
    status: ApplicationStatus


def _assert_company_owns(db, application: Application, company_id: int) -> Listing:
    listing = db.get(Listing, application.listing_id)
    if listing is None or listing.company_id != company_id:
        raise forbidden("You can only manage applications for your own listings")
    return listing


@router.patch("/{application_id}/status")
def update_status(application_id: int, body: AppStatusIn,
                  current: CurrentUser = Depends(require_role(Role.company)),
                  db: Session = Depends(get_db)):
    application = db.get(Application, application_id)
    if application is None:
        raise not_found("Application")
    _assert_company_owns(db, application, current.id)

    application_state.company_transition(application, body.status)
    notifications.application_status_changed(
        db, application.student_id, application.id, body.status.value)
    db.commit()
    return ok({"application_id": application.id, "status": application.status.value})


class BulkStatusIn(BaseModel):
    listing_id: int
    from_status: ApplicationStatus = ApplicationStatus.submitted
    to_status: ApplicationStatus = ApplicationStatus.rejected
    older_than_days: Optional[int] = None   # e.g. reject all Submitted older than 7 days


@router.patch("/bulk-status")
def bulk_status(body: BulkStatusIn,
                current: CurrentUser = Depends(require_role(Role.company)),
                db: Session = Depends(get_db)):
    listing = db.get(Listing, body.listing_id)
    if listing is None:
        raise not_found("Listing")
    if listing.company_id != current.id:
        raise forbidden("You can only bulk-update your own listings' applications")

    q = db.query(Application).filter(
        Application.listing_id == body.listing_id,
        Application.status == body.from_status,
    )
    if body.older_than_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=body.older_than_days)
        q = q.filter(Application.created_at < cutoff)

    updated = 0
    for application in q.all():
        try:
            application_state.company_transition(application, body.to_status)
        except Exception:
            continue  # skip any that aren't legally transitionable; report the count
        notifications.application_status_changed(
            db, application.student_id, application.id, body.to_status.value)
        updated += 1

    db.commit()
    return ok({"listing_id": body.listing_id, "updated": updated,
               "from": body.from_status.value, "to": body.to_status.value})
