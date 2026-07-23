# InspirationOS — Implementation Plan

Ten sequential milestones. **The final scope is the complete personal-use
version — no milestone may be dropped or trimmed as "not needed for an MVP."**
Work on one milestone at a time; a milestone is done only when every scope box
is checked, every acceptance criterion passes, and CI is green.

Conventions for every milestone:
- Tests use synthetic fixtures from `backend/tests/fixture_builder.py` only.
- Service-dependent tests (Postgres/Redis) skip with an explicit message when
  services are unreachable locally; CI always runs them.
- The standard verification suite ("**standard suite**") means:

```bash
cd backend && python -m ruff format --check . && python -m ruff check .
cd backend && python -m mypy app
cd backend && python -m pytest -q
cd frontend && npm run lint
cd frontend && npx tsc --noEmit
cd frontend && npm run test -- --run
```

---

## Milestone 1 — Foundation

**Goal:** running monorepo skeleton with compose stack, migrations, health
checks, a proven job loop, and CI.

Scope:
- [x] Monorepo layout per ARCHITECTURE.md (`backend/`, `frontend/`, `e2e/`).
- [x] `docker-compose.yml`: pgvector Postgres, Redis, backend (reload), RQ worker, Next.js dev.
- [x] Backend: FastAPI app, pydantic-settings config from env, SQLAlchemy 2 + Alembic wired, initial migration (`users`, `settings`, `jobs`).
- [x] `/api/health` endpoint checking DB + Redis; frontend page consuming it via the Next proxy.
- [x] Demo background job: enqueue via API → jobs row `queued→running→succeeded` → status poll endpoint.
- [x] Test skeletons: pytest (unit + api + workers dirs), Vitest + RTL, Playwright config + health spec.
- [x] GitHub Actions CI: backend / frontend / e2e / gitleaks jobs.
- [x] `.pre-commit-config.yaml` (ruff, ruff-format, gitleaks, frontend lint hook), `Makefile`, `.env.example`, `.gitignore`.

