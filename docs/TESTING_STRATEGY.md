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

1. Place the real export ZIP under gitignored `var/` only.
2. Run the full pipeline **locally** (never on the VPS first) with
   `AI_PROVIDER=mock` initially.
3. Compare the import-verification report (parsed counts vs. raw ZIP scan
   counts); investigate every category of skipped entry — none may be silent.
4. Spot-check duplicate groups against known repeat shares.
5. Exercise all three deletion scopes on a copy and verify the reports.
6. Only after local verification, optionally load real data into the VPS
   deployment.
7. Any parser change motivated by real data ships with a synthetic fixture
   reproducing the quirk.
