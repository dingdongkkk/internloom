"""Engine + session dependency. [OPUS]"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Session:
    """FastAPI dependency. Commit/rollback handled by the caller/service layer."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
