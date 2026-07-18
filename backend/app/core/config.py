"""Application settings. [OPUS]

Central config so nothing downstream hardcodes secrets or TTLs.
"""
from functools import lru_cache
from typing import List
import os


class Settings:
    # --- Security ---
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-only-change-me")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MIN: int = 60          # spec: 1 hour
    REFRESH_TOKEN_TTL_DAYS: int = 7
    OTP_TTL_MIN: int = 10
    BCRYPT_ROUNDS: int = 12

    # --- Database ---
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg2://internloom:internloom@localhost:5432/internloom"
    )

    # --- Email policy ---
    # Domains explicitly allowed for STUDENT registration.
    COLLEGE_EMAIL_SUFFIXES: List[str] = [".edu", ".ac.in", ".edu.in", ".ernet.in"]
    # Personal domains rejected for students at the API layer.
    BLOCKED_STUDENT_DOMAINS: List[str] = [
        "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "proton.me",
    ]

    # --- Matching weights (must sum to 1.0). See services/matching.py ---
    W_REQUIRED = 0.45
    W_PREFERRED = 0.15
    W_BRANCH_YEAR = 0.20
    W_COMPLETENESS = 0.12
    W_RECENCY = 0.08

    # --- Rate limit (Bonus A) ---
    RATE_LIMIT_MAX = 100
    RATE_LIMIT_WINDOW_SEC = 15 * 60


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
