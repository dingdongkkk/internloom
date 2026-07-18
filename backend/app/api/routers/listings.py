"""Listings router.

[OPUS] owns the hard endpoints:
  GET  /listings                  student feed, sorted by match score (desc)
  PATCH /listings/{id}/status     lifecycle transition guard
  GET  /listings/{id}/applicants  company-only, snapshot scores
  POST /listings/{id}/apply       concurrency-safe (delegates to services/apply)

The router also owns plain CRUD (POST /listings, PUT /listings/{id}) against the
same contract and shared helpers.
"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.core.envelope import ok, paginated, clamp_pagination
from app.core.deps import get_current_user, require_role, require_verified_student, CurrentUser
from app.core.exceptions import not_found, forbidden, bad_request
from app.models.enums import Role, ListingStatus, ApplicationStatus, LocationType, SkillKind
from app.models.listing import Listing
from app.models.profile import StudentProfile
from app.models.skill import StudentSkill, ListingSkill
from app.models.application import Application
from app.services import matching, listing_state, apply as apply_service
from app.services.completeness import compute_completeness
from app.services.skills import get_or_create_skills

router = APIRouter(prefix="/listings", tags=["listings"])


# ---------- shared helpers ----------
def _load_student_context(db: Session, student_id: int):
    profile = db.get(StudentProfile, student_id)
    if profile is None:
        raise not_found("Student profile")
    skill_ids = {s.skill_id for s in db.query(StudentSkill)
                 .filter(StudentSkill.student_id == student_id).all()}
    completeness = compute_completeness(profile, len(skill_ids))
    return profile, skill_ids, completeness


def score_for_student(listing, profile, skill_ids, completeness) -> matching.MatchBreakdown:
    req, pref = matching.split_listing_skills(listing)
    return matching.score_listing(
        student_skill_ids=skill_ids,
        student_branch=profile.branch,
        student_grad_year=profile.graduation_year,
        completeness=completeness,
        required_skill_ids=req,
        preferred_skill_ids=pref,
        listing_branch=listing.target_branch,
        listing_grad_year=listing.target_graduation_year,
        created_at=listing.created_at,
    )


# ---------- OPUS: student feed, ranked by match ----------
@router.get("")
def list_listings_for_student(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current: CurrentUser = Depends(require_role(Role.student)),
    db: Session = Depends(get_db),
):
    page, page_size = clamp_pagination(page, page_size)
    profile, skill_ids, completeness = _load_student_context(db, current.id)

    # Only active, not-past-deadline listings are worth ranking. Eager-load skills
    # (selectinload) so scoring is O(sum of skills), never N+1 / O(n^2).
    now = datetime.now(timezone.utc)
    listings = (
        db.query(Listing)
        .options(selectinload(Listing.skills))
        .filter(Listing.status == ListingStatus.active)
        .all()
    )

    scored = []
    for lst in listings:
        accepts, _ = listing_state.accepts_applications(lst, now)
        bd = score_for_student(lst, profile, skill_ids, completeness)
        scored.append((lst, bd, accepts))
    scored.sort(key=lambda t: t[1].score, reverse=True)  # rank desc by score

    total = len(scored)
    window = scored[(page - 1) * page_size: page * page_size]
    data = [{
        "id": lst.id,
        "title": lst.title,
        "location": lst.location.value,
        "stipend": float(lst.stipend) if lst.stipend is not None else None,
        "deadline": lst.deadline.isoformat() if lst.deadline else None,
        "target_branch": lst.target_branch,
        "target_graduation_year": lst.target_graduation_year,
        "accepting_applications": accepts,
        **bd.as_dict(),  # score + breakdown so the student sees WHY they ranked here
    } for (lst, bd, accepts) in window]
    return paginated(data, total, page, page_size)


# ---------- company's own listings (all statuses) ----------
@router.get("/mine")
def my_listings(
    current: CurrentUser = Depends(require_role(Role.company)),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Listing)
        .options(selectinload(Listing.skills))
        .filter(Listing.company_id == current.id)
        .order_by(Listing.created_at.desc())
        .limit(100)
        .all()
    )
    return ok([_serialize_listing(l) for l in rows])


# ---------- OPUS: lifecycle transition ----------
class StatusIn(BaseModel):
    status: ListingStatus


@router.patch("/{listing_id}/status")
def change_status(listing_id: int, body: StatusIn,
                  current: CurrentUser = Depends(require_role(Role.company)),
                  db: Session = Depends(get_db)):
    listing = db.get(Listing, listing_id)
    if listing is None:
        raise not_found("Listing")
    if listing.company_id != current.id:
        raise forbidden("You can only modify your own listings")
    listing_state.transition(listing, body.status,
                             company_is_approved=current.user.company.is_approved)
    if listing.status == ListingStatus.active:
        notify_high_matches(db, listing)  # spec: alert students with score > 70
    db.commit()
    return ok({"id": listing.id, "status": listing.status.value,
               "closed_reason": listing.closed_reason.value if listing.closed_reason else None})


# ---------- OPUS: applicants (company-only, snapshot scores) ----------
@router.get("/{listing_id}/applicants")
def list_applicants(listing_id: int,
                    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                    current: CurrentUser = Depends(require_role(Role.company)),
                    db: Session = Depends(get_db)):
    page, page_size = clamp_pagination(page, page_size)
    listing = db.get(Listing, listing_id)
    if listing is None:
        raise not_found("Listing")
    if listing.company_id != current.id:
        raise forbidden("You can only view applicants for your own listings")

    q = (db.query(Application)
         .filter(Application.listing_id == listing_id,
                 Application.status != ApplicationStatus.withdrawn)
         .order_by(Application.match_score_snapshot.desc().nullslast()))
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    data = [{
        "application_id": a.id,
        "student_id": a.student_id,
        "status": a.status.value,
        # snapshot score = the score AT APPLY TIME (stable; see tricky part #3)
        "match_score": float(a.match_score_snapshot) if a.match_score_snapshot is not None else None,
        "applied_at": a.created_at.isoformat() if a.created_at else None,
    } for a in rows]
    return paginated(data, total, page, page_size)


# ---------- OPUS: apply (delegates to concurrency-safe service) ----------
@router.post("/{listing_id}/apply", status_code=201)
def apply(listing_id: int,
          current: CurrentUser = Depends(require_verified_student),
          db: Session = Depends(get_db)):
    # Compute + freeze the match score at apply time.
    listing = db.get(Listing, listing_id, options=[selectinload(Listing.skills)])
    if listing is None:
        raise not_found("Listing")
    profile, skill_ids, completeness = _load_student_context(db, current.id)
    score = score_for_student(listing, profile, skill_ids, completeness).score

    application = apply_service.apply_to_listing(
        db, student_id=current.id, listing_id=listing_id, match_score=score)
    return ok({"application_id": application.id, "status": application.status.value,
               "match_score": round(score, 2)})


# ======================================================================
# Plain CRUD — implemented against the contract above.
# ======================================================================
HIGH_MATCH_THRESHOLD = 70.0


def notify_high_matches(db: Session, listing: Listing) -> int:
    """On activation, notify verified students whose match score > 70.

    Reuses the Opus scoring path (score_for_student) — one pass over students,
    each scored with O(k) set math. Returns how many were notified.
    """
    from app.models.user import User
    from app.services.notifications import high_match_listing

    notified = 0
    students = (db.query(StudentProfile)
                .join(User, User.id == StudentProfile.user_id)
                .filter(User.is_email_verified.is_(True))
                .all())
    for profile in students:
        skill_ids = {s.skill_id for s in db.query(StudentSkill)
                     .filter(StudentSkill.student_id == profile.user_id).all()}
        completeness = compute_completeness(profile, len(skill_ids))
        bd = score_for_student(listing, profile, skill_ids, completeness)
        if bd.score > HIGH_MATCH_THRESHOLD:
            high_match_listing(db, profile.user_id, listing.id, bd.score)
            notified += 1
    return notified


class ListingCreateIn(BaseModel):
    title: str
    description: Optional[str] = None
    required_skills: List[str] = []
    preferred_skills: List[str] = []
    stipend: Optional[float] = Field(None, ge=0)
    location: LocationType = LocationType.remote
    deadline: Optional[datetime] = None
    target_branch: Optional[str] = Field(None, max_length=100)
    target_graduation_year: Optional[int] = Field(None, ge=2000, le=2100)
    max_applicants: int = Field(..., gt=0)


class ListingUpdateIn(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    required_skills: Optional[List[str]] = None
    preferred_skills: Optional[List[str]] = None
    stipend: Optional[float] = Field(None, ge=0)
    location: Optional[LocationType] = None
    deadline: Optional[datetime] = None
    target_branch: Optional[str] = Field(None, max_length=100)
    target_graduation_year: Optional[int] = Field(None, ge=2000, le=2100)
    max_applicants: Optional[int] = Field(None, gt=0)
    status: Optional[ListingStatus] = None


def _replace_listing_skills(db: Session, listing_id: int,
                            required: List[str], preferred: List[str]) -> None:
    """Swap the listing's skill set — normalized join rows, never CSV."""
    db.query(ListingSkill).filter(ListingSkill.listing_id == listing_id).delete()
    for names, kind in ((required, SkillKind.required), (preferred, SkillKind.preferred)):
        for skill in get_or_create_skills(db, names):
            db.add(ListingSkill(listing_id=listing_id, skill_id=skill.id, kind=kind))


