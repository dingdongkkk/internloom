"""Normalized, queryable skills. [OPUS]

Skills are first-class rows, never a comma-separated blob. A company filtering
for 'React.js' joins on skill_id and gets exact matches — no substring hits
inside a text field. This is what makes the matching engine O(k) set math instead
of string scanning.
"""
from sqlalchemy import Column, Integer, String, ForeignKey, Enum, UniqueConstraint, Index
from sqlalchemy.orm import relationship

from app.db.base import Base
from .enums import SkillKind


class Skill(Base):
    __tablename__ = "skills"

    id = Column(Integer, primary_key=True)
    # Canonical, case-folded name. Aliases (react/react.js) should be resolved on
    # write by the profile/listing service so the same concept maps to one row.
    name = Column(String(100), unique=True, nullable=False, index=True)


class StudentSkill(Base):
    __tablename__ = "student_skills"

    student_id = Column(Integer, ForeignKey("student_profiles.user_id", ondelete="CASCADE"),
                        primary_key=True)
    skill_id = Column(Integer, ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True)

    skill = relationship("Skill")


class ListingSkill(Base):
    __tablename__ = "listing_skills"
    __table_args__ = (
        UniqueConstraint("listing_id", "skill_id", "kind", name="uq_listing_skill_kind"),
        Index("ix_listing_skills_listing", "listing_id"),
    )

    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    skill_id = Column(Integer, ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    kind = Column(Enum(SkillKind), nullable=False)  # required vs preferred (weighted differently)

    skill = relationship("Skill")
