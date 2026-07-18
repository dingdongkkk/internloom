# Design Decisions

Answers to the three "Tricky Part" questions from Section 3. Judges read this before
the demo; the code matches these answers exactly.

## Tricky Part #1 — A verified student changes their email; how do you re-verify without locking them out?

We never overwrite a verified email on request. A change goes through a staging
field, `users.pending_email`, and issues a fresh OTP bound to the *new* address
(purpose = `email_change`). Throughout this window the **old** email stays the
account's authoritative, verified identity — the student keeps full access,
including applying to roles. Only when the correct OTP is submitted do we promote
`pending_email → email` and keep `is_email_verified = true` (ownership was just
proven). If the student mistyped the address or never verifies, `pending_email`
and its OTP simply expire and nothing about their account changes. So a change
*request* can never lock anyone out; verification is a promotion, not a downgrade.
For students, the new address must itself pass college-domain validation before we
even stage it. Implemented in `services/auth.py::request_email_change` / `verify_otp`.

## Tricky Part #3 — A company edits the required skills of an Active listing that already has 15 applicants. Do existing applicants' scores change? Does the company see stale data?

We split the score into two views with different guarantees. **Students** always
see a *live* score, recomputed at query time from the listing's current skills — so
after an edit, a student's ranking reflects the new requirements immediately; there
is no stale student-facing data. **Companies** see a *snapshot* score,
`applications.match_score_snapshot`, frozen at the moment the student applied. This
is deliberate: the applicant list is a hiring record, and silently rewriting the
15 existing applicants' scores when requirements change would be misleading and
non-auditable. So editing required skills changes future rankings and any new
applicant's snapshot, but never retroactively rewrites the score a company already
saw for a past applicant. If a company wants live re-scoring against the new
criteria, that's an explicit re-rank action, not a silent mutation. This keeps the
company view stable/auditable and the student view fresh.

## Tricky Part #4 — Withdrawal reopens an auto-closed listing, but you said Closed → Active is not allowed. How do you reconcile this?

The "no re-entry" rule applies to **manual** transitions only. We record *why* a
listing closed in `listings.closed_reason`:
- `manual` — a company chose to close it. This is a business decision and is
  **never** auto-reopened. `Closed(manual) → Active` is forbidden by the state
  machine (`services/listing_state.py`).
- `cap_reached` — the system auto-closed it because `applicant_count` hit the cap.
  This is not a decision; it's a *derived* state, a pure function of the count. When
  a `submitted` application is withdrawn, `applicant_count` decrements, and if the
  listing was closed *for this reason* and is now below cap, it reopens to `active`
  (`services/apply.py::withdraw_application`).

So there is no contradiction: manual closes are irreversible intent; cap closes are
reversible bookkeeping. The `closed_reason` column is exactly what lets one code
path tell them apart.

---

### Bonus B — how the cap race is made safe (referenced live)

`services/apply.py` locks the listing row with `SELECT ... FOR UPDATE`, turning
the check-count-then-insert sequence into a serialized critical section. Five
simultaneous applies to a 1-slot listing queue on the lock; the first commits and
fills the slot, the other four re-read the now-full count and get a clean
`409 CAP_REACHED`. A `UNIQUE(listing_id, student_id)` constraint is a second guard
so even a duplicate-apply race yields `409 ALREADY_APPLIED`, never a 500.

### Matching performance (referenced live)

Scores are computed at query time, not stored. The student's skills are resolved to
a `set[int]` **once** per request; listings load their skills eagerly
(`selectinload`), so per-listing scoring is O(k) set intersection and the whole
feed is linear in data read — not O(n²). At scale: pre-filter required-skill overlap
in SQL via the `student_skills`/`listing_skills` join + index, cache per-listing
static terms (recency bucket, id sets), and recompute lazily.