Acceptance criteria:
- [ ] Fresh clone + `docker compose up` yields a working stack (verified in CI's e2e job; locally once Docker Desktop exists).
- [ ] `GET /api/health` returns ok with DB and Redis both reported healthy, reachable through the frontend proxy.
- [ ] Demo job transitions `queued→running→succeeded` in the `jobs` table and the frontend shows the transition by polling.
- [x] Standard suite passes; unit tests pass with no services running.
- [ ] CI green on the initial PR.
- [x] gitleaks pre-commit blocks a planted fake secret (verified once, manually, then the plant removed).

Test commands (all must pass):
```bash
# standard suite (see top)
cd e2e && npx playwright test specs/health.spec.ts   # in CI or with Docker up
```

---

## Milestone 2 — Secure Import

**Goal:** uploads are safe, recorded, and recoverable; malicious archives are
rejected; fixtures exist.

Scope:
- [x] Streamed, size-capped upload endpoint → Storage abstraction (`services/storage/`, local FS under `var/data/`) → `imports` row → `import_scan` job stub.
- [x] ZIP safety in `services/ingest/zip_safety.py`: zip-slip guard, zip-bomb caps (entry count, total uncompressed, compression ratio), never-wholesale extraction.
- [x] JSON-export detection; HTML exports rejected with "re-request as JSON" message.
- [x] SHA-256 checksum dedupe of re-uploaded ZIPs (app-level pre-check + authoritative partial unique index).
- [x] Temp cleanup guaranteed in `finally`; failure paths leave consistent `imports`/`jobs` rows.
- [x] `fixture_builder.py` v1: variants A/B, HTML export, zip-slip + zip-bomb fixtures (plus corrupted/empty/unrecognized/not-a-zip), stdlib-only with a CLI for e2e.
- [x] Frontend: import screen (upload, list, detail with job progress polling).

Acceptance criteria (verified locally against the compose stack 2026-07-16; CI
run still required — no commit has been made yet):
- [x] Valid synthetic ZIP uploads reach `scanned` status (stub counts).
- [x] Zip-slip and zip-bomb fixtures rejected with clean errors and **zero files left on disk** (asserted by test).
- [x] Oversized upload rejected before the body is fully read.
- [x] HTML export produces the actionable rejection message.
- [x] Re-uploading the same ZIP is detected via checksum.
- [x] Every rejection branch has a test.

Test commands:
```bash
# standard suite
cd backend && python -m pytest tests/unit/test_zip_safety.py tests/api/test_uploads.py -q
cd e2e && npx playwright test specs/import.spec.ts
```

---

## Milestone 3 — Instagram Parser

**Goal:** conversations discovered, self-DM flagged, links extracted and
deduplicated — correctly, idempotently, for multiple export structures.

Scope:
- [x] Scan pass: stream ZIP, persist conversation summaries (title, participants, message/link counts, date range) — no message bodies.
- [x] Owner-name detection (`personal_information.json`, fallback: common participant) + self-DM candidate flagging.
- [x] Mojibake fix (`encoding.py`) applied to all strings.
- [x] Conversations API + selection endpoint; extract pass persists messages/items **only for selected conversations**.
- [x] Link extraction (`share.link` + regex in `content`), canonicalization, shortcode, item_type.
- [x] Adjacent-text windows (same sender, ±120s configurable).
- [x] Exact dedupe into `duplicate_groups` (same shortcode / canonical URL).
- [x] Fixtures: paginated threads, missing fields, self-DM present/absent, emoji/mojibake, duplicates.

Acceptance criteria (verified locally against the compose stack 2026-07-17; CI
run still required — no commit has been made yet):
- [x] Variant A and B fixtures parse to identical logical results.
- [x] Mojibake/emoji strings round-trip to exact expected values.
- [x] Self-DM fixture flagged as candidate; no-self-DM fixture yields none.
- [x] Fixture counts (conversations/messages/links/duplicates) match DB exactly.
- [x] Re-running extract is idempotent — no duplicate items.
- [x] Messages exist in DB only for selected conversations.

Test commands:
```bash
# standard suite
cd backend && python -m pytest tests/unit/test_encoding.py tests/unit/test_links.py tests/unit/test_selfdm.py tests/api/test_parser_pipeline.py -q
```

---

## Milestone 4 — Inspiration Inbox

**Goal:** the extracted items are browsable, searchable, and bulk-manageable.

Scope:
- [x] Conversation selector UI (names, counts, self-DM confirmation).
- [x] Inbox: reel cards (type badge, timestamp, share/adjacent text, status, tags, note) with server-side pagination.
- [x] Search (Postgres full-text over share/adjacent text + notes).
- [x] Filters: status, type, tags, conversation, date range.
- [x] Duplicate-group visualization (grouped card with count).
- [x] Status transitions; notes and tags editing; bulk select + bulk status/tag.
- [x] Accessibility smoke (axe) on inbox and selector.

Acceptance criteria (verified locally against the compose stack 2026-07-18;
CI run still required — no commit has been made yet):
- [x] Playwright: upload → select conversation → inbox renders expected fixture items.
- [x] Search finds an item by adjacent text.
- [x] Each filter provably narrows results (asserted counts).
- [x] A duplicate group renders as one group of N.
- [x] Bulk status change on a multi-selection persists.
- [x] axe reports no critical violations on inbox/selector.

Test commands:
```bash
# standard suite
cd backend && python -m pytest tests/api/test_items.py -q
cd e2e && npx playwright test specs/inbox.spec.ts
```

---

## Milestone 5 — Content-Enrichment Workflow

**Goal:** consent-gated best-effort enrichment; a review queue fast enough
that manual context entry is painless.

Scope:
- [x] Consent gate: Settings toggle + dialog disclosing network use; consent timestamp stored.
- [x] Per-item / per-selection / per-group "Enrich" actions only — no global crawl. (Per-cluster is the same `item_ids`-based endpoint; clusters themselves don't exist until M6, so there's no cluster UI to wire it to yet.)
- [x] Fetcher: oEmbed → OG fallback, rate limit, timeouts, backoff, circuit breaker, result caching, `enrichment_attempts` audit.
- [x] `needs_context` auto-assignment for text-poor items; code-level exclusion of such items from AI-generation input.
- [x] Open-original button (new tab).
- [x] Fast review mode: j/k navigate, o open, e edit note, Enter save+advance, s skip, number keys set status; needs-context-first ordering.
- [x] Bulk notes/tags over selections and duplicate groups.

Acceptance criteria (verified locally against the compose stack 2026-07-19;
CI run still required — no commit has been made yet):
- [x] With enrichment disabled (default), no outbound request occurs anywhere (respx assertion).
- [x] Enabling the toggle alone triggers zero requests; only explicit Enrich actions do.
- [x] Success / blocked / 404 paths all recorded in `enrichment_attempts`; cached results not re-fetched; UI labels enriched fields by source.
- [x] A text-poor fixture item lands in `needs_context` and never reaches generation input (unit-enforced).
- [x] Playwright drives the full keyboard review loop without mouse.
- [x] A bulk note applies to every member of a duplicate group.

Test commands:
```bash
# standard suite
cd backend && python -m pytest tests/unit/test_enrichment_policy.py tests/api/test_enrichment.py -q
cd e2e && npx playwright test specs/review.spec.ts
```

---

## Milestone 6 — AI Analysis

**Goal:** provider-agnostic AI plumbing; embeddings, clustering, and topics
that work offline via the mock provider.

Scope:
- [x] `LLMProvider` interface + Anthropic, OpenAI, Mock implementations; config-only switching; Anthropic default for real use, Mock default in dev/CI.
- [x] Structured-output validation with one repair retry; hard failure fails the job.
- [x] Embeddings: fastembed → pgvector, `embed_batch` job, `EmbeddingProvider` interface.
- [x] Clustering job (agglomerative, cosine threshold), versioned `cluster_runs`; runnable **before** review.
- [x] Topic extraction (fast-model task); cluster labeling; editable cluster descriptions.
- [x] Near-duplicate text detection via cosine threshold → `duplicate_groups` (`near_text`).
- [x] Budget enforcement (`budget.py`) + `ai_requests` logging (no content).
- [x] Settings UI: provider, model overrides, monthly budget.

Acceptance criteria (verified locally against the compose stack 2026-07-19;
CI run still required — no commit has been made yet):
- [x] Full pipeline (embed → cluster → topics → labels) runs offline with MockProvider (worker test wraps it in a zero-HTTP respx guard; e2e drives it through the UI).
- [x] Deterministic fixture clusters as expected (assertable memberships).
- [x] Malformed-output test passes only via the repair path; double failure surfaces as a failed job with redacted error.
- [x] `ai_requests` rows contain counts/cost but never text (asserted; the table has no content columns at all).
- [x] Budget cap aborts a batch mid-way cleanly.
- [x] Both real adapters pass respx contract tests (no live keys).

Test commands:
```bash
# standard suite
cd backend && python -m pytest tests/unit/test_providers.py tests/unit/test_budget.py tests/workers/test_analysis_jobs.py -q
cd e2e && npx playwright test specs/clusters.spec.ts
```

---

## Milestone 7 — Project Workspace

**Goal:** grounded project generation with transparent, re-rankable scoring;
comparison, combination, advisor, roadmaps.

Scope:
- [x] `generate_projects` job from selected clusters/items + career profile; source IDs echoed and verified.
- [x] Project library: cards, domain/status filters, score-sorted.
- [x] Transparent scoring UI: sub-score bars + per-score rationale text.
- [x] Weight sliders: instant client-side re-rank from stored sub-scores.
- [x] Side-by-side comparison (2–3 projects).
- [x] Combine-two-ideas flow (`CombinedProject`, parent links).
- [x] **Project Advisor** (`AdvisorReview`): commonality verdict, comparative strength, recruiter impact, prerequisites, week-by-week plan; versioned.
- [x] Project detail page; roadmap milestones CRUD + statuses; field editing; regenerate.

Acceptance criteria (verified locally against the compose stack 2026-07-20;
CI run still required — no commit has been made yet):
- [x] MockProvider generation yields projects citing real source item/cluster IDs (server-verified).
- [x] Weight change re-orders the library with no generation API call.
- [x] Comparison view renders sub-scores aligned.
- [x] Combining two projects creates a child with both parent IDs.
- [x] Advisor renders all five structured sections, validates against schema, and regeneration versions it.
- [x] Milestones persist and reorder.
- [x] Playwright: generate → inspect scores → adjust weights → combine → advisor.

Test commands:
```bash
# standard suite
cd backend && python -m pytest tests/api/test_projects.py tests/unit/test_scoring.py tests/workers/test_generation_jobs.py -q
cd e2e && npx playwright test specs/projects.spec.ts
```

---

## Milestone 8 — Career Outputs

**Goal:** per-project career artifacts and stable exports, with no fabricated
claims.

Scope:
- [x] Artifact generation: README plan, resume bullets, portfolio description, interview explanation, likely technical questions.
- [x] Versioning + regenerate (v1 preserved).
- [x] Fabricated-claims guard: prompt rule + regex post-check that flags suspicious performance numbers for user attention.
- [x] Markdown export (project bundle + full library) and schema-stable JSON export, built by an export job through the Storage layer, downloadable.

Acceptance criteria (verified locally against the compose stack 2026-07-20 —
backend/frontend suites green; the Playwright criterion below is blocked, see
note):
- [x] Each artifact kind generates and displays with version history.
- [x] Regeneration creates v2 and keeps v1.
- [x] Claims guard flags a seeded "achieved 97% accuracy" mock output (test).
- [x] Exported Markdown renders correctly; JSON validates against its published schema.
- [x] A project with no artifacts exports cleanly.
- [ ] Playwright: generate README → export → file-content assertions.
  `specs/artifacts-export.spec.ts` is written (upload → extract → cluster →
  generate → generate README → export Markdown → export JSON → file-content
  assertions) but could not be exercised locally: the dev compose stack's
  `/import/[id]/conversations` route currently 404s in the frontend
  container (Next 16 / Turbopack dev server), reproduced identically by
  re-running the untouched, pre-existing `clusters.spec.ts` (M6) — a
  pre-existing environment defect, not caused by this milestone's diff.
  Needs a CI run (or a from-scratch dev-stack rebuild) to close out.

Test commands:
```bash
# standard suite
cd backend && python -m pytest tests/api/test_artifacts.py tests/unit/test_claims_guard.py tests/api/test_export.py -q
cd e2e && npx playwright test specs/artifacts-export.spec.ts
```

---

## Milestone 9 — Privacy & Personal Deployment

**Goal:** locked-down single-user app running privately on a VPS with tested
backups and deletion.

Scope:
- [x] Auth: argon2id, Redis sessions, httpOnly SameSite=Strict cookie, login rate limiting, CSRF posture, `create-user` CLI, all routes gated.
- [x] Log-redaction filter finalized + pipeline-wide assertion test.
- [x] Deletion flows: raw-import (keep-or-cascade choice), project, complete wipe with verification report.
- [x] `docker-compose.prod.yml` + multi-stage images + Caddy auto-TLS.
- [x] Backup scripts (nightly pg_dump + var/data) and a **tested** restore drill.
- [x] Migration-against-prod-copy rehearsal procedure documented and exercised — exercised against a fresh scratch stack built from the prod images (no real prod data exists yet, since there is no VPS deployment; `make deploy-migrate` ran cleanly through all 8 existing migrations there).
- [x] Deploy documentation (DEPLOYMENT_PLAN.md updated with the real runbook).

Acceptance criteria (verified locally 2026-07-21 against the compose stack
and a scratch `docker-compose.prod.yml` drill; the VPS-specific criterion
below is the one exception — see note):
- [x] Route sweep test: every non-auth route rejects unauthenticated access (`tests/api/test_route_gating.py`, 48 routes swept via `app.openapi()["paths"]`).
- [x] Sessions survive backend restart; logout revokes immediately (unit-tested and manually verified in a browser: login → logout → re-redirected to `/login` → protected API 401s).
- [x] Full-pipeline log capture contains zero fixture message strings (automated) — `tests/workers/test_log_redaction_pipeline.py` runs real scan+extract over the rich fixture with `caplog` capturing everything.
- [x] Each deletion scope leaves exactly the expected rows/files (count-verified); wipe report matches reality — `tests/api/test_deletion.py`; raw-import deletion additionally verified end-to-end in a real browser (upload → typed-confirmation delete → status shows `deleted`).
- [ ] VPS deploy serves valid HTTPS; port scan shows only Caddy exposed. **Not verified** — no real VPS/domain is available in this environment; `docker-compose.prod.yml`/`Caddyfile` are written and the non-Caddy services are confirmed to publish no ports, but live TLS issuance and an external port scan need a real deploy.
- [x] Restore drill from a real nightly backup succeeds with matching counts — rehearsed end-to-end under an isolated scratch compose project (`-p inspiration-drill`, separate from the dev stack): seeded rows + a data-volume file → `pg_dump`/tar backup → full simulated disaster (`down -v`) → fresh stack → restore both → row counts and file contents matched exactly. The nightly **cron scheduling** itself wasn't set up (no VPS to install a crontab on) — only the backup/restore mechanics were exercised.

Known limitations:
- The pre-existing `/import/[id]/conversations` dev-server defect noted in
  M8 (Next.js 16 Turbopack) was re-confirmed during this milestone's manual
  verification, including after a full `docker compose down` + `up --build`
  from scratch — the route still 404s locally. This blocks the specs that
  depend on conversation selection (`clusters.spec.ts`, `inbox.spec.ts`,
  `projects.spec.ts`, `review.spec.ts`, `artifacts-export.spec.ts`) locally;
  it does not affect this milestone's own `auth-deletion.spec.ts` (which
  never visits that route) or `health.spec.ts`/`import.spec.ts`, all of
  which pass locally. Needs a CI run to close out — CI runs on Linux, not
  this Windows+Docker-Desktop dev box, so it may simply not reproduce there.
