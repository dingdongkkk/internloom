"""The matching engine. [OPUS] — computed at query time, not stored.

Score in [0, 100], a weighted sum of five signals (weights in config, sum to 1.0):

  required   0.45  fraction of the listing's REQUIRED skills the student has
  preferred  0.15  fraction of the listing's PREFERRED skills the student has
  branch/yr  0.20  branch match + graduation-year proximity (never a hard exclude)
  complete   0.12  profile completeness/100 (incomplete profiles rank lower)
  recency    0.08  exp decay on listing age (~1.0 today, ~0.37 at 30 days)

Each sub-signal is normalized to [0,1], so the weighted sum is directly a %.

--- Why this is not O(n^2) ---
The caller resolves the student's skills ONCE into a set[int] and passes it in.
Listings are loaded with their skills eagerly (selectinload) so there is no N+1.
Per listing the work is set intersection over its own skill ids — O(k) where k is
that listing's skill count, not O(students * listings). So scoring M listings for
one student is O(sum of listing skills), i.e. linear in the data actually read.
At real scale you'd (a) push required-skill overlap into a SQL pre-filter using
the student_skills/listing_skills join + GIN index, (b) cache per-listing static
terms (recency bucket, required/preferred id sets), and (c) recompute lazily.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp
from typing import Iterable

from app.core.config import settings
from app.models.enums import SkillKind


@dataclass
class MatchBreakdown:
    score: float
    required: float
    preferred: float
    branch_year: float
    completeness: float
    recency: float

    def as_dict(self) -> dict:
        # Exposed to the student so they can see WHY they ranked where they did.
        return {
            "score": round(self.score, 2),
            "breakdown": {
                "required_skills": round(self.required, 3),
                "preferred_skills": round(self.preferred, 3),
                "branch_year": round(self.branch_year, 3),
                "completeness": round(self.completeness, 3),
                "recency": round(self.recency, 3),
            },
        }


def _skill_fraction(student_skill_ids: set[int], target_ids: set[int]) -> float:
    if not target_ids:
        return 1.0  # a listing that requires nothing is neutral, not a zero
    return len(student_skill_ids & target_ids) / len(target_ids)


def _branch_year_score(student_branch, student_grad_year,
                       listing_branch, listing_grad_year) -> float:
    """Soft alignment. A mismatch lowers rank but never excludes."""
    # Branch: exact match strong; otherwise a floor so ECE still surfaces for a CSE role.
    if listing_branch and student_branch:
        branch = 1.0 if student_branch.strip().lower() == listing_branch.strip().lower() else 0.4
    else:
        branch = 0.7  # unspecified target -> mildly positive
    # Graduation year: decay 0.25 per year of distance from the target, floored at 0.
    if listing_grad_year and student_grad_year:
        year = max(0.0, 1.0 - 0.25 * abs(int(student_grad_year) - int(listing_grad_year)))
    else:
        year = 0.7
    return 0.6 * branch + 0.4 * year


def _recency_score(created_at: datetime) -> float:
    if created_at is None:
        return 0.5
    now = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
    return exp(-age_days / 30.0)


def score_listing(
    *,
    student_skill_ids: set[int],
    student_branch,
    student_grad_year,
    completeness: int,
    required_skill_ids: set[int],
    preferred_skill_ids: set[int],
    listing_branch,
    listing_grad_year,
    created_at: datetime,
) -> MatchBreakdown:
    req = _skill_fraction(student_skill_ids, required_skill_ids)
    pref = _skill_fraction(student_skill_ids, preferred_skill_ids)
    by = _branch_year_score(student_branch, student_grad_year, listing_branch, listing_grad_year)
    comp = max(0.0, min(1.0, completeness / 100.0))
    rec = _recency_score(created_at)

    total = 100.0 * (
        settings.W_REQUIRED * req
        + settings.W_PREFERRED * pref
        + settings.W_BRANCH_YEAR * by
        + settings.W_COMPLETENESS * comp
        + settings.W_RECENCY * rec
    )
    return MatchBreakdown(total, req, pref, by, comp, rec)


def split_listing_skills(listing) -> tuple[set[int], set[int]]:
    """Partition a listing's skills into (required_ids, preferred_ids)."""
    required, preferred = set(), set()
    for ls in listing.skills:
        (required if ls.kind == SkillKind.required else preferred).add(ls.skill_id)
    return required, preferred
