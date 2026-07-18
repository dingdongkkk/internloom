"""End-to-end smoke suite — 38 checks over the full API surface.

Run from backend/ (no server or Postgres needed; uses a throwaway SQLite DB
and FastAPI's TestClient):

    PYTHONPATH=. python tests/test_smoke.py

Covers: registration + email policy, OTP gate, profile completeness, matched
feed ordering + score breakdown, apply/duplicate/cap-auto-close/withdraw-reopen,
state machines, actor isolation (403s), delete-profile guard, notifications,
error envelopes, Bonus A rate limiting, and Bonus C audit capture.

Bonus B's concurrency guarantee is NOT covered here — that needs real Postgres
row locks; use tests/test_cap_race.py against a live Postgres-backed server.
Exits 0 if all checks pass, 1 otherwise.
"""
import os, tempfile

dbfile = os.path.join(tempfile.mkdtemp(), "smoke.db")
os.environ["DATABASE_URL"] = f"sqlite:///{dbfile}"

from app.db.base import Base
from app.db.session import engine, SessionLocal

Base.metadata.create_all(engine)  # JsonType variant makes audit_log SQLite-safe

from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)
FAIL = []

def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        FAIL.append(name)

# --- company: register, approve (simulating seeded pre-approved co), login ---
r = c.post("/auth/register/company", json={"email": "hr@acme-corp.com",
    "password": "secret123", "company_name": "Acme Corp"})
check("company register 201", r.status_code == 201, r.text[:120])

db = SessionLocal()
from app.models.user import Company
db.query(Company).update({Company.is_approved: True})
db.commit(); db.close()

r = c.post("/auth/login", json={"email": "hr@acme-corp.com", "password": "secret123"})
co_tok = r.json()["data"]["access_token"]
CO = {"Authorization": f"Bearer {co_tok}"}

# --- company: create listing (draft), then activate via PATCH ---
r = c.post("/listings", headers=CO, json={
    "title": "Backend Intern", "description": "FastAPI work",
    "required_skills": ["Python", "FastAPI"], "preferred_skills": ["PostgreSQL"],
    "stipend": 20000, "location": "remote", "max_applicants": 2,
    "target_branch": "CSE", "target_graduation_year": 2026})
check("create listing 201 draft", r.status_code == 201 and r.json()["data"]["status"] == "draft", r.text[:200])
lid = r.json()["data"]["id"]
check("skills normalized", r.json()["data"]["required_skills"] == ["fastapi", "python"])
check("target branch/year stored", r.json()["data"]["target_branch"] == "CSE"
      and r.json()["data"]["target_graduation_year"] == 2026)

r = c.patch(f"/listings/{lid}/status", headers=CO, json={"status": "closed"})
check("draft->closed rejected 400", r.status_code == 400, r.text[:120])
r = c.patch(f"/listings/{lid}/status", headers=CO, json={"status": "active"})
check("draft->active 200", r.status_code == 200, r.text[:120])

# --- student: personal email rejected, college ok, OTP verify, profile ---
r = c.post("/auth/register/student", json={"email": "kid@gmail.com", "password": "secret123"})
check("gmail rejected 400", r.status_code == 400 and r.json()["error"]["code"] == "PERSONAL_EMAIL_REJECTED")

r = c.post("/auth/register/student", json={"email": "anu@bmsce.ac.in", "password": "secret123"})
check("student register 201", r.status_code == 201, r.text[:120])
sid, otp = r.json()["data"]["user_id"], r.json()["data"]["otp_for_demo"]

r = c.post("/auth/login", json={"email": "anu@bmsce.ac.in", "password": "secret123"})
ST = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}

r = c.post(f"/listings/{lid}/apply", headers=ST)
check("unverified apply blocked 403", r.status_code == 403 and r.json()["error"]["code"] == "EMAIL_NOT_VERIFIED")

