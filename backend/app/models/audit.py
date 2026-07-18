"""Audit log (Bonus C).

Every mutation records who did what to which resource, with before/after JSON.
Designed so admin can be added later without a schema change.
"""
from sqlalchemy import Column, Integer, String, DateTime, func, Index, JSON
from sqlalchemy.dialects.postgresql import JSONB
from app.db.base import Base

# JSONB on Postgres, generic JSON elsewhere (keeps local/test runs portable).
JsonType = JSON().with_variant(JSONB(), "postgresql")


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_actor", "actor_role", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    actor_user_id = Column(Integer, nullable=True)   # nullable: system/anonymous actions
    actor_role = Column(String(20), nullable=True)
    action = Column(String(20), nullable=False)      # POST/PUT/PATCH/DELETE
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(Integer, nullable=True)
    before = Column(JsonType, nullable=True)
    after = Column(JsonType, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
