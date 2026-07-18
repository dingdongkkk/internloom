"""In-app notification log."""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, func, Index
from app.db.base import Base


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "is_read"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(50), nullable=False)          # e.g. application_status, high_match, new_applicant
    message = Column(Text, nullable=False)
    resource_type = Column(String(50), nullable=True)  # e.g. listing, application
    resource_id = Column(Integer, nullable=True)
    is_read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class EmailVerification(Base):
    """OTP records. Supports both signup verification and email-change re-verification."""
    __tablename__ = "email_verifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), nullable=False)     # the address this OTP verifies
    otp_code = Column(String(6), nullable=False)
    purpose = Column(String(20), nullable=False)    # OtpPurpose value
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
