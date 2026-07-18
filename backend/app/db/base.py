"""Declarative base + import surface for Alembic autogenerate. [OPUS]

Alembic's env.py imports Base from here so `--autogenerate` sees every table.
"""
from sqlalchemy.orm import declarative_base

Base = declarative_base()

# Import all models so they register on Base.metadata (order matters for FKs at
# create_all time; Alembic handles ordering itself).
from app.models import user, skill, profile, listing, application, notification, audit  # noqa: E402,F401
