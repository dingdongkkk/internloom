"""Notification creation helpers.

Meaningful state changes call these. Rows are committed by the caller's transaction
so a notification never exists for an action that rolled back.
"""
from __future__ import annotations

from app.models.notification import Notification


def notify(db, *, user_id: int, type_: str, message: str,
           resource_type: str | None = None, resource_id: int | None = None) -> Notification:
    n = Notification(
        user_id=user_id, type=type_, message=message,
        resource_type=resource_type, resource_id=resource_id, is_read=False,
    )
    db.add(n)
    return n


# --- Semantic wrappers for the events the spec enumerates ---
def application_status_changed(db, student_user_id, application_id, new_status):
    return notify(db, user_id=student_user_id, type_="application_status",
                  message=f"Your application status is now '{new_status}'.",
                  resource_type="application", resource_id=application_id)


def high_match_listing(db, student_user_id, listing_id, score):
    return notify(db, user_id=student_user_id, type_="high_match",
                  message=f"A new listing matches your profile ({score:.0f}% match).",
                  resource_type="listing", resource_id=listing_id)


def new_applicant(db, company_user_id, listing_id, student_id):
    return notify(db, user_id=company_user_id, type_="new_applicant",
                  message="A new student applied to your listing.",
                  resource_type="listing", resource_id=listing_id)


def listing_auto_closed(db, company_user_id, listing_id):
    return notify(db, user_id=company_user_id, type_="listing_auto_closed",
                  message="Your listing was auto-closed after reaching its applicant cap.",
                  resource_type="listing", resource_id=listing_id)