- The frontend's `proxy.ts` redirect-to-login guard checks cookie
  *presence*, not validity — if a session is revoked server-side (e.g. a
  Redis flush) while the browser still holds the cookie, protected pages
  will 401 their API calls rather than auto-redirecting to `/login`. Not a
  security gap (the backend still rejects every call correctly), but a
  minor UX rough edge, discovered during manual verification.

Test commands:
```bash
# standard suite
cd backend && python -m pytest tests/api/test_auth.py tests/api/test_route_gating.py tests/unit/test_log_redaction.py tests/workers/test_log_redaction_pipeline.py tests/api/test_deletion.py -q
cd e2e && npx playwright test specs/auth-deletion.spec.ts
# on the VPS after deploy:
curl -fsS https://$APP_DOMAIN/api/health
```

---

## Milestone 10 — Real-Data Hardening

**Status: implementation complete; real-export validation pending.** No
real Instagram export exists in the environment this milestone was
implemented in, and per hard constraint none may be fetched, requested, or
fabricated — see TESTING_STRATEGY.md's "Real-data workflow" for the manual
runbook the user runs afterward with their own file. Every box below that
depends on the real export is left unchecked on purpose; everything
buildable and testable against synthetic fixtures (including the
5,000-message performance benchmark, which the perf targets are defined
against directly, not just the real export) is implemented, tested, and
was executed in this session.

