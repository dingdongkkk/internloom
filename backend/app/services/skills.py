"""Skill name -> Skill row resolution.

Shared by profile PUT and listing create/edit. Names are case-folded and trimmed
so 'React.js', 'react.js ' and 'REACT.JS' all map to one canonical row — skills
are never stored as CSV, only as rows linked via the join tables.
"""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.models.skill import Skill


def _canonical(name: str) -> str:
    return " ".join(name.strip().split()).lower()


def get_or_create_skills(db: Session, names: List[str]) -> List[Skill]:
    """Resolve a list of raw skill names to Skill rows, creating missing ones.

    Deduplicates on the canonical form and preserves no particular order.
    """
    canonical = {_canonical(n) for n in names if n and n.strip()}
    if not canonical:
        return []

    existing = db.query(Skill).filter(Skill.name.in_(canonical)).all()
    found = {s.name for s in existing}

    created = []
    for name in canonical - found:
        skill = Skill(name=name)
        db.add(skill)
        created.append(skill)
    if created:
        db.flush()  # assign ids before callers link join rows
    return existing + created
