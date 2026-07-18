"""Identity tables. [OPUS]

One `users` table holds auth state for all roles (keeps auth uniform and lets an
admin be added later without a migration). Role-specific data lives in 1:1 child
tables (student_profiles, companies).

`pending_email` is the key to the email-change edge case (tricky part #1): the
current email stays verified and usable while a new one is being verified, so a
user is never locked out.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Enum, ForeignKey, Numeric, func
)
from sqlalchemy.orm import relationship

from app.db.base import Base
from .enums import Role


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(Role), nullable=False, index=True)

    is_email_verified = Column(Boolean, nullable=False, default=False)
    # New email awaiting verification; current `email` remains authoritative until confirmed.
    pending_email = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    student_profile = relationship("StudentProfile", back_populates="user", uselist=False,
                                   cascade="all, delete-orphan")
    company = relationship("Company", back_populates="user", uselist=False,
                           cascade="all, delete-orphan")


class Company(Base):
    __tablename__ = "companies"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    company_name = Column(String(255), nullable=False)
    # Listings can only go Active once the company is approved by an admin.
    # One company is seeded pre-approved for the demo.
    is_approved = Column(Boolean, nullable=False, default=False)

    user = relationship("User", back_populates="company")
    listings = relationship("Listing", back_populates="company")
