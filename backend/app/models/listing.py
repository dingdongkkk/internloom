"""Job listing. [OPUS]

`applicant_count` is denormalized on purpose: the cap check and auto-close must be
atomic under concurrency, so we lock THIS row (SELECT ... FOR UPDATE) and read the
count from it rather than racing a COUNT(*) query. See services/apply.py.

`closed_reason` is what reconciles the "no re-entry" rule with the withdrawal
reopen: a `manual` close is a company decision and stays closed; a `cap_reached`
close is a pure function of applicant_count and reopens when count drops.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Enum, ForeignKey, Numeric, func, CheckConstraint, Index
)
from sqlalchemy.orm import relationship

from app.db.base import Base
from .enums import ListingStatus, ClosedReason, LocationType


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (
        CheckConstraint("max_applicants > 0", name="ck_listing_cap_positive"),
        Index("ix_listings_status_created", "status", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.user_id", ondelete="CASCADE"),
                        nullable=False, index=True)

    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    stipend = Column(Numeric(10, 2), nullable=True)
    location = Column(Enum(LocationType), nullable=False, default=LocationType.remote)
    deadline = Column(DateTime(timezone=True), nullable=True)
    target_branch = Column(String(100), nullable=True, index=True)
    target_graduation_year = Column(Integer, nullable=True, index=True)
    max_applicants = Column(Integer, nullable=False)

    applicant_count = Column(Integer, nullable=False, default=0)   # active (non-withdrawn) apps
    status = Column(Enum(ListingStatus), nullable=False, default=ListingStatus.draft, index=True)
    closed_reason = Column(Enum(ClosedReason), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company", back_populates="listings")
    skills = relationship("ListingSkill", cascade="all, delete-orphan")
    applications = relationship("Application", back_populates="listing")