def _serialize_listing(listing: Listing) -> dict:
    required = sorted(ls.skill.name for ls in listing.skills if ls.kind == SkillKind.required)
    preferred = sorted(ls.skill.name for ls in listing.skills if ls.kind == SkillKind.preferred)
    return {
        "id": listing.id,
        "title": listing.title,
        "description": listing.description,
        "required_skills": required,
        "preferred_skills": preferred,
        "stipend": float(listing.stipend) if listing.stipend is not None else None,
        "location": listing.location.value,
        "deadline": listing.deadline.isoformat() if listing.deadline else None,
        "target_branch": listing.target_branch,
        "target_graduation_year": listing.target_graduation_year,
        "max_applicants": listing.max_applicants,
        "applicant_count": listing.applicant_count,
        "status": listing.status.value,
        "closed_reason": listing.closed_reason.value if listing.closed_reason else None,
    }


@router.post("", status_code=201)
def create_listing(body: ListingCreateIn,
                   current: CurrentUser = Depends(require_role(Role.company)),
                   db: Session = Depends(get_db)):
    listing = Listing(
        company_id=current.id,
        title=body.title,
        description=body.description,
        stipend=body.stipend,
        location=body.location,
        deadline=body.deadline,
        target_branch=body.target_branch,
        target_graduation_year=body.target_graduation_year,
        max_applicants=body.max_applicants,
        status=ListingStatus.draft,  # always born in draft; activation is a transition
    )
    db.add(listing)
    db.flush()
    _replace_listing_skills(db, listing.id, body.required_skills, body.preferred_skills)
    db.commit()
    db.refresh(listing)
    return ok(_serialize_listing(listing))


