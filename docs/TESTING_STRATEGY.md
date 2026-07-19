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
- **Cluster export** (`build_cluster_export_zip`, emitted as `clusters.zip`;
  M6) — one friend thread whose shares form two clearly-themed groups (high
  token overlap within a theme, none across) plus a near-duplicate text pair
  on distinct URLs. Deterministic clusters under both the mock and the real
  local embedding provider; kept separate from the rich export so M4/M5
  count assertions never shift. `clusters.spec.ts` uploads this one (each
  spec file uploads its own ZIP — checksum dedupe would 409 a re-upload).
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
  transactions/rollback.
- **workers/** — RQ tasks executed synchronously against real Redis;
  idempotency (run twice, same result) and retry paths.
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
downloads the embedding model once). Critical path:
login → upload synthetic ZIP → confirm self-DM → extract → inbox counts →
cluster → bulk-describe cluster → keyboard-review a needs_context item →
generate projects → adjust weights (observe re-rank) → combine two ideas →
advisor review → generate README → export Markdown/JSON → delete import →
verify gone.

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

# E2E (compose stack must be up)
docker compose up -d --build
cd e2e && npx playwright test
```

## CI (GitHub Actions, every push/PR)

- **backend** — ruff + mypy + pytest with pgvector-Postgres and Redis service
  containers, coverage report.
- **frontend** — eslint + tsc + vitest.
- **e2e** — compose up + Playwright critical path.
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
