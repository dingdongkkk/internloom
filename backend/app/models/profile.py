"""Student profile. [OPUS]

A structured, queryable document — not just a row. Completeness score is computed
on read (services/completeness.py), never stored.
"""
from sqlalchemy import Column, Integer, String, ForeignKey, Numeric, Text
from sqlalchemy.orm import relationship

from app.db.base import Base


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)

    name = Column(String(150), nullable=True)
    college = Column(String(200), nullable=True)
    branch = Column(String(100), nullable=True, index=True)       # e.g. CSE, ECE
    graduation_year = Column(Integer, nullable=True, index=True)
    cgpa = Column(Numeric(4, 2), nullable=True)                   # 0.00 - 10.00
    github_url = Column(String(300), nullable=True)
    linkedin_url = Column(String(300), nullable=True)
    bio = Column(Text, nullable=True)
    resume_url = Column(String(300), nullable=True)

    user = relationship("User", back_populates="student_profile")
    skills = relationship("StudentSkill", cascade="all, delete-orphan")
    applications = relationship("Application", back_populates="student")
