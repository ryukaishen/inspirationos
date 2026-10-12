# InspirationOS — Testing Strategy

## Principles

- Every milestone ends with green tests proving its acceptance criteria.
- **All test data is synthetic.** No real export content ever appears in
  tests, fixtures, or git.
- Tests that need Postgres/Redis run against real services (Docker locally,
  service containers in CI) and **skip with an explicit message** when the
  services are unreachable — they are never silently faked. CI always runs
  them, so skips can't hide failures.

## The synthetic fixture system (cornerstone)

`backend/tests/fixture_builder.py` programmatically writes Instagram-export
ZIPs at test time (nothing export-like is committed):

- **Variant A** — current layout (`your_instagram_activity/messages/inbox/…`).
- **Variant B** — legacy layout (`messages/inbox/…`).
- **Rich export** (`build_rich_export_zip`, emitted by the CLI as
  `rich_a.zip`/`rich_b.zip`) — identical logical content in both layouts:
  a paginated friend thread, a self-DM thread, adjacent-window hits and
  misses, exact + tracking-parameter duplicates, an external link, and
  mojibake strings whose exact expected decodings are exported as module
  constants for test assertions.
- **Cluster export** (`build_cluster_export_zip`, emitted as `clusters.zip`
  and, with a distinct `--unique` marker, `projects.zip`; M6/M7) — one friend
  thread whose shares form two clearly-themed groups (high token overlap
  within a theme, none across) plus a near-duplicate text pair on distinct
  URLs. Deterministic clusters under both the mock and the real local
  embedding provider; kept separate from the rich export so M4/M5 count
  assertions never shift. `clusters.spec.ts` uploads `clusters.zip` and
  `projects.spec.ts` uploads `projects.zip` (each spec file uploads its own
  ZIP — checksum dedupe would 409 a re-upload).
- Mojibake/emoji strings (UTF-8-as-latin-1 escapes) with known expected
  decodings.
- Multi-file paginated threads (`message_1.json`, `message_2.json`).
- Self-DM present / absent variants; `personal_information.json` present /
  missing.
- Messages with missing fields, unsent messages, media-only messages.
- Shared reels/posts (`share.link` + URLs inside `content`), including exact
  duplicates and tracking-parameter variants.
