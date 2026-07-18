"""Bonus B — cap-race proof.

Fires 5 SIMULTANEOUS applies (thread barrier) at the seeded 1-slot listing and
asserts exactly one 201, four clean 409s, zero 500s — no double-accept.

Run against a live server with seeded data:

    uvicorn app.main:app          # terminal 1
    python tests/test_cap_race.py # terminal 2

Why it holds: services/apply.py locks the listing row (SELECT ... FOR UPDATE),
so the five transactions serialize at the cap check; the DB unique constraint
backstops duplicates. See docs/DESIGN_DECISIONS.md.

IMPORTANT — run the server on PostgreSQL for this test. SQLite ignores
FOR UPDATE (no row locks): against the SQLite fallback this script correctly
DETECTS the race (5×201 — we verified this), proving both that the test is
sensitive and that the guarantee genuinely comes from Postgres row locking,
not from luck.
"""
from __future__ import annotations

import sys
import threading

import httpx

BASE = "http://localhost:8000"
PASSWORD = "Password123"
N = 5


def make_verified_student(i: int) -> str:
    """Register + OTP-verify a fresh student via the real API; return a token."""
    email = f"racer{i}@bmsce.ac.in"
    r = httpx.post(f"{BASE}/auth/register/student",
                   json={"email": email, "password": PASSWORD})
    if r.status_code == 409:  # rerun: student already exists
        pass
    else:
        data = r.json()["data"]
        httpx.post(f"{BASE}/auth/verify-otp",
                   json={"user_id": data["user_id"], "code": data["otp_for_demo"]})
    r = httpx.post(f"{BASE}/auth/login", json={"email": email, "password": PASSWORD})
    return r.json()["data"]["access_token"]


def find_one_slot_listing(token: str) -> int:
    r = httpx.get(f"{BASE}/listings", headers={"Authorization": f"Bearer {token}"},
                  params={"page_size": 100})
    for listing in r.json()["data"]:
        if "cap-race" in listing["title"]:
            return listing["id"]
    sys.exit("Seeded cap-race listing not found — run `python seed.py` on a fresh DB first.")


def main() -> None:
    print(f"Preparing {N} verified students...")
    tokens = [make_verified_student(i) for i in range(N)]
    listing_id = find_one_slot_listing(tokens[0])
    print(f"Target: listing {listing_id} (1 slot). Firing {N} simultaneous applies...\n")

    barrier = threading.Barrier(N)
    results: list = [None] * N

    def fire(idx: int) -> None:
        client = httpx.Client(timeout=30)
        barrier.wait()  # all threads release at the same instant
        r = client.post(f"{BASE}/listings/{listing_id}/apply",
                        headers={"Authorization": f"Bearer {tokens[idx]}"})
        results[idx] = (r.status_code, r.json().get("error") or r.json().get("data"))

    threads = [threading.Thread(target=fire, args=(i,)) for i in range(N)]
    for t in threads: t.start()
    for t in threads: t.join()

    codes = [c for c, _ in results]
    for i, (code, detail) in enumerate(results):
        print(f"  student {i}: HTTP {code}  {detail}")

    ok_201 = codes.count(201)
    ok_409 = codes.count(409)
    crashes = sum(1 for c in codes if c >= 500)
    print(f"\n201s: {ok_201}   409s: {ok_409}   5xx: {crashes}")

    assert ok_201 == 1, f"expected exactly 1 acceptance, got {ok_201}"
    assert ok_409 == N - 1, f"expected {N-1} clean rejections, got {ok_409}"
    assert crashes == 0, "server crashed under race"
    print("CAP RACE TEST PASSED — exactly one winner, four clean rejections, no 500s.")


if __name__ == "__main__":
    main()