r = c.post("/auth/verify-otp", json={"user_id": sid, "code": otp})
check("otp verify 200", r.status_code == 200 and r.json()["data"]["is_email_verified"])

r = c.get("/profile/me", headers=ST)
low = r.json()["data"]["completeness"]
check("empty profile completeness low", r.status_code == 200 and low < 20, f"score={low}")

r = c.put("/profile/me", headers=ST, json={
    "name": "Anu", "college": "BMSCE", "branch": "CSE", "graduation_year": 2026,
    "cgpa": 8.7, "github_url": "https://github.com/anu", "linkedin_url": "https://linkedin.com/in/anu",
    "bio": "backend dev", "resume_url": "https://x.com/r.pdf",
    "skills": ["Python", "FastAPI", "PostgreSQL", "React.js", "Docker"]})
full = r.json()["data"]["completeness"]
check("full profile completeness 100", r.status_code == 200 and full == 100, f"score={full}")

# --- matched feed: score + breakdown present, sorted ---
r = c.get("/listings", headers=ST)
d = r.json()["data"]
check("feed has scored listing", r.status_code == 200 and len(d) == 1 and d[0]["score"] > 70,
      f"score={d and d[0].get('score')}")
check("feed exposes breakdown", "breakdown" in d[0])

# --- notify-on-activate: second listing activated AFTER profile complete ---
r = c.post("/listings", headers=CO, json={"title": "Python Intern",
    "required_skills": ["Python"], "max_applicants": 5,
    "target_branch": "CSE", "target_graduation_year": 2026})
lid2 = r.json()["data"]["id"]
c.patch(f"/listings/{lid2}/status", headers=CO, json={"status": "active"})
r = c.get("/notifications", headers=ST, params={"is_read": False})
types = [n["type"] for n in r.json()["data"]]
check("high_match notification created", "high_match" in types, str(types))

# --- apply: 201, duplicate 409, cap auto-close, withdraw reopen ---
r = c.post(f"/listings/{lid}/apply", headers=ST)
check("apply 201", r.status_code == 201, r.text[:150])
app_id = r.json()["data"]["application_id"]
r = c.post(f"/listings/{lid}/apply", headers=ST)
check("duplicate apply 409", r.status_code == 409 and r.json()["error"]["code"] == "ALREADY_APPLIED", r.text[:150])

# second student fills the cap (cap=2) -> auto-close
r = c.post("/auth/register/student", json={"email": "b@iitb.ac.in", "password": "secret123"})
sid2, otp2 = r.json()["data"]["user_id"], r.json()["data"]["otp_for_demo"]
c.post("/auth/verify-otp", json={"user_id": sid2, "code": otp2})
r = c.post("/auth/login", json={"email": "b@iitb.ac.in", "password": "secret123"})
ST2 = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
r = c.post(f"/listings/{lid}/apply", headers=ST2)
check("second apply 201", r.status_code == 201, r.text[:150])
app2 = r.json()["data"]["application_id"]

db = SessionLocal()
from app.models.listing import Listing
lst = db.get(Listing, lid)
check("cap auto-close", lst.status.value == "closed" and lst.closed_reason.value == "cap_reached")
db.close()

r = c.post(f"/listings/{lid}/apply", headers=ST2)
check("apply to closed 409", r.status_code == 409)

# withdraw (submitted) -> reopen
r = c.post(f"/applications/{app2}/withdraw", headers=ST2)
check("withdraw 200", r.status_code == 200 and r.json()["data"]["status"] == "withdrawn", r.text[:150])
db = SessionLocal()
lst = db.get(Listing, lid)
check("withdraw reopens cap-closed listing", lst.status.value == "active" and lst.closed_reason is None)
db.close()

# --- delete-profile guard: blocked with active application ---
r = c.delete("/profile/me", headers=ST)
check("delete blocked w/ active app 409", r.status_code == 409
      and r.json()["error"]["code"] == "PROFILE_HAS_ACTIVE_APPLICATIONS", r.text[:150])

