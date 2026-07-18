"""Apply / withdraw — the concurrency-critical path. [OPUS] (Bonus B)

=== The cap race ===
Requirement: 5 simultaneous applies to a listing with 1 slot left => exactly 1
succeeds, 4 are rejected cleanly, no double-accept, no 500.

How we guarantee it:
  1. `SELECT ... FOR UPDATE` on the listing row. Postgres serializes the five
     transactions here: each waits its turn, so only one reads a given
     applicant_count value at a time. This turns the check-then-act into an
     atomic critical section.
  2. Inside the lock we re-read applicant_count (authoritative, denormalized on
     the row we just locked) and re-run accepts_applications(). The loser txns see
     count == cap and get a clean 409 CAP_REACHED.
  3. The UNIQUE(listing_id, student_id) constraint is the second line of defence:
     even a duplicate-apply race can't create two rows — the second INSERT raises
     IntegrityError which we translate to a clean 409, never a 500.
  4. When this apply fills the last slot we auto-close (status=closed,
     closed_reason=cap_reached) inside the same transaction, then commit.

=== Withdrawal reopen reconciliation (tricky part #4) ===
Withdrawing from `submitted` decrements applicant_count. If the listing was
auto-closed (closed_reason == cap_reached) and the count is now below cap, we
reopen it to active. This does NOT violate "no manual re-entry": a cap close is a
system state derived from the count, so it is reversible; a manual close
(closed_reason == manual) is a company decision and is never auto-reopened.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.models.listing import Listing
from app.models.application import Application
from app.models.enums import ListingStatus, ClosedReason, ApplicationStatus
from app.core.exceptions import ApiError, not_found, conflict, bad_request
from app.services import listing_state, notifications


_REASONS = {
    "LISTING_NOT_ACTIVE": "This listing is not accepting applications",
    "DEADLINE_PASSED": "The application deadline for this listing has passed",
    "CAP_REACHED": "This listing has reached its maximum number of applicants",
}


def apply_to_listing(db, *, student_id: int, listing_id: int, match_score: float | None) -> Application:
    now = datetime.now(timezone.utc)

    # (1) Lock the listing row — critical section begins.
    listing = (
        db.query(Listing)
        .filter(Listing.id == listing_id)
        .with_for_update()
        .first()
    )
    if listing is None:
        raise not_found("Listing")

    # (2) Re-check gates against the freshly-locked, authoritative row.
    ok, reason = listing_state.accepts_applications(listing, now)
    if not ok:
        raise conflict(reason, _REASONS.get(reason, "Cannot apply to this listing"))

    application = Application(
        listing_id=listing_id,
        student_id=student_id,
        status=ApplicationStatus.submitted,
        match_score_snapshot=match_score,
    )
    db.add(application)

    # (3) Duplicate-apply guard via the DB unique constraint.
    try:
        db.flush()  # forces the INSERT while we still hold the lock
    except IntegrityError:
        db.rollback()
        raise conflict("ALREADY_APPLIED", "You have already applied to this listing")

    # Count this application and auto-close if we just filled the last slot.
    listing.applicant_count += 1
    notifications.new_applicant(db, listing.company_id, listing.id, student_id)

    if listing.applicant_count >= listing.max_applicants:
        listing.status = ListingStatus.closed
        listing.closed_reason = ClosedReason.cap_reached
        notifications.listing_auto_closed(db, listing.company_id, listing.id)

    db.commit()          # (4) release lock, publish result atomically
    db.refresh(application)
    return application


def withdraw_application(db, *, student_id: int, application_id: int) -> Application:
    application = db.get(Application, application_id)
    if application is None or application.student_id != student_id:
        raise not_found("Application")

    if application.status != ApplicationStatus.submitted:
        raise bad_request(
            "WITHDRAW_NOT_ALLOWED",
            "You can only withdraw an application that is still in 'submitted' state",
            {"current_status": application.status.value},
        )

    # Lock the listing so the decrement + possible reopen is atomic vs concurrent applies.
    listing = (
        db.query(Listing).filter(Listing.id == application.listing_id).with_for_update().first()
    )

    application.status = ApplicationStatus.withdrawn
    if listing is not None:
        listing.applicant_count = max(0, listing.applicant_count - 1)

        # Reopen ONLY if the close was cap-driven (system state), not a manual close.
        if (
            listing.status == ListingStatus.closed
            and listing.closed_reason == ClosedReason.cap_reached
            and listing.applicant_count < listing.max_applicants
        ):
            listing.status = ListingStatus.active
            listing.closed_reason = None

    db.commit()
    db.refresh(application)
    return application
