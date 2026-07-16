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
- [ ] Scan pass: stream ZIP, persist conversation summaries (title, participants, message/link counts, date range) — no message bodies.
- [ ] Owner-name detection (`personal_information.json`, fallback: common participant) + self-DM candidate flagging.
- [ ] Mojibake fix (`encoding.py`) applied to all strings.
- [ ] Conversations API + selection endpoint; extract pass persists messages/items **only for selected conversations**.
- [ ] Link extraction (`share.link` + regex in `content`), canonicalization, shortcode, item_type.
- [ ] Adjacent-text windows (same sender, ±120s configurable).
- [ ] Exact dedupe into `duplicate_groups` (same shortcode / canonical URL).
- [ ] Fixtures: paginated threads, missing fields, self-DM present/absent, emoji/mojibake, duplicates.

Acceptance criteria:
- [ ] Variant A and B fixtures parse to identical logical results.
- [ ] Mojibake/emoji strings round-trip to exact expected values.
- [ ] Self-DM fixture flagged as candidate; no-self-DM fixture yields none.
- [ ] Fixture counts (conversations/messages/links/duplicates) match DB exactly.
- [ ] Re-running extract is idempotent — no duplicate items.
- [ ] Messages exist in DB only for selected conversations.

Test commands:
```bash
# standard suite
cd backend && python -m pytest tests/unit/test_encoding.py tests/unit/test_links.py tests/unit/test_selfdm.py tests/api/test_parser_pipeline.py -q
```

---

## Milestone 4 — Inspiration Inbox

**Goal:** the extracted items are browsable, searchable, and bulk-manageable.

Scope:
- [ ] Conversation selector UI (names, counts, self-DM confirmation).
- [ ] Inbox: reel cards (type badge, timestamp, share/adjacent text, status, tags, note) with server-side pagination.
- [ ] Search (Postgres full-text over share/adjacent text + notes).
- [ ] Filters: status, type, tags, conversation, date range.
- [ ] Duplicate-group visualization (grouped card with count).
- [ ] Status transitions; notes and tags editing; bulk select + bulk status/tag.
- [ ] Accessibility smoke (axe) on inbox and selector.

Acceptance criteria:
- [ ] Playwright: upload → select conversation → inbox renders expected fixture items.
- [ ] Search finds an item by adjacent text.
- [ ] Each filter provably narrows results (asserted counts).
- [ ] A duplicate group renders as one group of N.
- [ ] Bulk status change on a multi-selection persists.
- [ ] axe reports no critical violations on inbox/selector.

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
- [ ] Consent gate: Settings toggle + dialog disclosing network use; consent timestamp stored.
- [ ] Per-item / per-selection / per-group / per-cluster "Enrich" actions only — no global crawl.
- [ ] Fetcher: oEmbed → OG fallback, rate limit, timeouts, backoff, circuit breaker, result caching, `enrichment_attempts` audit.
- [ ] `needs_context` auto-assignment for text-poor items; code-level exclusion of such items from AI-generation input.
- [ ] Open-original button (new tab).
- [ ] Fast review mode: j/k navigate, o open, e edit note, Enter save+advance, s skip, number keys set status; needs-context-first ordering.
- [ ] Bulk notes/tags over selections and duplicate groups.

Acceptance criteria:
- [ ] With enrichment disabled (default), no outbound request occurs anywhere (respx assertion).
- [ ] Enabling the toggle alone triggers zero requests; only explicit Enrich actions do.
- [ ] Success / blocked / 404 paths all recorded in `enrichment_attempts`; cached results not re-fetched; UI labels enriched fields by source.
- [ ] A text-poor fixture item lands in `needs_context` and never reaches generation input (unit-enforced).
- [ ] Playwright drives the full keyboard review loop without mouse.
- [ ] A bulk note applies to every member of a duplicate group.

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
- [ ] `LLMProvider` interface + Anthropic, OpenAI, Mock implementations; config-only switching; Anthropic default for real use, Mock default in dev/CI.
- [ ] Structured-output validation with one repair retry; hard failure fails the job.
- [ ] Embeddings: fastembed → pgvector, `embed_batch` job, `EmbeddingProvider` interface.
- [ ] Clustering job (agglomerative, cosine threshold), versioned `cluster_runs`; runnable **before** review.
- [ ] Topic extraction (fast-model task); cluster labeling; editable cluster descriptions.
- [ ] Near-duplicate text detection via cosine threshold → `duplicate_groups` (`near_text`).
- [ ] Budget enforcement (`budget.py`) + `ai_requests` logging (no content).
- [ ] Settings UI: provider, model overrides, monthly budget.

