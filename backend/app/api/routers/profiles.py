"""Profile router, implemented against docs/CONTRACT.md.

  GET    /profile/me   own profile + computed completeness (never stored)
  PUT    /profile/me   update own profile; skills resolved to rows, never CSV
  DELETE /profile/me   blocked while pending/active applications exist
                       (assert_deletable — Opus-provided guard). Deletes the
                       account; a student user without a profile is not a
                       meaningful entity on this platform.

Pattern copied from routers/auth.py: Pydantic body in, ok() envelope out,
Depends guards, ApiError for failures. Scoped strictly to the caller — a student
can only ever touch their OWN profile.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, constr
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.envelope import ok
from app.core.deps import require_role, CurrentUser
from app.core.exceptions import not_found
from app.models.enums import Role
from app.models.profile import StudentProfile
from app.models.skill import StudentSkill
from app.models.user import User
from app.services.completeness import compute_completeness
from app.services.profile_guard import assert_deletable
from app.services.skills import get_or_create_skills

router = APIRouter(prefix="/profile", tags=["profile"])


class ProfileUpdateIn(BaseModel):
    name: Optional[constr(max_length=150)] = None
    college: Optional[constr(max_length=200)] = None
    branch: Optional[constr(max_length=100)] = None
    graduation_year: Optional[int] = Field(None, ge=2000, le=2100)
    cgpa: Optional[float] = Field(None, ge=0, le=10)
    github_url: Optional[constr(max_length=300)] = None
    linkedin_url: Optional[constr(max_length=300)] = None
    bio: Optional[str] = None
    resume_url: Optional[constr(max_length=300)] = None
    skills: Optional[List[constr(min_length=1, max_length=100)]] = None


_SCALAR_FIELDS = (
    "name", "college", "branch", "graduation_year", "cgpa",
    "github_url", "linkedin_url", "bio", "resume_url",
)


def _load_own_profile(db: Session, student_id: int) -> StudentProfile:
    profile = db.get(StudentProfile, student_id)
    if profile is None:
        raise not_found("Student profile")
    return profile


def _serialize(db: Session, profile: StudentProfile) -> dict:
    links = db.query(StudentSkill).filter(StudentSkill.student_id == profile.user_id).all()
    skill_names = sorted(link.skill.name for link in links)
    return {
        "user_id": profile.user_id,
        "name": profile.name,
        "college": profile.college,
        "branch": profile.branch,
        "graduation_year": profile.graduation_year,
        "cgpa": float(profile.cgpa) if profile.cgpa is not None else None,
        "github_url": profile.github_url,
        "linkedin_url": profile.linkedin_url,
        "bio": profile.bio,
        "resume_url": profile.resume_url,
        "skills": skill_names,
        # Computed on every fetch, per spec — see services/completeness.py.
        "completeness": compute_completeness(profile, len(skill_names)),
    }


@router.get("/me")
def get_my_profile(current: CurrentUser = Depends(require_role(Role.student)),
                   db: Session = Depends(get_db)):
    profile = _load_own_profile(db, current.id)
    return ok(_serialize(db, profile))


@router.put("/me")
def update_my_profile(body: ProfileUpdateIn,
                      current: CurrentUser = Depends(require_role(Role.student)),
                      db: Session = Depends(get_db)):
    profile = _load_own_profile(db, current.id)

    # Only touch fields the caller actually sent (partial update semantics).
    provided = body.dict(exclude_unset=True)
    for field in _SCALAR_FIELDS:
        if field in provided:
            setattr(profile, field, provided[field])

    # Replace the skill set via the join table — normalized rows, never CSV.
    if body.skills is not None:
        skills = get_or_create_skills(db, body.skills)
        db.query(StudentSkill).filter(StudentSkill.student_id == current.id).delete()
        for skill in skills:
            db.add(StudentSkill(student_id=current.id, skill_id=skill.id))

    db.commit()
    return ok(_serialize(db, profile))


@router.delete("/me")
def delete_my_profile(current: CurrentUser = Depends(require_role(Role.student)),
                      db: Session = Depends(get_db)):
    _load_own_profile(db, current.id)
    # Opus-provided constraint: cannot delete with pending/active applications.
    assert_deletable(db, current.id)

    # Delete the account; profile, skills and (terminal-only) applications cascade.
    user = db.get(User, current.id)
    db.delete(user)
    db.commit()
    return ok({"deleted": True, "user_id": current.id})
