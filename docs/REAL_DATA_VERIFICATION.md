# Real-Data Verification Report

Records what was actually exercised against the running application, as
opposed to what `docs/IMPLEMENTATION_PLAN.md` records as *implemented*.
Synthetic-fixture results and real-export results are kept in clearly
separate sections per the project's privacy rules — **no real Instagram
export has been used against this application; the real-export sections
below are explicitly pending.**

## Test metadata

- **Date:** 2026-07-23
- **Commit:** `5b18c0e6857789e1f4b1667804e2c84bea801182` ("Implement Milestone
  10 - Real-Data Hardening (real-export validation pending)")
- **Environment:** Windows 11 Home, Docker Desktop 29.6.1, full compose
  stack (`docker compose up -d --build --force-recreate
  --renew-anon-volumes`), backend Python 3.12 venv, Node v24.16.0.
- **AI provider for all synthetic testing:** `mock` (default), except the
  deliberate invalid-key drill below.

## Layer 1 — Automated suite (synthetic fixtures only)

| Check | Result |
| --- | --- |
| `ruff format --check .` / `ruff check .` | PASS |
| `mypy app` | PASS (102 files) |
| `pytest -q` | **411 passed, 3 skipped** (pre-existing exempt-route skips in `test_route_gating.py`, unrelated to this pass) |
| `npm run lint` | PASS |
| `npx tsc --noEmit` | PASS |
| `npm run test -- --run` | **83 passed** (18 files) |
| `npx playwright test` (16 specs) | **16/16 passed** on a clean run; one later re-run showed 1 flake (`auth-deletion.spec.ts` raw-import-deletion) caused by a concurrent manual browser session contending for the same shared single worker — reproduced clean (4/4) in isolation immediately after. Not a regression. |
| `backend/scripts/benchmark_import.py` (synthetic 5k fixture) | **PASS** — scan 0.22s (< 60s), extract ~23s (< 180s), inbox p95 ~30ms (< 300ms) |

## Layer 2 — Full-stack smoke test (browser, live compose stack)

- Home page loads; "All services healthy", DB healthy, Redis healthy — PASS
- Login (test account) — PASS
- Refresh persists session — PASS
- Backend health + Swagger docs (`localhost:8000/docs`) — PASS
- Import page opens, renders the import list — PASS
- Console: zero errors across every page visited
- Network: zero unexplained 401/404/422/500. The one 401 seen was a stale
  session cookie surviving a Redis flush from the container rebuild — this
  is the **already-documented M9 UX limitation** (`proxy.ts` checks cookie
  *presence*, not validity), not a new defect.
- Worker/job status: the demo job completes successfully server-side every
  time (confirmed via the `jobs` table and worker logs). One polling
  artifact was observed in the automated browser-testing tool specifically
  — it reports `document.visibilityState === "hidden"`, which pauses
  TanStack Query's default background-polling behavior. This is a
  characteristic of the automation tool's rendering context, not the app:
  the same flow is covered by `e2e/specs/health.spec.ts`'s "demo job
  transitions queued/running to succeeded via polling" test, which passes
  reliably in a normally-focused Playwright browser.

## Layer 3 — Real Instagram export workflow: **NOT RUN**

No real export file was placed in this environment (`var/private/` is
empty), and per this project's hard constraints an automated session must
never fetch, request, or fabricate one. Every acceptance criterion below
that depends on the real file is **pending** — see the manual checklist at
the end of this document.

## Layer 4 — Destructive recovery tests

| Scenario | Result |
| --- | --- |
| `docker compose restart backend` | **PASS** — migrations re-run, `/api/health` OK immediately after. |
| `docker compose restart worker` (graceful SIGTERM) | **PASS** — RQ's warm shutdown finishes the in-flight job before the process exits; the new worker resumes queue processing normally. |
| `docker compose restart redis` | **PASS** — worker logs connection errors, retries with backoff, reconnects automatically, and successfully processes new jobs once Redis is healthy again. |
| Worker **hard kill** (`docker kill`) mid-job | **FAIL — real gap found.** A 20-step demo job killed at step 6 stayed stuck at `status=running, progress=6/20` for **370+ seconds across 3 subsequent worker restarts**, with no automatic recovery. Root cause: `git grep -n ".enqueue("` across `app/` shows **no** enqueue call anywhere in the codebase passes `retry=Retry(...)` or a custom `job_timeout`, despite `docs/ARCHITECTURE.md` documenting `Retry(max=3, interval=[10, 60, 300])` and a "Retry button in UI" for exactly this scenario. Neither exists (`cli.py requeue-failed` was also already noted in M9's own doc as never implemented). **Practical impact:** a real worker crash (OOM-kill, host reboot, container crash) leaves that job permanently `running` forever, with no automated recovery and no UI/CLI way to retry or cancel it. Not fixed in this pass — flagged as a follow-up (see "Known limitations"). |
| Invalid AI provider key | **PASS.** Switched `settings.ai_provider` to `anthropic` with a deliberately fake key, triggered a real topic-extraction job against an existing cluster run. The job failed cleanly with `jobs.error = "AuthenticationError"` (exception class name only); the worker did not crash and continued processing subsequent jobs normally; `git grep`/log grep confirmed the fake key never appeared in any backend or worker log; the `ai_requests` audit row recorded `status=error` with zero content. Reverted the provider setting to `mock` and removed the temporary `.env` afterward. |

## Deletion drill (synthetic data)

Deleted import `1433` (`rich_a.zip`, `cascade=true`) via the live running
API:

- Stored ZIP removed from disk (`var/data/imports/...` — confirmed gone)
- 2 conversations / 11 messages / 5 items removed for that import
- Import status → `deleted`
- An unrelated import (`rich_b.zip`) kept all 5 of its items untouched
- Active-import count dropped by exactly 1 (110 → 109)

**PASS.**

## Backup/restore drill

Built `docker-compose.prod.yml` images in an isolated scratch project
(`-p inspiration-backup-drill`, fully separate network/volumes from the
live dev stack), seeded a test project row + a marker file in the data
volume, then:

1. Backed up: `pg_dump` (gzipped) + `tar` of `/app/var/data`.
2. Full simulated disaster: `down -v` (all containers + volumes destroyed).
3. Restored both the DB dump and the data tar into a **second**, separate
   scratch project (`-p inspiration-restore-drill`).
4. Verified: the seeded project row, the marker file's exact byte content,
   and login against the restored user account all matched.
5. Tore down both scratch projects (`down -v`) and removed the scratch
   images; confirmed zero drill containers/volumes/images remain and the
   live dev stack was completely unaffected throughout.

**PASS.** (A Windows/Git-Bash-specific tooling gotcha was hit and worked
around along the way — piping a decompressed tar into `docker exec -i`
mangles binary data on this box; routing through `docker cp` instead fixed
it. Documented in the assistant's environment notes; not an application
defect.)

## Privacy leak review

- `git grep -n "ANTHROPIC_API_KEY"` / `"OPENAI_API_KEY"`: only
  placeholder/config references (`.env.example`, docker-compose env-var
  wiring, `ProviderNotConfiguredError` messages) — no real key values
  anywhere in the tree.
- `git status --ignored`: `var/`, all caches, `node_modules/`, etc. all
  correctly ignored; nothing unexpected.
- Working tree clean at the time of review; nothing staged.
- A full `docker compose logs` snapshot was grepped for API-key patterns,
  `share_text`/`adjacent_text`/`context_note` field leaks, raw password
  values, and email addresses — **zero matches on every check.** The
  snapshot was deleted immediately after review.

## Known limitations

1. **Real-export-dependent acceptance criteria remain unverified**: real
   parse-error count, real duplicate spot-check, deletion-scope-on-a-real-copy
   drill, and real-export performance numbers. Pending the user's own run
   per the manual checklist below and `docs/TESTING_STRATEGY.md`'s
   real-data workflow.
2. **New finding, this pass:** a hard worker crash mid-job leaves that job
   permanently stuck at `running` with no automatic retry/recovery and no
   UI/CLI way to unstick it — `docs/ARCHITECTURE.md`'s documented
   `Retry(...)`/"Retry button in UI" claims do not match the actual
   implementation. Not fixed here (out of scope for a testing pass);
   worth a dedicated follow-up.
3. **Pre-existing, already documented (M9):** a stale-but-present session
   cookie doesn't auto-redirect to `/login` after a server-side session
   revocation (e.g. a Redis flush) — reproduced again naturally during this
   pass, not a new issue.

## Manual checklist — real Instagram export (for the user)

Run once the export is placed at `var/private/<file>.zip` and uploaded
through the app yourself. Record results without pasting raw message
content back — counts, statuses, and pass/fail per item are enough.

**1. Self-DM confirmation**
- After upload → scan, open `/import/{id}/conversations`.
- Find the conversation flagged as a self-DM *candidate*.
- Confirm it's really your own "message yourself" thread (participant list
  is just you, or the title is your own name).
- If no candidate was flagged but you know you have one, or the wrong
  thread got flagged, note the mismatch.

**2. Spot-check 20 random extracted reels**
- After extraction, open `/inbox`; sample ~20 items spread across several
  pages (not just page 1).
- For each: click through to the original — confirm the link is correct
  (right reel/post, right creator) and the `item_type` badge matches
  (reel/post/tv/story/external).
- Confirm `shared_at` looks plausible.

**3. Check 10 duplicate groups**
- In the Inbox, open 10 different grouped ("×N") cards.
- Confirm each group is genuinely the *same* content shared multiple
  times, not an incorrect grouping.
- Cross-check the totals against the Verification Report's duplicate
  summary (by reason) for a rough sanity check.

**4. Check 10 adjacent-message cases**
- Pick 10 items with adjacent text shown beyond the share caption.
- Confirm that text genuinely reads as commentary sent close in time to
  that share, not unrelated content pulled in incorrectly.

**5. Record mismatches**
- For each category: total sampled, number correct, and a description of
  any mismatch (item id / thread name is fine — no message bodies) precise
  enough to act on.

Report back the pass/fail counts and any mismatches; the real-export
acceptance criteria in `docs/IMPLEMENTATION_PLAN.md` stay unchecked until
this comes back clean.

## After this checklist passes

```bash
git status
git add .
git commit -m "Validate complete application workflow"
git push
```

Optionally, once *everything* (including the real-export checklist above)
has genuinely passed:

```bash
git tag -a v1.0.0 -m "First fully tested personal release"
git push origin v1.0.0
```