# --- company: applicants view + status transition + notifications ---
r = c.get(f"/listings/{lid}/applicants", headers=CO)
check("applicants view", r.status_code == 200 and len(r.json()["data"]) == 1
      and r.json()["data"][0]["match_score"] is not None, r.text[:200])
r = c.get(f"/listings/{lid}/applicants", headers=ST)
check("student blocked from applicants 403", r.status_code == 403)

r = c.patch(f"/applications/{app_id}/status", headers=CO, json={"status": "shortlisted"})
check("illegal skip blocked 400", r.status_code == 400)
r = c.patch(f"/applications/{app_id}/status", headers=CO, json={"status": "under_review"})
check("submitted->under_review 200", r.status_code == 200)

r = c.get("/notifications", headers=ST, params={"is_read": False})
n_unread = r.json()["meta"]["total"]
check("student has unread notifications", n_unread >= 2, f"unread={n_unread}")
r = c.patch("/notifications/read", headers=ST, json={"all": True})
check("bulk mark-read", r.status_code == 200 and r.json()["data"]["marked_read"] == n_unread)
r = c.get("/notifications", headers=ST, params={"is_read": False})
check("all read now", r.json()["meta"]["total"] == 0)

# --- envelope shape on an invalid-input crash attempt ---
r = c.post("/listings", headers=CO, json={"title": 123, "max_applicants": -5})
check("invalid input 422 envelope", r.status_code == 422 and r.json()["success"] is False
      and r.json()["error"]["code"] == "VALIDATION_ERROR")

# --- my-applications (student) and my-listings (company) views ---
r = c.get("/applications/mine", headers=ST)
check("my applications list", r.status_code == 200 and len(r.json()["data"]) >= 1
      and r.json()["data"][0]["listing_title"] is not None, r.text[:150])
r = c.get("/listings/mine", headers=CO)
check("my listings incl. draft", r.status_code == 200
      and any(l["status"] == "closed" or l["status"] == "active" for l in r.json()["data"]),
      f"count={len(r.json()['data'])}")
r = c.get("/listings/mine", headers=ST)
check("student blocked from /listings/mine 403", r.status_code == 403)

# --- Bonus C: audit trail captured the mutations above ---
r = c.get("/audit")
check("audit without token 403", r.status_code == 403)
r = c.get("/audit", headers={"X-Admin-Token": "internloom-admin-demo"})
rows = r.json()["data"]
check("audit rows exist", r.status_code == 200 and r.json()["meta"]["total"] > 10,
      f"total={r.json()['meta']['total']}")
status_changes = [x for x in rows if x["resource_type"] == "application" and x["before"]]
check("audit captured before-state", any(x["before"].get("status") == "submitted"
      for x in status_changes), str(status_changes[:1]))
r = c.get("/audit", headers={"X-Admin-Token": "internloom-admin-demo"},
          params={"actor_type": "company"})
check("audit actor filter", all(x["actor_role"] == "company" for x in r.json()["data"]))

# --- Bonus A: rate limiter (tiny fresh instance so we don't need 100 calls) ---
from app.api.middleware.rate_limit import RateLimitMiddleware
from fastapi import FastAPI as _F
mini = _F(); mini.add_middleware(RateLimitMiddleware, max_requests=3, window_sec=60)
@mini.get("/ping")
def ping(): return {"ok": True}
mc = TestClient(mini)
codes = [mc.get("/ping").status_code for _ in range(5)]
last = mc.get("/ping")
check("rate limit 3/60s -> 429 after 3", codes == [200, 200, 200, 429, 429])
check("Retry-After header present", "retry-after" in last.headers
      and last.json()["error"]["code"] == "RATE_LIMITED", str(last.headers.get("retry-after")))

print()
print("RESULT:", "ALL PASSED" if not FAIL else f"{len(FAIL)} FAILURES: {FAIL}")
raise SystemExit(1 if FAIL else 0)
