"""Seed script.

Populates a fresh, migrated DB with demo data. Run AFTER `alembic upgrade head`:

    python seed.py

Goes through the real service layer (register_student / register_company /
verify_otp / profile PUT-equivalent) so hashing, validation and skill
normalization exactly match production paths.

Demo credentials (all passwords: Password123):
  COMPANY (pre-approved): hr@technova.com          <- required by spec: admin is
  COMPANY (pending):      talent@quantumsoft.com      out of scope, so one company
  STUDENT (verified):     priya@bmsce.ac.in           is seeded already approved.
  STUDENT (verified):     rahul@iitb.ac.in
  STUDENT (unverified):   arjun@nitk.edu.in
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db.session import SessionLocal
from app.models.user import Company
from app.models.profile import StudentProfile
from app.models.skill import StudentSkill, ListingSkill
from app.models.listing import Listing
from app.models.enums import ListingStatus, LocationType, SkillKind
from app.services import auth as auth_service
from app.services.skills import get_or_create_skills
from app.services.apply import apply_to_listing

PASSWORD = "Password123"
NOW = datetime.now(timezone.utc)


def seed_students(db) -> dict:
    students = {}
    for email, profile_data, skills, verify in [
        ("priya@bmsce.ac.in", dict(
            name="Priya Sharma", college="BMS College of Engineering", branch="CSE",
            graduation_year=2026, cgpa=8.9, github_url="https://github.com/priyasharma",
            linkedin_url="https://linkedin.com/in/priyasharma", bio="Backend developer, loves APIs",
            resume_url="https://example.com/priya.pdf"),
         ["Python", "FastAPI", "PostgreSQL", "React.js", "Docker"], True),
        ("rahul@iitb.ac.in", dict(
            name="Rahul Verma", college="IIT Bombay", branch="ECE",
            graduation_year=2027, cgpa=7.8, github_url="https://github.com/rahulv"),
         ["Python", "C++"], True),                      # ~40% complete on purpose
        ("arjun@nitk.edu.in", dict(name="Arjun Rao"), ["JavaScript"], False),  # unverified
    ]:
        res = auth_service.register_student(db, email=email, password=PASSWORD)
        uid = res["user_id"]
        if verify:
            auth_service.verify_otp(db, user_id=uid, code=res["otp_for_demo"])
        profile = db.get(StudentProfile, uid)
        for k, v in profile_data.items():
            setattr(profile, k, v)
        for skill in get_or_create_skills(db, skills):
            db.add(StudentSkill(student_id=uid, skill_id=skill.id))
        db.commit()
        students[email] = uid
        print(f"  student {email} (id={uid}, verified={verify})")
    return students


def seed_companies(db) -> dict:
    companies = {}
    for email, name, approved in [
        ("hr@technova.com", "TechNova Labs", True),      # THE pre-approved company
        ("talent@quantumsoft.com", "QuantumSoft", False),
    ]:
        res = auth_service.register_company(db, email=email, password=PASSWORD, company_name=name)
        uid = res["user_id"]
        if approved:
            db.get(Company, uid).is_approved = True
            db.commit()
        companies[email] = uid
        print(f"  company {name} (id={uid}, approved={approved})")
    return companies


def _listing(db, company_id, *, title, description, required, preferred, stipend,
             location, deadline_days, cap, status, age_days,
             target_branch=None, target_graduation_year=None) -> Listing:
    listing = Listing(
        company_id=company_id, title=title, description=description, stipend=stipend,
        location=location, max_applicants=cap, status=status,
        deadline=NOW + timedelta(days=deadline_days) if deadline_days is not None else None,
        target_branch=target_branch, target_graduation_year=target_graduation_year,
    )
    db.add(listing)
    db.flush()
    for names, kind in ((required, SkillKind.required), (preferred, SkillKind.preferred)):
        for skill in get_or_create_skills(db, names):
            db.add(ListingSkill(listing_id=listing.id, skill_id=skill.id, kind=kind))
    db.commit()
    # Backdate created_at so the recency signal is visible in match scores.
    db.execute(text("UPDATE listings SET created_at = :ts WHERE id = :id"),
               {"ts": NOW - timedelta(days=age_days), "id": listing.id})
    db.commit()
    print(f"  listing '{title}' (id={listing.id}, status={status.value}, age={age_days}d)")
    return listing


def seed_listings(db, companies) -> dict:
    tn = companies["hr@technova.com"]
    listings = {}
    listings["backend"] = _listing(
        db, tn, title="Backend Engineering Intern",
        description="Build REST APIs with FastAPI and PostgreSQL.",
        required=["Python", "FastAPI"], preferred=["PostgreSQL", "Docker"],
        stipend=25000, location=LocationType.remote, deadline_days=14, cap=10,
        status=ListingStatus.active, age_days=2,
        target_branch="CSE", target_graduation_year=2026)  # fresh -> high recency
    listings["fullstack"] = _listing(
        db, tn, title="Full-Stack Intern",
        description="React frontend + Python services.",
        required=["React.js", "Python"], preferred=["FastAPI"],
        stipend=20000, location=LocationType.hybrid, deadline_days=10, cap=5,
        status=ListingStatus.active, age_days=28,
        target_branch="CSE", target_graduation_year=2026)  # old -> low recency
    listings["embedded"] = _listing(
        db, tn, title="Embedded Systems Intern",
        description="Firmware in C++ for IoT devices.",
        required=["C++"], preferred=["Python"],
        stipend=18000, location=LocationType.onsite, deadline_days=21, cap=3,
        status=ListingStatus.active, age_days=5,
        target_branch="ECE", target_graduation_year=2027)
    listings["draft"] = _listing(
        db, tn, title="Data Engineering Intern (unpublished)",
        description="Draft — not visible to students yet.",
        required=["Python", "PostgreSQL"], preferred=[],
        stipend=22000, location=LocationType.remote, deadline_days=30, cap=5,
        status=ListingStatus.draft, age_days=0,
        target_branch="CSE", target_graduation_year=2026)
    listings["tight"] = _listing(
        db, tn, title="DevOps Intern (1 slot — cap-race demo)",
        description="Use this one for the Bonus B concurrency test.",
        required=["Docker"], preferred=["Python"],
        stipend=15000, location=LocationType.remote, deadline_days=7, cap=1,
        status=ListingStatus.active, age_days=1,
        target_branch="CSE", target_graduation_year=2026)
    return listings


def _apply_with_score(db, student_id: int, listing) -> None:
    """Apply through the real service, with a real apply-time snapshot score."""
    from app.api.routers.listings import _load_student_context, score_for_student
    profile, skill_ids, completeness = _load_student_context(db, student_id)
    score = score_for_student(listing, profile, skill_ids, completeness).score
    application = apply_to_listing(db, student_id=student_id,
                                   listing_id=listing.id, match_score=round(score, 2))
    print(f"  application id={application.id} student={student_id} "
          f"-> '{listing.title}' (score={score:.1f})")


def seed_applications(db, students, listings) -> None:
    # Priya applies to two listings so the applicants view has data.
    for key in ("backend", "fullstack"):
        _apply_with_score(db, students["priya@bmsce.ac.in"], listings[key])
    _apply_with_score(db, students["rahul@iitb.ac.in"], listings["embedded"])


def main() -> None:
    db = SessionLocal()
    try:
        if db.query(Company).count():
            raise SystemExit("DB already seeded — start from a fresh `alembic upgrade head`.")
        print("Seeding students...");  students = seed_students(db)
        print("Seeding companies..."); companies = seed_companies(db)
        print("Seeding listings...");  listings = seed_listings(db, companies)
        print("Seeding applications..."); seed_applications(db, students, listings)
        print("\nDone. Demo login (password for all): Password123")
        print("  pre-approved company: hr@technova.com")
        print("  verified student:     priya@bmsce.ac.in")
    finally:
        db.close()


if __name__ == "__main__":
    main()