**Goal:** the app works reliably with Adam's actual export at real scale.

Scope:
- [ ] Run the real export locally per TESTING_STRATEGY.md real-data workflow. — pending (needs the real file; runbook documented)
- [x] Parser tolerance fixes for real-world JSON variations — **each with a new synthetic fixture** reproducing it. Scope for this session: (1) every scan-pass skip is now categorized and counted instead of silently dropped (`ScanIssues`, `services/ingest/instagram/export_reader.py`); (2) known Meta thread categories beyond `inbox` (`message_requests`/`filtered_threads`/`archived_threads`) are now parsed, not invisible. Both are defensive tolerance for *documented* export-format facts, not fixes for quirks observed in a real file — any *additional* variation the real run surfaces still needs its own fixture+test afterward.
- [x] Import-verification report UI: parsed counts vs. raw ZIP scan counts; every skipped entry categorized, none silent. `GET /api/imports/{id}/verification` (`services/ingest/verification.py`) + the import detail page's "Verification report" card; tested against a purpose-built fixture (`build_verification_export_zip`) exercising every skip category and a duplicate pair.
- [ ] Verify duplicate detection on real repeat shares. — the duplicate-summary mechanism is built and tested against synthetic duplicates; real spot-check pending.
- [ ] Verify all deletion scopes on a real-data copy. — deletion scopes were already implemented and tested in M9; the real-data-copy drill procedure is documented (reusing the M9 backup/restore scratch-project pattern) but not executed (no real data exists here).
- [x] / [ ] Performance pass: 5k-message fixture benchmark + real export (targets: scan < 1 min, extract < 3 min for ~5k messages, inbox p95 API < 300 ms). Synthetic-fixture leg **done and run this session** (`backend/scripts/benchmark_import.py` against `fixture_builder.build_perf_export_zip`); real-export leg pending.
- [ ] Only after all above: optionally load real data on the VPS. — pending (blocked on everything above).

