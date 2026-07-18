"""Enum types shared across models. [OPUS]"""
import enum


class Role(str, enum.Enum):
    student = "student"
    company = "company"
    admin = "admin"


class ListingStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    closed = "closed"


class ClosedReason(str, enum.Enum):
    manual = "manual"          # company closed it — NOT reversible
    cap_reached = "cap_reached"  # system auto-close — reversible on withdrawal


class LocationType(str, enum.Enum):
    remote = "remote"
    hybrid = "hybrid"
    onsite = "onsite"


class SkillKind(str, enum.Enum):
    required = "required"
    preferred = "preferred"


class ApplicationStatus(str, enum.Enum):
    submitted = "submitted"
    under_review = "under_review"
    shortlisted = "shortlisted"
    rejected = "rejected"
    offer_extended = "offer_extended"
    withdrawn = "withdrawn"      # student-initiated terminal state


class OtpPurpose(str, enum.Enum):
    verify_signup = "verify_signup"
    email_change = "email_change"
