"""Profile deletion constraint for DELETE /profile/me.

A student cannot delete their profile while they hold a pending/active application.
"Active" = any application not in a terminal state (rejected / offer_extended /
withdrawn). Enforced at the API layer, not just documented.
"""
from app.models.application import Application
from app.models.enums import ApplicationStatus
from app.core.exceptions import conflict

_TERMINAL = {ApplicationStatus.rejected, ApplicationStatus.offer_extended,
             ApplicationStatus.withdrawn}


def assert_deletable(db, student_id: int) -> None:
    blocking = (
        db.query(Application)
        .filter(Application.student_id == student_id,
                Application.status.notin_([s for s in _TERMINAL]))
        .count()
    )
    if blocking:
        raise conflict(
            "PROFILE_HAS_ACTIVE_APPLICATIONS",
            "Cannot delete profile while you have pending or active applications",
            {"active_applications": blocking},
        )