- An HTML-format export (must be rejected).
- Malicious pair: zip-slip (path traversal entries, `/` and `\` separators,
  absolute and drive-letter paths) and zip-bomb (extreme compression ratio /
  entry count / total declared size); plus not-a-zip, corrupted
  central-directory, empty, and unrecognized ZIPs.
- A ~5,000-message export for performance tests (built on demand).

The builder is **stdlib-only** and doubles as a CLI so Playwright can generate
fixtures without installing backend dependencies —
`e2e/global-setup.ts` runs it before every e2e session:

```bash
python backend/tests/fixture_builder.py --out e2e/.fixtures --unique 12345
```

`--unique` varies message text (and therefore checksums) per run so the
dedupe flow stays testable against a long-lived dev stack. Generated ZIPs land
in gitignored paths only.

Every real-world quirk discovered in M10 gets a new synthetic fixture
reproducing it before the fix is considered done.

## Test layers

### Backend — pytest (`backend/tests/`)
- **unit/** — no services needed: mojibake fix, URL canonicalization,
  shortcode extraction, self-DM heuristics, dedupe logic, ZIP safety
  rejections, scoring math, budget enforcement, log redaction, schema
  validation + repair loop (canned bad LLM outputs).
- **api/** — FastAPI `TestClient` against real Postgres, per-test
  transactions/rollback. Every route requires a session (M9): `conftest.py`'s
  `client` fixture creates a synthetic user and logs in once per test (real
  cookie + the CSRF header set as `TestClient` defaults), so this needed no
  changes to the ~10 pre-M9 test files that already use it. `anon_client`
  (no login, same CSRF default) covers the auth-negative tests —
  `test_auth.py`, `test_route_gating.py` (sweeps every route via
  `app.openapi()["paths"]`, not `app.routes` — this FastAPI version resolves
  included routers lazily, so `openapi()` is the version-agnostic source of
  truth), `test_deletion.py`.
- **workers/** — RQ tasks executed synchronously against real Redis;
  idempotency (run twice, same result) and retry paths. Two files
  (`test_parser_pipeline.py` in `api/`, and `test_log_redaction_pipeline.py`)
  build their own really-committed-rows `client`/session fixtures rather
  than the savepoint-scoped one (workers use their own DB session), so they
  need the login/CSRF treatment applied locally too.
- **Reel media extraction (M11)** — `unit/test_media_pipeline.py` drives the
  pure pipeline with fake downloader/transcriber/frame-reader adapters (no
  network, no yt-dlp/Whisper); `unit/test_media_adapters.py` runs the real
  yt-dlp adapter against a stand-in `yt_dlp` module and the real frame
  sampler/audio detection against a video generated in the test (these two
  need the optional `media` extra and skip with an explicit reason without
  it — CI doesn't install it); `workers/test_media_transcription.py` covers
  selection, persistence, search, and the vision reader's budget/audit
  against real Postgres. A sentinel string asserts no extracted text ever
  reaches progress output or stored errors.
- Provider adapters (Anthropic/OpenAI) tested against faked HTTP (`respx`);
  **no live API keys in tests or CI, ever.** MockProvider covers all AI
  pipelines.
- **Embeddings in tests are the deterministic mock provider**
  (`EMBEDDING_PROVIDER=mock`: sha256-token vectors, shared vocabulary ⇒ high
  cosine), so cluster memberships and near-duplicate groups are exactly
  assertable and no model download ever happens in a test. The worker
  analysis suite additionally wraps the whole embed → cluster → topics
  pipeline in a respx guard asserting **zero HTTP requests**. Real fastembed
  runs only in real use (and optionally in local e2e, where assertions stay
  provider-agnostic).

### Frontend — Vitest + React Testing Library (`frontend/tests/`)
Component behavior (reel-card states, filter bar, weight-slider re-rank math,
keyboard review hook) and API-client contract tests against mocked responses.

### End-to-end — Playwright (`e2e/specs/`)
Runs against the full compose stack with `AI_PROVIDER=mock`; CI additionally
sets `EMBEDDING_PROVIDER=mock` so the e2e job stays hermetic (locally the
default `local` fastembed provider works too — the first analysis run just
downloads the embedding model once). Critical path (spread across spec
files, not one giant test): upload synthetic ZIP → confirm self-DM →
extract → inbox counts → cluster → bulk-describe cluster → keyboard-review a
needs_context item → generate projects → adjust weights (observe re-rank) →
combine two ideas → advisor review → generate README → export Markdown/JSON.
`projects.spec.ts` (M7) covers generate → score bars → weight re-rank
(asserted with zero `/api/projects/generate` requests) → save weights →
compare → combine → detail field edit → milestone add/reorder → advisor
review with all five sections → regenerate advisor to v2.

Every non-auth route requires a session (M9), so a login has to happen
somewhere before any of the above can run. `e2e/global-setup.ts` performs
**one** real login (`e2e/auth-constants.ts`'s fixed test credential — seeded
by `python -m app.cli create-user`, see below) and saves the session cookie
as Playwright `storageState`; `playwright.config.ts` sets that as the
default `use.storageState` for every project, so every other spec file
needs zero auth-specific code, exactly as before M9. `specs/auth-deletion.spec.ts`
is the one file that overrides `storageState` to start logged out
(`test.use({ storageState: { cookies: [], origins: [] } })`) — it drives the
login UI itself (redirect-when-logged-out, wrong credentials, correct
credentials, logout revokes access immediately) and covers the raw-import
deletion scope (upload → typed-confirmation delete → verify it shows
`deleted` in the active list). Project deletion and the complete wipe are
covered at the API/service level in `backend/tests/api/test_deletion.py`
(see below) rather than through the UI, since a real wipe run against this
shared dev database would be destructive — see that file's docstring.

## Canonical commands

```bash
# Backend
cd backend && python -m ruff format --check . && python -m ruff check .
cd backend && python -m mypy app
cd backend && python -m pytest -q                  # full suite
cd backend && python -m pytest -q -m "not integration"   # unit-only (no services)

# Frontend
cd frontend && npm run lint
cd frontend && npx tsc --noEmit
cd frontend && npm run test -- --run

# E2E (compose stack must be up; every route needs a session — M9)
docker compose up -d --build
docker compose exec -T backend python -m app.cli create-user \
  --email e2e@example.com --password e2e-test-password-not-a-secret
cd e2e && npx playwright test
```

`make e2e` wraps all three steps above. The email/password must match
`e2e/auth-constants.ts` — `global-setup.ts` logs in with them before any spec
runs and fails loudly (not a mysterious redirect-to-`/login` in every spec)
if the account doesn't exist yet.

## CI (GitHub Actions, every push/PR)

- **backend** — ruff + mypy + pytest with pgvector-Postgres and Redis service
  containers, coverage report.
- **frontend** — eslint + tsc + vitest.
- **e2e** — compose up + seed the e2e test user (`create-user`) + Playwright
  critical path.
- **gitleaks** — secret scan of the diff and history.

A milestone is complete only when CI is green.

## Real-data workflow (M10; safety rules apply before then too)

This workflow is a manual runbook — an AI coding session must never execute
it (never access, request, or fabricate the real export; see
PRIVACY_SECURITY.md). Everything it depends on (verification report,
skip-categorized parser tolerance, the 5k-message performance benchmark) is
built and tested against synthetic fixtures only; this section is what a
human operator runs afterward, locally, with their own file.

**Synthetic vs. real-data results are always reported separately** — a
synthetic-fixture pass (automated, reproducible, safe to state in git
history/PRs) is not evidence that the real-export criteria below have been
met, and vice versa.

1. Place the real export ZIP under gitignored `var/` only — e.g.
   `var/private/<export>.zip` (`var/` is fully gitignored; confirm with
   `git check-ignore var/private/<export>.zip`, which should print the path).
   Never `git add` it, even accidentally.
2. Start the stack locally (never the VPS first) with the default
   `AI_PROVIDER=mock`:
   ```bash
   docker compose up -d
   docker compose exec backend python -m app.cli create-user \
     --email you@example.com   # skip if already seeded
   ```
   Open the app, log in, and use the **Import** screen to upload the ZIP —
   upload/scan/extract are fully offline regardless of the AI provider
   setting (see PRIVACY_SECURITY.md's network policy).
3. On the import detail page, read the **Verification report** section
   (`GET /api/imports/{id}/verification`): raw-vs-matched message-JSON
   counts, every skip category with a count and description, and — after
   selecting conversations and extracting — the duplicate-group summary by
   reason. Every category must be individually explained (a nonzero
   `unrecognized_message_path` count names the unrecognized directory —
   investigate what it is before treating the import as complete); none may
   be silently ignored.
4. Spot-check duplicate groups against known repeat shares: the
   verification report's per-reason counts are the aggregate signal: open
   the Inbox and look at the grouped cards (M4) for a sample of groups to
   confirm they're genuinely the same content.
5. Exercise all three deletion scopes **on a copy**, never the primary
   real-data stack, reusing the M9 backup/restore scratch-project pattern
   so a mistake can never touch the only copy:
   ```bash
   docker compose exec backend bash /app/scripts/backup.sh   # or your local equivalent
   docker compose -p inspiration-real-data-drill -f docker-compose.prod.yml \
     up -d postgres redis backend worker
   backend/scripts/restore.sh <db-backup> <data-backup>       # into the drill project
   # exercise raw-import deletion, project deletion, and the complete wipe
   # through that drill stack's UI/API; verify each report matches reality
   docker compose -p inspiration-real-data-drill -f docker-compose.prod.yml down -v
   ```
6. Performance sanity check: run the automated synthetic benchmark first
   (`cd backend && python scripts/benchmark_import.py`, targets: scan < 60s,
   extract < 180s, inbox p95 < 300ms — this step needs no real data and can
   run any time). Then, separately, note the real import's actual scan/
   extract durations from the Jobs UI as an informal real-world sanity
   check against the same targets — not a scripted pass/fail, since a real
   export's size and content mix aren't controlled like the fixture's.
7. Only after all of the above, optionally load real data into the VPS
   deployment (see DEPLOYMENT_PLAN.md's "Real data on production").
8. Any parser change motivated by something found in the real run ships
   with a new synthetic fixture in `backend/tests/fixture_builder.py`
   reproducing the quirk, plus a test — never a fix justified only by "I saw
   this in my real export."
