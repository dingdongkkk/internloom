"""Profile completeness score (0-100), computed on read, never stored. [OPUS]

Documented criteria (weights sum to 100). Skills scale linearly to full credit at
5+ skills because a single skill is a weak signal. Returned on every profile fetch
and consumed by the matching engine as the completeness penalty term.
"""
from decimal import Decimal

# field -> weight
WEIGHTS = {
    "name": 10,
    "college": 10,
    "branch": 10,
    "graduation_year": 10,
    "cgpa": 10,
    "skills": 20,        # linear: full credit at >= SKILLS_FOR_FULL
    "github_url": 10,
    "linkedin_url": 5,
    "bio": 5,
    "resume_url": 10,
}
SKILLS_FOR_FULL = 5


def _present(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def compute_completeness(profile, skill_count: int) -> int:
    """profile: StudentProfile ORM object; skill_count: number of linked skills."""
    score = 0.0
    for field, weight in WEIGHTS.items():
        if field == "skills":
            score += weight * min(skill_count, SKILLS_FOR_FULL) / SKILLS_FOR_FULL
        elif _present(getattr(profile, field, None)):
            score += weight
    return round(score)
