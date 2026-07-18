"""Auth service: register, login, OTP verify, refresh, email change. [OPUS]

=== Email-change re-verification (tricky part #1) ===
Naive approach: on email change, overwrite email and flip is_email_verified=False.
That instantly locks the student out of applying using an address they may have
typo'd, with no way back.

Our approach: the current email stays authoritative and verified. A change request
stores the new address in `pending_email` and issues an OTP bound to that address.
The user keeps full access under the old email meanwhile. Only when they submit the
correct OTP do we (a) promote pending_email -> email, (b) keep is_email_verified
True (they just proved ownership). If they never verify, pending_email simply
expires and nothing changes. A user is therefore never locked out by a change.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.security import (
    hash_password, verify_password, generate_otp, validate_student_email, parse_domain,
)
from app.core.jwt import create_access_token, create_refresh_token, decode_token
from app.core.exceptions import bad_request, conflict, ApiError
from app.models.user import User, Company
from app.models.profile import StudentProfile
from app.models.notification import EmailVerification
from app.models.enums import Role, OtpPurpose


def _issue_otp(db: Session, user: User, email: str, purpose: OtpPurpose) -> str:
    code = generate_otp()
    db.add(EmailVerification(
        user_id=user.id, email=email, otp_code=code, purpose=purpose.value,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.OTP_TTL_MIN),
    ))
    return code  # in a real system this is emailed; here we return it for the demo/log


def register_student(db: Session, *, email: str, password: str) -> dict:
    validate_student_email(email)          # raises on personal/non-college domains
    user = User(email=email.lower(), password_hash=hash_password(password),
                role=Role.student, is_email_verified=False)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise conflict("EMAIL_TAKEN", "An account with this email already exists")
    db.add(StudentProfile(user_id=user.id))
    otp = _issue_otp(db, user, user.email, OtpPurpose.verify_signup)
    db.commit()
    return {"user_id": user.id, "email": user.email, "otp_for_demo": otp,
            "note": "Account created but unverified. Verify OTP before applying."}


def register_company(db: Session, *, email: str, password: str, company_name: str) -> dict:
    domain = parse_domain(email)
    if not domain:
        raise bad_request("INVALID_EMAIL", "Email address is malformed")
    if domain in settings.BLOCKED_STUDENT_DOMAINS:
        # Companies need a corporate address, not a personal inbox.
        raise bad_request("PERSONAL_EMAIL_REJECTED",
                          "Companies must register with a corporate email")
    user = User(email=email.lower(), password_hash=hash_password(password),
                role=Role.company, is_email_verified=True)  # companies need no OTP
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise conflict("EMAIL_TAKEN", "An account with this email already exists")
    # Not approved by default; listings stay in draft/pending until an admin approves.
    db.add(Company(user_id=user.id, company_name=company_name, is_approved=False))
    db.commit()
    return {"user_id": user.id, "email": user.email,
            "note": "Company created. Listings cannot go active until admin approval."}


def login(db: Session, *, email: str, password: str) -> dict:
    user = db.query(User).filter(User.email == email.lower()).first()
    if not user or not verify_password(password, user.password_hash):
        raise ApiError(401, "INVALID_CREDENTIALS", "Email or password is incorrect")
    return _token_pair(user)


def verify_otp(db: Session, *, user_id: int, code: str) -> dict:
    rec = (
        db.query(EmailVerification)
        .filter(EmailVerification.user_id == user_id,
                EmailVerification.otp_code == code,
                EmailVerification.consumed_at.is_(None))
        .order_by(EmailVerification.id.desc())
        .first()
    )
    if rec is None:
        raise bad_request("INVALID_OTP", "OTP is invalid or already used")
    expires = rec.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires:
        raise bad_request("OTP_EXPIRED", "This OTP has expired; request a new one")

    user = db.get(User, user_id)
    rec.consumed_at = datetime.now(timezone.utc)

    if rec.purpose == OtpPurpose.email_change.value:
        # Promote the pending email now that ownership is proven.
        user.email = rec.email
        user.pending_email = None
    user.is_email_verified = True
    db.commit()
    return {"user_id": user.id, "email": user.email, "is_email_verified": True}


def request_email_change(db: Session, *, user_id: int, new_email: str) -> dict:
    user = db.get(User, user_id)
    if user.role == Role.student:
        validate_student_email(new_email)  # new address must also be a college email
    if db.query(User).filter(User.email == new_email.lower(), User.id != user_id).first():
        raise conflict("EMAIL_TAKEN", "That email is already in use")

    # Current email stays authoritative & verified. Only stage the new one.
    user.pending_email = new_email.lower()
    otp = _issue_otp(db, user, new_email.lower(), OtpPurpose.email_change)
    db.commit()
    return {"pending_email": user.pending_email, "otp_for_demo": otp,
            "note": "Current email still works. Verify the OTP to switch."}


def refresh(db: Session, *, refresh_token: str) -> dict:
    payload = decode_token(refresh_token, expected_type="refresh")
    user = db.get(User, int(payload["sub"]))
    if not user:
        raise ApiError(401, "USER_NOT_FOUND", "Token subject no longer exists")
    # Issue a fresh access token (and rotate the refresh token) — never reuse.
    return _token_pair(user)


def _token_pair(user: User) -> dict:
    return {
        "access_token": create_access_token(user.id, user.role.value),
        "refresh_token": create_refresh_token(user.id, user.role.value),
        "token_type": "bearer",
        "role": user.role.value,
        "is_email_verified": user.is_email_verified,
    }