@router.put("/{listing_id}")
def update_listing(listing_id: int, body: ListingUpdateIn,
                   current: CurrentUser = Depends(require_role(Role.company)),
                   db: Session = Depends(get_db)):
    listing = db.get(Listing, listing_id, options=[selectinload(Listing.skills)])
    if listing is None:
        raise not_found("Listing")
    if listing.company_id != current.id:
        raise forbidden("You can only edit your own listings")

    provided = body.dict(exclude_unset=True)
    for field in (
        "title", "description", "stipend", "location", "deadline",
        "target_branch", "target_graduation_year",
    ):
        if field in provided:
            setattr(listing, field, provided[field])

    if body.max_applicants is not None:
        if body.max_applicants < listing.applicant_count:
            raise bad_request(
                "CAP_BELOW_APPLICANTS",
                "max_applicants cannot be lower than the current applicant count",
                {"applicant_count": listing.applicant_count})
        listing.max_applicants = body.max_applicants

    # Skill edits never rewrite existing applicants' snapshot scores — students see
    # live scores, companies see apply-time snapshots (DESIGN_DECISIONS, tricky #3).
    if body.required_skills is not None or body.preferred_skills is not None:
        current_req = [ls.skill.name for ls in listing.skills if ls.kind == SkillKind.required]
        current_pref = [ls.skill.name for ls in listing.skills if ls.kind == SkillKind.preferred]
        _replace_listing_skills(
            db, listing.id,
            body.required_skills if body.required_skills is not None else current_req,
            body.preferred_skills if body.preferred_skills is not None else current_pref)

    activated = False
    if body.status is not None and body.status != listing.status:
        # Never set .status directly — the Opus state machine owns transitions.
        listing_state.transition(listing, body.status,
                                 company_is_approved=current.user.company.is_approved)
        activated = listing.status == ListingStatus.active

    if activated:
        db.expire(listing, ["skills"])  # re-load skills so scoring sees the edit
        notify_high_matches(db, listing)

    db.commit()
    db.refresh(listing)
    return ok(_serialize_listing(listing))