Acceptance criteria:
- [ ] Full pipeline (embed → cluster → topics → labels) runs offline with MockProvider.
- [ ] Deterministic fixture clusters as expected (assertable memberships).
- [ ] Malformed-output test passes only via the repair path; double failure surfaces as a failed job with redacted error.
- [ ] `ai_requests` rows contain counts/cost but never text (asserted).
- [ ] Budget cap aborts a batch mid-way cleanly.
- [ ] Both real adapters pass respx contract tests (no live keys).

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
- [ ] `generate_projects` job from selected clusters/items + career profile; source IDs echoed and verified.
- [ ] Project library: cards, domain/status filters, score-sorted.
- [ ] Transparent scoring UI: sub-score bars + per-score rationale text.
- [ ] Weight sliders: instant client-side re-rank from stored sub-scores.
- [ ] Side-by-side comparison (2–3 projects).
- [ ] Combine-two-ideas flow (`CombinedProject`, parent links).
- [ ] **Project Advisor** (`AdvisorReview`): commonality verdict, comparative strength, recruiter impact, prerequisites, week-by-week plan; versioned.
- [ ] Project detail page; roadmap milestones CRUD + statuses; field editing; regenerate.

Acceptance criteria:
- [ ] MockProvider generation yields projects citing real source item/cluster IDs (server-verified).
- [ ] Weight change re-orders the library with no generation API call.
- [ ] Comparison view renders sub-scores aligned.
- [ ] Combining two projects creates a child with both parent IDs.
- [ ] Advisor renders all five structured sections, validates against schema, and regeneration versions it.
- [ ] Milestones persist and reorder.
- [ ] Playwright: generate → inspect scores → adjust weights → combine → advisor.

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
- [ ] Artifact generation: README plan, resume bullets, portfolio description, interview explanation, likely technical questions.
- [ ] Versioning + regenerate (v1 preserved).
- [ ] Fabricated-claims guard: prompt rule + regex post-check that flags suspicious performance numbers for user attention.
- [ ] Markdown export (project bundle + full library) and schema-stable JSON export, built by an export job through the Storage layer, downloadable.

Acceptance criteria:
- [ ] Each artifact kind generates and displays with version history.
- [ ] Regeneration creates v2 and keeps v1.
- [ ] Claims guard flags a seeded "achieved 97% accuracy" mock output (test).
- [ ] Exported Markdown renders correctly; JSON validates against its published schema.
- [ ] A project with no artifacts exports cleanly.
- [ ] Playwright: generate README → export → file-content assertions.

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
- [ ] Auth: argon2id, Redis sessions, httpOnly SameSite=Strict cookie, login rate limiting, CSRF posture, `create-user` CLI, all routes gated.
- [ ] Log-redaction filter finalized + pipeline-wide assertion test.
- [ ] Deletion flows: raw-import (keep-or-cascade choice), project, complete wipe with verification report.
- [ ] `docker-compose.prod.yml` + multi-stage images + Caddy auto-TLS.
- [ ] Backup scripts (nightly pg_dump + var/data) and a **tested** restore drill.
- [ ] Migration-against-prod-copy rehearsal procedure documented and exercised.
- [ ] Deploy documentation (DEPLOYMENT_PLAN.md updated with the real runbook).

Acceptance criteria:
- [ ] Route sweep test: every non-auth route rejects unauthenticated access.
- [ ] Sessions survive backend restart; logout revokes immediately.
- [ ] Full-pipeline log capture contains zero fixture message strings (automated).
- [ ] Each deletion scope leaves exactly the expected rows/files (count-verified); wipe report matches reality.
- [ ] VPS deploy serves valid HTTPS; port scan shows only Caddy exposed.
- [ ] Restore drill from a real nightly backup succeeds with matching counts.

Test commands:
```bash
# standard suite
cd backend && python -m pytest tests/api/test_auth.py tests/api/test_route_gating.py tests/unit/test_log_redaction.py tests/api/test_deletion.py -q
cd e2e && npx playwright test specs/auth-deletion.spec.ts
# on the VPS after deploy:
curl -fsS https://$APP_DOMAIN/api/health
```

---

## Milestone 10 — Real-Data Hardening

**Goal:** the app works reliably with Adam's actual export at real scale.

Scope:
- [ ] Run the real export locally per TESTING_STRATEGY.md real-data workflow.
- [ ] Parser tolerance fixes for real-world JSON variations — **each with a new synthetic fixture** reproducing it.
- [ ] Import-verification report UI: parsed counts vs. raw ZIP scan counts; every skipped entry categorized, none silent.
- [ ] Verify duplicate detection on real repeat shares.
- [ ] Verify all deletion scopes on a real-data copy.
- [ ] Performance pass: 5k-message fixture benchmark + real export (targets: scan < 1 min, extract < 3 min for ~5k messages, inbox p95 API < 300 ms).
- [ ] Only after all above: optionally load real data on the VPS.

Acceptance criteria:
- [ ] Real export imports with zero unhandled parse errors.
- [ ] Verification report link count within explained tolerance of raw count.
- [ ] Duplicate spot-checks correct on real repeats.
- [ ] Complete wipe verified on a real-data copy.
- [ ] Perf targets met on the 5k fixture via the benchmark script.
- [ ] Every real-world quirk that changed code has a committed synthetic fixture + test.

Test commands:
```bash
# standard suite
cd backend && python -m pytest -q                       # entire suite, including new quirk fixtures
cd backend && python scripts/benchmark_import.py        # prints timings; must meet targets
cd e2e && npx playwright test                           # full critical path
```
