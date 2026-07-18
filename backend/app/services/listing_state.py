"""Listing lifecycle state machine. [OPUS]

Valid MANUAL transitions only:  draft -> active -> closed.
Forbidden: draft -> closed (skips active),  closed -> active (no manual re-entry).

Auto-close on cap and auto-reopen on withdrawal are SYSTEM transitions handled in
services/apply.py — they are deliberately not routed through this guard, because a
cap-driven close is a function of applicant_count, not a company decision. The
`closed_reason` column keeps the two kinds distinguishable (tricky part #4).
"""
from __future__ import annotations

from app.models.enums import ListingStatus, ClosedReason
from app.core.exceptions import bad_request, forbidden

# Allowed manual edges.
_ALLOWED = {
    (ListingStatus.draft, ListingStatus.active),
    (ListingStatus.active, ListingStatus.closed),
}


def transition(listing, new_status: ListingStatus, *, company_is_approved: bool) -> None:
    """Apply a company-initiated status change, or raise ApiError. Mutates listing."""
    current = listing.status
    if new_status == current:
        return  # idempotent no-op

    if (current, new_status) not in _ALLOWED:
        raise bad_request(
            "INVALID_STATE_TRANSITION",
            f"Cannot move listing from '{current.value}' to '{new_status.value}'",
            {"allowed_from_here": [b.value for (a, b) in _ALLOWED if a == current]},
        )

    # A listing can only go live if the company has been approved by an admin.
    if new_status == ListingStatus.active and not company_is_approved:
        raise forbidden("Company is not yet approved; listings cannot be activated")

    listing.status = new_status
    if new_status == ListingStatus.closed:
        listing.closed_reason = ClosedReason.manual  # explicit, non-reversible close
    elif new_status == ListingStatus.active:
        listing.closed_reason = None


def accepts_applications(listing, now) -> tuple[bool, str | None]:
    """Gate used by the apply endpoint. Returns (ok, reason_code_if_not)."""
    if listing.status != ListingStatus.active:
        return False, "LISTING_NOT_ACTIVE"
    if listing.deadline is not None:
        deadline = listing.deadline
        if deadline.tzinfo is None:
            from datetime import timezone
            deadline = deadline.replace(tzinfo=timezone.utc)
        if now > deadline:
            # Deadline passed even though status is still Active — reject anyway.
            return False, "DEADLINE_PASSED"
    if listing.applicant_count >= listing.max_applicants:
        return False, "CAP_REACHED"
    return True, None
