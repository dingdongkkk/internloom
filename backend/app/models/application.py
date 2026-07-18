"""Application. [OPUS]

Unique(listing_id, student_id) enforces "apply once per role" at the DB level —
the API returns a clean 409, but even a race can't create a duplicate.

`match_score_snapshot` freezes the score at apply time. This is the documented
answer to tricky part #3: the company's applicant list shows the score as it was
when the student applied (stable, audit-consistent), while students always see a
live score recomputed at query time. Editing a listing's skills therefore never
silently rewrites historical applicant scores.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, DateTime, Enum, ForeignKey, Numeric, UniqueConstraint, func, Index
)
from sqlalchemy.orm import relationship

from app.db.base import Base
from .enums import ApplicationStatus


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("listing_id", "student_id", name="uq_one_application_per_role"),
        Index("ix_applications_listing_status", "listing_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(Integer, ForeignKey("student_profiles.user_id", ondelete="CASCADE"),
                        nullable=False, index=True)

    status = Column(Enum(ApplicationStatus), nullable=False, default=ApplicationStatus.submitted)
    match_score_snapshot = Column(Numeric(5, 2), nullable=True)  # score at apply time

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    listing = relationship("Listing", back_populates="applications")
    student = relationship("StudentProfile", back_populates="applications")
