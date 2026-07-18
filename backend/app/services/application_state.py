"""Application lifecycle state machine. [OPUS]

Company-driven forward path:
  submitted -> under_review -> shortlisted -> (rejected | offer_extended)
A company may also reject from any non-terminal state.
Student-driven: withdraw, allowed ONLY from `submitted` (handled in apply.py so it
can also decrement the listing count atomically).
"""
from __future__ import annotations

from app.models.enums import ApplicationStatus as S
from app.core.exceptions import bad_request

_TERMINAL = {S.rejected, S.offer_extended, S.withdrawn}

# Company-allowed forward transitions.
_COMPANY_EDGES = {
    S.submitted: {S.under_review, S.rejected},
    S.under_review: {S.shortlisted, S.rejected},
    S.shortlisted: {S.offer_extended, S.rejected},
}


def company_transition(application, new_status: S) -> None:
    """Validate + apply a company status change. Mutates application, or raises."""
    current = application.status
    if current in _TERMINAL:
        raise bad_request("APPLICATION_TERMINAL",
                          f"Application is already in terminal state '{current.value}'")
    allowed = _COMPANY_EDGES.get(current, set())
    if new_status not in allowed:
        raise bad_request(
            "INVALID_APPLICATION_TRANSITION",
            f"Cannot move application from '{current.value}' to '{new_status.value}'",
            {"allowed_from_here": [s.value for s in allowed]},
        )
    application.status = new_status


def can_student_withdraw(application) -> bool:
    return application.status == S.submitted