Acceptance criteria:
- [ ] Real export imports with zero unhandled parse errors. — pending, needs the real file.
- [ ] Verification report link count within explained tolerance of raw count. — mechanism built + tested on synthetic data; real comparison pending.
- [ ] Duplicate spot-checks correct on real repeats. — mechanism built + tested on synthetic duplicates; real spot-check pending.
- [ ] Complete wipe verified on a real-data copy. — deletion scopes tested (M9); real-copy drill documented, not executed.
- [x] Perf targets met on the 5k fixture via the benchmark script. — run this session: scan 0.22s (< 60s), extract 22.72s (< 180s), inbox p95 32.7ms (< 300ms), all PASS. (The "+ real export" half of the scope line above stays pending.)
- [ ] Every real-world quirk that changed code has a committed synthetic fixture + test. — true for everything changed this session (see the two fixes above); any further quirk found in the real run needs the same treatment afterward.

Test commands:
```bash
# standard suite
cd backend && python -m ruff format . && python -m ruff check --fix .
cd backend && python -m mypy app
cd backend && python -m pytest -q                       # entire suite, including new quirk fixtures — 411 passed, 3 skipped (pre-existing, unrelated)
cd frontend && npm run lint && npx tsc --noEmit && npm run test -- --run
cd backend && python scripts/benchmark_import.py --email <existing-account>   # prints timings; must meet targets
cd e2e && npx playwright test                           # full critical path, including specs/verification.spec.ts
```
