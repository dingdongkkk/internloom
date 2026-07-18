# InternLoom API — Shared Contract

> This is the single source of truth. Opus wrote the hard logic against this contract.
> The implementation fills in the boilerplate against this **same** contract. Do not diverge from it.

## 1. Response envelope (every endpoint, no exceptions)

Success:
```json
{ "success": true, "data": <object|array>, "error": null, "meta": { ... } }
```
Error:
```json
{ "success": false, "data": null, "error": { "code": "STRING_CODE", "message": "human readable", "details": {...} } }
```
`meta` carries pagination (`page`, `page_size`, `total`, `total_pages`) and anything non-payload.
Helpers live in `app/core/envelope.py`. **Never return raw dicts from a route.**

## 2. Actors & roles

`role ∈ {student, company, admin}`. Admin endpoints are out of scope but the schema supports
them (audit, cross-tenant reads). Every protected route resolves the caller via
`Depends(get_current_user)` and asserts role with `require_role(...)` — see `app/core/deps.py`.

## 3. Auth model

- Self-implemented JWT. Access token TTL **1h**, refresh token TTL **7d**.
- `POST /auth/refresh` mints a new access token from a valid refresh token (rotation supported).
- Students register with a **college email** (allowlist of TLDs/domains, personal domains blocked).
- Students get an **OTP** to verify email. Unverified → may log in, **may not apply**.
- Companies: no OTP; listings start `draft`/`pending` until admin approves. One company is
  **pre-approved via seed** for the demo.
- Passwords hashed with **bcrypt** (disqualification if plaintext).

## 4. Data model (see `app/models/`)

Normalized skills (NOT csv): `skills`, `student_skills`, `listing_skills` (required/preferred flag).
State columns are enums. `listings.closed_reason` distinguishes `manual` vs `cap_reached`
(this powers the withdrawal-reopen reconciliation). `audit_log` captures before/after JSON.

## 5. State machines

- **Listing:** `draft → active → closed`. No `closed → active` *manually*. No `draft → closed`.
  Auto-close on cap sets `closed_reason = cap_reached` (system state, reversible).
- **Application:** `submitted → under_review → shortlisted → (rejected | offer_extended)`.
  Company moves forward; student may **withdraw only from `submitted`**.

## 6. Endpoint list (✅ = implemented, 🔨 = remaining implementation)

| Method | Path | Implementation |
|---|---|---|
| POST | /auth/register/student | ✅ auth service done, router done |
| POST | /auth/register/company | ✅ |
| POST | /auth/login | ✅ |
| POST | /auth/verify-otp | ✅ |
| POST | /auth/request-email-change | ✅ (tricky-part #1) |
| POST | /auth/refresh | ✅ |
| GET  | /profile/me | ✅ computed completeness |
| PUT  | /profile/me | ✅ |
| DELETE | /profile/me | ✅ guarded by `assert_deletable` |
| GET  | /listings | ✅ student view: matching-sorted (Opus) |
| POST | /listings | ✅ CRUD (company) |
| PUT  | /listings/{id} | ✅ uses `listing_state.transition` |
| PATCH| /listings/{id}/status | ✅ transition logic (Opus) |
| GET  | /listings/{id}/applicants | ✅ authz + snapshot scores (Opus) |
| POST | /listings/{id}/apply | ✅ concurrency-safe (Opus, Bonus B) |
| POST | /applications/{id}/withdraw | ✅ reopen reconciliation (Opus) |
| PATCH| /applications/{id}/status | ✅ transition (Opus) |
| PATCH| /applications/bulk-status | ✅ bulk reject-older-than (Opus) |
| GET  | /applications/mine | ✅ student's own applications (spec 2.1) |
| GET  | /listings/mine | ✅ company's own listings, all statuses |
| GET  | /notifications | ✅ filter + paginate |
| PATCH| /notifications/read | ✅ single + bulk |
| GET  | /audit | ✅ Bonus C (admin, mock token) |

## 7. Pagination default

`page` (1-based, default 1), `page_size` (default 20, max 100). Enforce the cap — no unbounded queries.
