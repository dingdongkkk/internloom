"""Password hashing, OTP generation, email policy. [OPUS]"""
from __future__ import annotations

import re
import secrets
import bcrypt

from .config import settings


# --- Passwords (bcrypt — plaintext = instant disqualification) ---
def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(settings.BCRYPT_ROUNDS)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


# --- OTP ---
def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


# --- Email policy ---
_EMAIL_RE = re.compile(r"^[^@\s]+@([^@\s]+\.[^@\s]+)$")


def parse_domain(email: str) -> str | None:
    m = _EMAIL_RE.match(email.strip().lower())
    return m.group(1) if m else None


def validate_student_email(email: str) -> None:
    """Raise a clear ApiError if this is not an acceptable college email."""
    from .exceptions import bad_request

    domain = parse_domain(email)
    if not domain:
        raise bad_request("INVALID_EMAIL", "Email address is malformed")
    if domain in settings.BLOCKED_STUDENT_DOMAINS:
        raise bad_request(
            "PERSONAL_EMAIL_REJECTED",
            "Students must register with a college email, not a personal one",
            {"domain": domain},
        )
    if not any(domain.endswith(sfx) or ("." + domain).endswith(sfx)
               for sfx in settings.COLLEGE_EMAIL_SUFFIXES):
        raise bad_request(
            "NOT_A_COLLEGE_EMAIL",
            "Email domain is not recognised as a college domain",
            {"domain": domain, "allowed_suffixes": settings.COLLEGE_EMAIL_SUFFIXES},
        )
