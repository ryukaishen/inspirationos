# InspirationOS — Architecture

## System overview

```
Browser ──HTTPS──> Caddy (VPS, auto-TLS)          [dev: no Caddy, Next dev server]
                     │
        ┌────────────┴─────────────┐
        │ Next.js (frontend)       │  App Router, TS, Tailwind + shadcn/ui,
        │  /api/* proxied ─────────┼─► TanStack Query, same-origin cookie auth
        └────────────┬─────────────┘
                     ▼
        ┌──────────────────────────┐     ┌─────────────┐
        │ FastAPI (backend)        │────►│ PostgreSQL   │  + pgvector extension
        │  Pydantic v2 schemas     │     │ (SQLAlchemy  │
        │  session auth (Redis)    │     │  + Alembic)  │
        └───────┬──────────────────┘     └─────────────┘
                │ enqueue (RQ)                 ▲
                ▼                              │
        ┌──────────────────────────┐           │
        │ Redis: queues            │           │
        │  imports/enrichment/ai   │           │
        └───────┬──────────────────┘           │
                ▼                              │
        ┌──────────────────────────┐           │
        │ RQ Worker(s)             │───────────┘
        │  import scan/extract,    │──► Storage abstraction (local FS now,
        │  enrichment, embeddings, │        S3-compatible later)
        │  clustering, LLM calls   │──► LLM providers: Anthropic | OpenAI | Mock
        └──────────────────────────┘
```

## Key choices and their rationale (interview-ready)

| Choice | Why |
| --- | --- |
| **RQ** over Celery | Minimal config, built-in `Retry` + failed-job registry, sync workers fit batch workloads, far simpler mental model. |
| **pgvector** | Embeddings + cosine search inside Postgres; no second datastore to run/backup/secure. |
| **fastembed** (ONNX, `BAAI/bge-small-en-v1.5`, 384-dim) | Local, no torch, no API key, small image; behind an `EmbeddingProvider` interface with optional OpenAI adapter. |
| **Agglomerative clustering** (scikit-learn, cosine distance threshold) | Deterministic, parameter-explainable; runs versioned as `cluster_runs`. |
| **shadcn/ui + Tailwind** | Accessible (Radix), composable, no runtime dependency lock-in. |
| **TanStack Query + 2s polling** for jobs | Single user; SSE is a later extension, polling is trivially reliable. |
| **Server-side Redis sessions** | Revocable on logout/restart-safe, httpOnly SameSite=Strict cookie. |

## Repository layout

```
inspiration-os/
├── docker-compose.yml            # dev: postgres(pgvector), redis, backend, worker, frontend
├── docker-compose.prod.yml       # prod (M9): standalone, not an overlay — see "Production
│                                 #   deployment" below for why merging with the dev file
│                                 #   was rejected. Only Caddy publishes ports.
├── Caddyfile                     # auto-TLS reverse proxy to frontend:3000 (M9)
├── .env.example / .gitignore / Makefile / .pre-commit-config.yaml
├── .github/workflows/ci.yml
├── docs/
├── backend/
│   ├── pyproject.toml            # fastapi, sqlalchemy2, alembic, rq, pydantic2, pgvector,
│   │                             #   fastembed, anthropic, openai, argon2-cffi, psycopg
│   ├── Dockerfile                # dev image (bind-mounted, --reload)
│   ├── Dockerfile.prod            # prod image (M9): multi-stage, no bind mounts, non-root
│   ├── scripts/                  # backup.sh, restore.sh (M9)
│   ├── alembic/                  # migrations
│   ├── app/
│   │   ├── main.py, config.py    # pydantic-settings from env
│   │   ├── api/                  # routers: auth, deps.py (get_current_user,
│   │   │                         #   require_csrf_header), imports, conversations, items,
│   │   │                         #   clusters, projects, career, artifacts, jobs, settings,
│   │   │                         #   export, privacy (wipe), health
│   │   │                         #   enqueue.py: shared jobs-row-then-enqueue helper
│   │   ├── models/               # SQLAlchemy models (see DATA_MODEL.md)
│   │   ├── schemas/              # Pydantic request/response models
│   │   ├── services/
│   │   │   ├── ingest/           # importer.py (SourceImporter interface), zip_safety.py,
│   │   │   │                     #   instagram/: export_reader.py, parser.py, encoding.py,
│   │   │   │                     #   links.py, selfdm.py
│   │   │   ├── enrichment/       # fetcher.py (oembed/og), policy.py (consent, rate limit)
│   │   │   ├── ai/               # provider.py, anthropic_provider.py, openai_provider.py,
│   │   │   │                     #   mock_provider.py, structured.py, prompts/, budget.py
│   │   │   ├── analysis/         # embeddings.py, clustering.py, topics.py, dedupe.py
│   │   │   ├── generation/       # projects.py, scoring.py, combine.py, artifacts.py, advisor.py
│   │   │   ├── storage/          # base.py (Protocol), local.py (+ clear()/count_files() for
│   │   │   │                     #   the wipe), (s3.py later)
│   │   │   ├── auth/             # passwords.py (argon2id), sessions.py (Redis, HMAC-signed
│   │   │   │                     #   cookie), rate_limit.py (login attempts) — M9
│   │   │   └── privacy/          # deletion.py (raw import/project/wipe), log_filter.py — M9
│   │   ├── workers/              # jobs.py (RQ tasks incl. run_delete_data), runner.py
│   │   └── cli.py                # create-user, wipe-data
│   └── tests/                    # unit/ api/ workers/ + fixtures/ + fixture_builder.py
├── frontend/
│   ├── next.config.ts            # rewrite /api/* -> backend (same-origin cookies);
│   │                             #   output: "standalone" for Dockerfile.prod
│   ├── Dockerfile.prod            # prod image (M9): multi-stage, Next's standalone bundle
│   ├── src/
│   │   ├── proxy.ts              # M9: redirect-to-/login UX guard (Next 16 renamed
│   │   │                         #   middleware.ts → proxy.ts) — not the security boundary
│   │   ├── app/                  # login, import, conversations, inbox, review, clusters,
│   │   │                         #   projects, projects/[id], settings
│   │   ├── components/  lib/
│   └── tests/                    # vitest + React Testing Library
└── e2e/                          # playwright.config.ts + auth-constants.ts + specs/
```

## Job processing

- Three queues — **imports**, **enrichment**, **ai** — so slow AI work never
  blocks an import. One worker consumes all three in dev; prod can scale
  per-queue.
- Every enqueue first creates a `jobs` row; the task updates
  status/progress/total as it runs. Frontend polls `GET /api/jobs/{id}`.
- **Recoverability:** exception-raising job failures are caught by each task
  and recorded in the `jobs` row (redacted error) — no automatic retry is
  actually wired up (**correction, 2026-07-23, see
  docs/REAL_DATA_VERIFICATION.md**: no `.enqueue()` call anywhere passes
  `retry=Retry(...)` or a custom `job_timeout`, despite this section
  previously claiming `Retry(max=3, interval=[10, 60, 300])` and a "Retry
  button in UI" — neither exists; `cli.py requeue-failed` was likewise never
  implemented, per M9's own note above). Worse, a **hard worker crash**
  mid-job (OOM-kill, host reboot, container crash — not a clean exception)
  leaves that job stuck at `status=running` **permanently**, confirmed for
  6+ minutes across multiple worker restarts in a live drill — there is
  currently no automated recovery and no UI/CLI path to retry or cancel a
  stuck job. A graceful restart (`docker compose restart worker`, SIGTERM)
  is unaffected: RQ's warm shutdown finishes the in-flight job first.
- **Idempotency:** tasks operate on IDs and upsert by natural key (items by
  shortcode/canonical URL; embeddings by item+model) — a crashed-and-retried
  job never duplicates data.
- Batch tasks chunk work (e.g., 100 items/transaction) for visible progress
  and resumability; cancellation flag checked between chunks.
- Job payloads contain **IDs only, never message content**.

## Upload & storage (M2)

**Endpoint shape:** `POST /api/imports/upload?filename=<display name>` takes the
ZIP as the **raw request body**, not multipart. Rationale: FastAPI/starlette
parse a multipart body in full before endpoint code runs, which would defeat
the requirement to reject oversized uploads *before the body is fully read*.
With a raw body the endpoint checks `Content-Length` first (413 with zero bytes
read) and, for chunked/lying clients, streams chunk-by-chunk to a spool file —
hashing (SHA-256) and counting as it goes — aborting the moment the cap is
crossed. `filename` is sanitized display metadata only (basename, control
chars stripped, 255-char cap); storage keys are server-generated UUIDs.

**Validation order** (all on the spool file, before anything is persisted):
size cap → checksum dedupe pre-check → ZIP validity → zip-slip entry names
(absolute paths, drive letters, `..` in `/` or `\` separators) → zip-bomb caps
(entry count, total declared uncompressed size, per-entry compression ratio
with a 1 MB floor) → export-format detection from entry **names** only.
Central-directory metadata is all that is read — the archive is never
extracted and no entry contents are opened at upload time.

**Transaction-safe acceptance sequence:** promote spool → stored key
(`os.replace`, same volume) → **one DB transaction** inserting the `imports`
row plus its single `import_scan` `jobs` row → enqueue. Failure mapping:
duplicate insert (partial unique index on active checksums — the authoritative,
race-safe dedupe) → 409 + promoted file deleted; any other DB failure → 500 +
promoted file deleted, no rows; enqueue failure → both rows `failed`, ZIP
retained for recovery. The spool file is removed in `finally` on every path;
cleanup-time storage errors never mask the primary error. Rejected archives
(slip/bomb/not-a-zip/unrecognized) leave zero rows and zero files; HTML exports
leave a `failed` row (`export_format=html_detected`, no file) so the rejection
is visible in the import list, with the actionable "re-request as JSON"
message.

**Storage abstraction:** `services/storage/base.py` defines a `Storage`
protocol (`spool_dir`, `save_file`, `open`, `exists`, `size`, `delete` — delete
is idempotent); `local.py` implements it rooted at `DATA_DIR` with a
resolved-path containment guard. An S3-compatible adapter can slot in later
without changing the upload flow.

**Scan job (M3, replaces the M2 stub):** `run_import_scan` streams the stored
ZIP (never extracted), parses one thread at a time, and persists
`conversations` summaries only — title, participants, message/link counts,
date range — upserted by `(import_id, thread_path)` so retries never
duplicate and `is_selected` survives a re-scan. Message bodies are read in
memory solely to count links; none are persisted. Owner detection
(`personal_information.json`, else the participant common to all threads)
flags self-DM *candidates*. `imports.counts` keeps the M2 keys
(`total_entries`, `message_files` — the frontend/e2e contract) and adds
`conversations`/`messages`/`links`. Failures mark both the job and the import
`failed` with the exception class name only.

**Selection & extract (M3):** `GET /api/imports/{id}/conversations` lists the
scanned summaries; `POST /api/imports/{id}/conversations/selection` takes
`{"conversation_ids": [...]}` with **replace semantics** (listed → selected,
all others deselected), inserts the `import_extract` jobs row (payload: IDs
only) and enqueues it — enqueue failure marks the job failed and returns 503,
mirroring the upload endpoint. A `failed` import with a stored file stays
selectable so a failed extract can be retried. `run_import_extract` re-reads
the retained ZIP and, per selected conversation in its own transaction
(visible progress, resumable), delete-and-reinserts `messages` + `items` —
re-running converges to identical rows, and deselected conversations lose
their rows, keeping the "messages exist only for selected conversations"
invariant. Exact duplicate groups are rebuilt from scratch across the import
at the end (canonical item = earliest share); `imports.counts` gains
`extracted_messages`/`items`/`duplicate_groups`.

## Instagram parsing

Export realities handled (each with a synthetic fixture):
- Path variants: `your_instagram_activity/messages/inbox/<thread>/message_N.json`
  (current) and legacy `messages/inbox/…`; multiple paginated
  `message_N.json` per thread (reverse-chronological).
- **Mojibake:** Instagram encodes UTF-8 bytes as latin-1 escapes. Every string
  passes through a **strict** `s.encode('latin-1').decode('utf-8')` round-trip
  that falls back to the original string on any `UnicodeError` — strict rather
  than `errors='ignore'`, which would silently delete characters from strings
  that are already correct Unicode. Emoji/non-ASCII names are explicit test
  cases.
- Message shapes: plain `content`, `share {link, share_text,
  original_content_owner}`, missing fields, unsent, media-only.
- HTML-format exports: detected and rejected with "re-request as JSON."

**Two-pass privacy-preserving pipeline:**
1. **Scan pass** (on upload): stream the ZIP (never fully extracted), read only
   `message_*.json` entries, persist *conversation summaries only* (title,
   participants, counts, date range). No message bodies in the DB yet.
2. **Extract pass** (after the user selects conversations): re-read the
   retained ZIP; persist messages + items for *selected conversations only*.
   The original ZIP stays in private storage so re-selection never requires
   re-upload.

**Self-DM detection:** owner name from
`personal_information/personal_information.json` when present, else the
participant common to all threads; a thread whose only participant is the
owner (or title == owner) is flagged a *candidate* — the user confirms in the
UI.

**Links:** collect `share.link` + regex-matched URLs in `content`.
Canonicalize: lowercase host, strip tracking params (`igsh`, `utm_*`, `si`),
shortcode from `/reel/{code}/`, `/p/{code}/`, `/tv/{code}/`; non-Instagram
URLs kept as `external`.

**Adjacent text:** `share_text` + same-sender messages within a configurable
±120s window, concatenated in order.

**Dedup:** same shortcode/canonical URL → exact duplicate group at extract
time (repeat timestamps kept as a signal). Near-duplicate *text* grouping via
embedding cosine threshold arrives with M6 and feeds the same
`duplicate_groups` mechanism.

## Inbox: browsing, search, filters (M4)

`GET /api/items` (`app/api/items.py`) is the read/search surface over
extracted items. **Grouped pagination:** a row is included only if
`duplicate_group_id IS NULL` or the item is its group's canonical item
(earliest share) — every duplicate group therefore renders as exactly one
entry, with `duplicate_count` computed via one follow-up `GROUP BY` query
over the page's group ids (not a per-row correlated subquery). This keeps
pagination totals and "a filter narrows results" counts exact and avoids a
duplicate group ever splitting across pages. `GET /api/items/facets` reuses
the same canonical-only restriction to populate filter UI (distinct
conversations, distinct tags with counts) but is **unfiltered** by the
current search/filter state — a static reference list, not a live
cross-filter recount.

**Full-text search:** `to_tsvector('english', coalesce(share_text,'') || ' '
|| coalesce(adjacent_text,'') || ' ' || coalesce(context_note,'')) @@
plainto_tsquery('english', :q)`, backed by the `ix_items_fts` GIN expression
index (migration `0004`). Uses `coalesce(...) || ...` rather than
`concat(...)`: `concat()` is not IMMUTABLE-eligible for a Postgres
expression index (confirmed against a live database — `CREATE INDEX`
fails with "functions in index expression must be marked IMMUTABLE").

**Editing:** `PATCH /api/items/{id}` applies only the fields present in the
request body (`exclude_unset=True` — a partial update, not a full replace).
`POST /api/items/bulk` applies a status, tag-union, and/or note across a
selected id list; tag writes always reassign a new list (`Item.tags` is a
plain `ARRAY(Text)`, not `MutableList`-tracked, so in-place `.append()` would
silently fail to persist). Both routes act on canonical items only for their
literal `item_ids` — **M5** adds an optional `duplicate_group_ids` field
(shared `_expand_item_ids` helper, also used by the enrich-trigger endpoint)
that expands to every member of the given groups, so a bulk note/tag/status
action can explicitly reach a whole "shared again" group, not just its
canonical (visible) row, while per-single-item editing still defaults to
canonical-only.

The frontend conversation-selector page (`/import/[id]/conversations`)
drives M3's existing selection API; every checkbox (self-DM candidate or
not) initializes from that conversation's own `is_selected`, which already
defaults to `false` server-side — so "never assume a self-DM candidate" and
"restore a prior partial selection on retry" both fall out for free without
special-casing. The inbox (`/inbox`) keeps all filter/search/page state in
the URL (`lib/item-filters.ts` — pure parse/serialize helpers, framework-free
and independently unit-tested) so it's shareable and drives Playwright
assertions directly against rendered counts.

## Metadata enrichment (consent-gated; see PRIVACY_SECURITY.md) — M5

**Consent gate:** `settings.enrichment_enabled`/`enrichment_consent_at`
(`app/api/settings.py`, `GET /api/settings` + `PATCH /api/settings/enrichment`)
— enabling for the first time (false→true) stamps the consent timestamp;
disabling keeps it as history. The endpoint only ever flips the flag — it
never enqueues anything, so toggling alone triggers zero requests. The
frontend gates the toggle behind a disclosure dialog
(`frontend/src/app/settings/page.tsx`).

**Trigger:** `POST /api/items/enrich` (`item_ids` and/or `duplicate_group_ids`,
expanded server-side by the same `_expand_item_ids` helper the bulk-update
endpoint uses) — 403s before any row is created if consent isn't given, so no
outbound request ever occurs while enrichment is off. Otherwise creates an
`enrich_batch` `jobs` row and enqueues `run_enrich_batch` onto the
`enrichment` queue, mirroring the imports.py job-row-then-enqueue convention.
One endpoint shape serves per-item, per-selection, and per-group actions; a
future per-cluster action (M6) needs no new code, just its own member
item_ids.

**Fetcher** (`app/services/enrichment/fetcher.py`): order per item is (1)
Instagram oEmbed, (2) OpenGraph tags from the public page — anonymous GET,
honest User-Agent, no login/cookies/headless/CAPTCHA. Transient
(connect/timeout) errors retry on a fixed backoff schedule (3 attempts:
0s/1s/2s); a definitive HTTP response (success, 404, or a block) is never
retried.

**Policy** (`app/services/enrichment/policy.py`): a `TokenBucket` rate limits
requests (`enrichment_requests_per_minute`, default 20/min ≈ 1 req/3s); a
`CircuitBreaker` trips after N consecutive `blocked` classifications
(`enrichment_circuit_breaker_threshold`, default 5) — scoped to one
`run_enrich_batch` call, so every new batch starts closed. Once tripped,
remaining sources are recorded `disabled` with zero further HTTP calls.
`classify_response` maps outcomes: 200 → `success`, 404 → `not_found`,
401/403/429/999 → `blocked`, exhausted retries → `error`. Every attempted
(non-cached) source is audited in `enrichment_attempts`; a source with an
existing `success`/`not_found` row is never re-fetched, and an item that
already succeeded via an earlier source on a prior run is skipped entirely
(not just per-source caching — see DATA_MODEL.md). On success, `enriched_*`
fields are updated (only non-null fetched values overwrite) and
`enriched_source` records which source produced them, so the UI can label
fields "via oEmbed"/"via OpenGraph". Limitations are documented in UI copy:
expect low hit rates; Instagram blocks anonymous access aggressively;
captions often unavailable.

**`needs_context` auto-assignment:** `policy.initial_status_for` (also used
by the M3 extract pipeline, `services/ingest/instagram/parser.py`) assigns
`needs_context` to a freshly extracted item with no `share_text`/
`adjacent_text` at all, `new` otherwise. `policy.is_eligible_for_generation`
is the anti-hallucination predicate from DATA_MODEL.md — implemented here
(not a not-yet-existing `generation/` package) since M5 tests it directly;
M6/M7 import this same function rather than re-implementing it.

## Fast review mode — M5

`frontend/src/app/review/page.tsx` fetches `GET /api/items?status=new&
status=needs_context&order=needs_context_first` (the `order` param is
additive to M4's `list_items` — default behavior/tests unaffected) and walks
a single loaded batch one item at a time. Keyboard handling is a pure keymap
(`frontend/src/lib/review-keyboard.ts::mapKeyToAction`, unit-tested) wired by
a thin hook (`use-review-keyboard.ts`): `j`/`k` navigate, `o` opens the
original in a new tab, `e` focuses the note field, `Enter` always saves the
note + sets status `reviewed` + advances (notes are one-sentence, so Enter
never needs to insert a newline), `s` skips, `1`–`5` set a status directly
(matching `ITEM_STATUSES` order). While the note field has focus, only
`Enter`/`Escape` are intercepted — every other key types normally, so
shortcuts never hijack note text.

## AI analysis pipeline (M6)

Three jobs on the `ai` queue, each following the standard job conventions and
triggered via `app/api/clusters.py` (`POST /api/analysis/embed|cluster|topics`,
job-row-then-enqueue, payloads carry IDs/scalars only). The frontend
`/clusters` page chains them (`lib/analysis-pipeline.ts`, polling
`/api/jobs/{id}`); each is also individually re-runnable and idempotent.

- **`run_embed_batch`** (`services/analysis/embeddings.py`): embeds each
  item's real text (`share_text` + `adjacent_text` + `enriched_caption` +
  `context_note`) into `items.embedding vector(384)`. Items with no text are
  never embedded — the anti-hallucination invariant starts here. Default
  scope = items missing an embedding for the active model; `force` re-embeds
  (e.g. after notes changed). `EmbeddingProvider` implementations: **local**
  fastembed (`BAAI/bge-small-en-v1.5`, lazy one-time ONNX model download — an
  infra fetch, no user data), **openai** (`dimensions=384` to fit the fixed
  column), **mock** (deterministic sha256-token vectors; tests/CI — shared
  vocabulary ⇒ high cosine, so memberships are exactly assertable).
- **`run_cluster`** (`services/analysis/clustering.py` + `dedupe.py`): fully
  local and deterministic (no LLM, no network) so it is runnable **before**
  review. Creates a new versioned `cluster_runs` row per execution
  (scikit-learn `AgglomerativeClustering`, cosine distance threshold
  `CLUSTER_DISTANCE_THRESHOLD`, average linkage); clusters below
  `min_cluster_size=2` are dropped (singletons stay unclustered; recorded in
  `params`). The same job then rebuilds **`near_text` duplicate groups** from
  scratch: cosine similarity ≥ `NEAR_DUPLICATE_SIMILARITY_THRESHOLD` among
  items not already in an exact group → connected components → groups with
  canonical = earliest share. Exact groups are never touched. At single-user
  scale similarity is computed in-process over the full matrix; pgvector is
  durable storage plus future ANN search, not a query dependency.
- **`run_topics`** (`services/analysis/topics.py`): per cluster (own
  transaction, visible progress), the fast-model tier runs `ClusterLabel`
  then `TopicExtraction` over member texts filtered by
  `is_eligible_for_generation` and truncated (`TOPICS_MAX_*` caps). Labels/
  descriptions are written **only when still NULL**, so user edits survive
  re-runs. Echoed item_ids are verified server-side (`GroundingError` on
  unknown ids); topics upsert by slug; `item_topics` delete-and-reinsert per
  item. A budget abort mid-batch keeps completed clusters.

## AI providers & structured output (M6 plumbing)

- `LLMProvider` (`services/ai/provider.py`): `generate_raw(task, instructions,
  context, schema, model) -> RawGeneration` (JSON text + token usage +
  latency). Implementations: **Anthropic** (`anthropic_provider.py`, official
  SDK, one forced tool call whose `input_schema` is the task's Pydantic JSON
  schema; defaults `claude-sonnet-5` generation / `claude-haiku-4-5` fast),
  **OpenAI** (`openai_provider.py`, `json_schema` response_format; `gpt-5.2` /
  `gpt-5-mini`), **Mock** (`mock_provider.py`, deterministic token-frequency
  outputs, always schema-valid, zero cost/IO; dev/CI default). Both real SDKs
  are httpx-based, so respx contract tests exercise them with no live keys.
- **Selection is configuration-only** (`factory.py`): effective provider =
  `settings.ai_provider` (DB singleton, seeded `mock`, switched via the
  Settings UI); env `AI_PROVIDER` is only the fallback when the row is
  missing. Models resolve as `settings.model_overrides`
  (`{"generation"|"fast": name}`) → provider env defaults. API keys are
  env-only — never in the DB, API payloads, or logs; a real provider without
  its key fails with `ProviderNotConfiguredError`.
- **Validation loop** (`structured.py::generate_validated`): budget check →
  provider call → JSON parse + schema validation; on failure ONE repair retry
  with the validation errors appended (sent only back to the same provider,
  never logged/stored); second failure raises `StructuredOutputError` → the
  job fails with the class name only. Every call — success, invalid output,
  or provider error — writes an `ai_requests` row (committed immediately so
  the audit survives job-failure rollbacks): provider/model/task/tokens/
  est-cost/latency/status, never content.
- **Cost controls** (`budget.py`): monthly spend = SUM(`est_cost_usd`) over
  the current UTC calendar month, cap = `settings.monthly_budget_usd` else
  `AI_MONTHLY_BUDGET_USD`; plus a per-job cumulative token budget
  (`AI_JOB_TOKEN_BUDGET`). Both checked before **each** call, so a batch
  aborts cleanly mid-way with completed work retained. The pricing table is
  a per-MTok estimate (mock = $0; unknown models assume Opus-tier rates).
- **Prompt templates** are versioned files in `services/ai/prompts/`
  (`<task>_v1.txt`, instructions only — never user data).
- M6 task schemas (`services/ai/schemas.py`): `TopicExtraction` (per-item
  assignments with confidences), `ClusterLabel`. M7/M8 add `ProjectIdeas`
  (sub-scores each with a one-line rationale), `CombinedProject`,
  `AdvisorReview` (commonality verdict, comparative strength, recruiter
  impact, prerequisites, week-by-week plan), `ReadmePlan`, `ResumeBullets`,
  `PortfolioDescription`, `InterviewAnswer`, `TechQuestions`.
- **Grounding:** generated output must cite source item/cluster IDs (echoed
  and verified server-side — implemented for topics in M6); only items with
  real text may enter generation context (enforced in code); M8 adds a
  post-generation regex flagging suspicious performance claims in artifacts.
- Scoring (M7) is hybrid: LLM sub-scores with rationales; final score computed
  at read time as `Σ(weight_i × subscore_i)` from user weights — instant
  re-rank.

## Project generation, combination, and advisor (M7)

Four jobs on the `ai` queue, all following the M6 conventions (own session,
idempotency guard, per-unit progress commits, redacted errors) and triggered
via `app/api/projects.py`. `app/api/enqueue.py::enqueue_job` is the shared
jobs-row-then-enqueue helper (extracted from `clusters.py`, which now imports
it) so `projects.py` doesn't duplicate the pattern.

- **`run_generate_projects`** (`services/generation/projects.py`):
  `POST /api/projects/generate` takes `cluster_ids`/`item_ids` (at least one
  required; clusters expand to their member items via `ItemCluster`) and an
  optional `count` (default/cap from `AppConfig.projects_default_count` /
  `projects_max_count`). Context assembly reuses
  `analysis.topics.build_llm_context_items` (the same
  `is_eligible_for_generation` gate M6 uses) plus cluster label/description
  summaries and the serialized career profile. One generation-tier
  `generate_validated` call returns the whole batch (`ProjectIdeas`); every
  idea's echoed `source_item_ids`/`source_cluster_ids` are verified against
  the allowed sets **before any project row is written** — a single
  ungrounded citation fails the whole batch (`GroundingError`, ids only). The
  API layer also 404s unknown cluster/item ids and 400s a selection with no
  eligible (real-text) items, so a bad request never reaches the worker.
- **`run_combine_projects`** (`services/generation/combine.py`): 
  `POST /api/projects/combine` takes exactly two existing `parent_project_ids`.
  The provider sees only the two parents' generated fields (title, one-liner,
  summary, domains, tech stack, skills) plus the career profile — no source
  ids are echoed by the model. The child's `source` is the **union** of the
  parents' stored `item_ids`/`cluster_ids`, and `parent_project_ids` links
  both parents.
- **`run_regenerate_project`** (`POST /api/projects/{id}/regenerate`):
  re-runs generation grounded on the project's own stored `source` ids and
  calls `apply_generated_fields` to replace only the generated fields (title,
  summary, scores, tech stack, etc.). Status, milestones, parent links, and
  existing advisor reviews are untouched — regeneration never resets
  user-owned state.
- **`run_advisor_review`** (`services/generation/advisor.py`,
  `POST /api/projects/{id}/advisor`, kind `generate_artifact`): context is the
  project's fields, a compact `{project_id, title, one_liner}` summary of the
  rest of the library (for comparative judgment), and the career profile. The
  validated `AdvisorReview` (commonality verdict + reasoning, comparative
  strength, recruiter impact, prerequisites, week-by-week plan) is stored as
  an `artifacts` row (`kind=advisor_review`): `payload` holds the structured
  data the UI renders from, `content_md` is a markdown rendering (reused by
  M8's export). `version = max(existing) + 1` per `(project_id, kind)` —
  earlier versions are never overwritten, so regenerating the review always
  keeps history.

**Frontend** (`app/projects/`, `app/projects/[id]/`,
`components/projects/`): the library page mirrors the clusters-page pattern
(dependent queries: list → pick → detail; job trigger + poll via
`refetchInterval`). Weight sliders (`components/ui/slider.tsx`, hand-rolled
`<input type="range">` like `switch`/`checkbox` — no Radix) write to page
state that a `useMemo` re-ranks through `lib/scoring.ts::rankProjects`; this
is pure client-side math with zero API calls, verified by both a vitest test
asserting no `fetch` call and an e2e test with a `page.on("request")`
listener. "Save weights" is a separate, explicit action
(`PATCH /api/settings/scoring`). The project-detail page composes
`MilestoneEditor` (CRUD + up/down reorder, `PUT
/api/projects/{id}/milestones/order` with server-side exact-permutation
validation) and `AdvisorPanel` (version picker over
`GET /api/projects/{id}/advisor`). Comparison (`CompareDialog`) is
client-side only — a CSS-grid of aligned sub-score rows over 2-3 selected
cards, no new endpoint.

## Career artifacts, claims guard, and export (M8)

**Career artifacts:** five kinds (`readme`, `resume_bullets`, `portfolio_desc`,
`interview_answer`, `tech_questions`) reuse the M7 `artifacts` table and
Advisor's exact versioning shape, but through **one generic endpoint pair and
one worker dispatcher** instead of five near-duplicate copies —
`ArtifactKind`/`JobKind.generate_artifact` already carried every value M8
needs since M7's migration, which pre-scaffolded this. `POST/GET
/api/projects/{id}/artifacts/{kind}` (`kind` a `CareerArtifactKind` path enum
that deliberately excludes `advisor_review`, which keeps its own `/advisor`
endpoints unchanged) mirror the advisor trigger/list pair; a convenience `GET
/api/projects/{id}/artifacts` returns the latest version of every generated
kind for a summary view. `workers/jobs.py::run_generate_career_artifact(job_id,
project_id, kind)` looks up a `CareerArtifactSpec` (task name, Pydantic
schema, markdown renderer) from `services/generation/career_outputs.py`'s
`CAREER_ARTIFACT_SPECS` dict keyed by `ArtifactKind`, then follows
`run_advisor_review`'s exact shape (idempotency guard, `generate_validated`,
`next_artifact_version`, redacted-error handling). Generation context is the
project's **own stored fields** (title, summary, tech stack, scores, …) plus
the career profile — not a re-fetch of raw source items, since the M7-stored
project fields are already the grounded, verified representation.

**Fabricated-claims guard:** `services/generation/claims_guard.py::find_claims`
is a plain-regex heuristic (achievement-verb-plus-number patterns, e.g.
"achieved 97%"; bare "N% <metric>" patterns; both skip a match preceded by a
hedge word like "target"/"goal"/"estimate") run against each new artifact's
rendered `content_md` right after generation. A match **never blocks**
generation — findings are stored in `artifacts.claims_flags` (JSONB list,
default `[]`) for the user's attention, surfaced in the UI as a warning badge
and included in exports. Each new prompt (`services/ai/prompts/
{readme,resume_bullets,portfolio_desc,interview_answer,tech_questions}_v1.txt`)
also carries an explicit instruction never to state an unmeasured performance
number as an already-achieved fact. Scoped to the five career-artifact kinds
only — `advisor_review` critiques an idea, not measured results.

**Export:** `POST /api/exports` (body: `{format: "markdown"|"json",
project_id: int|null}`, `project_id: null` = full-library) inserts an
`exports` row (`storage_key=NULL`) plus its `jobs` row in one transaction,
then enqueues onto the `ai` queue — mirroring `imports.py`'s accept sequence
so a request that never got queued never leaves a "ready" row behind.
`workers/jobs.py::run_export_bundle(job_id, export_id)` assembles a
`ProjectExport`/`LibraryExport` (`schemas/export.py` — the **published,
schema-stable JSON contract**, `schema_version` field; validated round-trip
via `ProjectExport.model_validate_json` rather than a separate `jsonschema`
dependency) from `services/generation/export.py::build_project_export`/
`build_library_export` (project fields + milestones + the latest version of
each generated artifact, via `career_outputs.py::latest_artifacts_by_kind`),
renders it to Markdown or JSON, and writes it through the `Storage`
abstraction (`exports/{uuid}.{md,json}`), filling in `storage_key`/
`size_bytes` (or `error`) on the `exports` row. `GET /api/exports/{id}`
reports readiness from that row alone; `GET /api/exports/{id}/download`
streams the file (`Content-Disposition: attachment`) through a small
`_iter_and_close` generator — a raw file object handed to `StreamingResponse`
is otherwise never explicitly closed, which leaked an open handle (visible as
a Windows file-lock on cleanup) until this was added. A project with zero
generated artifacts exports cleanly (`artifacts: []`).

**Frontend** (`components/projects/career-artifacts-panel.tsx`,
`export-panel.tsx`): the artifacts panel is a kind-tab selector over the
same version-picker/regenerate shape as `AdvisorPanel`, rendering
`content_md` directly (one generic renderer, not five bespoke per-kind
layouts) plus a claims-warning banner when `claims_flags` is non-empty. The
export panel's "Download" control is a plain same-origin `<a download>` to
`/api/exports/{id}/download` — no blob/JS-download plumbing needed, since a
normal anchor click already carries the session cookie. Both panels use the
new `lib/use-job-polling.ts` hook, which extracts the
mutation→jobId-state→`refetchInterval`-poll→callback block that M7 had
inlined three times (`projects/[id]/page.tsx`, `AdvisorPanel`,
`GenerateDialog`'s consumer) — justified now because M8 adds five more
independent job-polling sites (one per artifact kind) plus export.

## Auth, deletion, and log redaction (M9)

**Sessions:** `app/api/auth.py` (`POST /auth/login|logout`, `GET /auth/me`)
issues a server-side Redis session (`services/auth/sessions.py`):
`secrets.token_urlsafe(32)` token → Redis `session:{token}` = user id, sliding
TTL (`session_ttl_seconds`). The cookie value is `{token}.{hmac}` — an
HMAC-SHA256 of the token keyed by `AppConfig.secret_key`, giving that
previously-unused setting a real purpose (tamper-evidence only; revocation
is Redis-side, immediate on logout). Passwords are argon2id
(`services/auth/passwords.py`). Login is rate-limited by client IP
(`services/auth/rate_limit.py`, Redis fixed-window counter) — in production
only Caddy is internet-facing and every request reaches the backend via the
frontend container, so this is a global brake on login attempts rather than
a per-attacker one, an acceptable tradeoff at single-user scale.

**Route gating:** `app/api/__init__.py` wraps every router except `health`
and `auth` in an inner `protected_router` carrying
`dependencies=[Depends(get_current_user)]`; the outer `api_router` carries
`dependencies=[Depends(require_csrf_header)]` for every route including
`auth` itself. Both dependencies live in `app/api/deps.py`. FastAPI resolves
router-level dependencies before endpoint-level body parsing (confirmed
empirically), so an unauthenticated POST with no body still 401s rather than
being masked by a 422. The route-sweep test (`tests/api/test_route_gating.py`)
enumerates every path via `app.openapi()["paths"]` rather than walking
`app.routes` directly — this FastAPI version resolves included routers
lazily (`_IncludedRouter`), so `app.routes` is no longer a flat list; the
OpenAPI schema is the version-agnostic source of truth for "every registered
route" instead.

**CSRF:** `require_csrf_header` rejects any non-GET/HEAD/OPTIONS request
missing `X-Requested-With: XMLHttpRequest` — a header a cross-site
form/link/image can never set, alongside the session cookie's
`SameSite=Strict`. The frontend's `lib/api.ts` attaches this header to every
mutating call.

**Cookie `Secure` and the test transport:** the session cookie is always
`httponly, secure, samesite=strict` in real use — Chromium (including
Playwright) and other real browsers treat `http://localhost` as a secure
context and happily store/resend it there. FastAPI's `TestClient`, however,
talks plain `http://testserver` through Python's stdlib `http.cookiejar`,
which has no such exception and silently drops `Secure` cookies. Rather than
weaken the shipped default, `AppConfig.session_cookie_secure` (default
`True`) is set to `false` only inside the pytest process
(`tests/conftest.py` sets `SESSION_COOKIE_SECURE=false` before the first
`get_config()` call) — production and manual/Playwright-driven dev are
unaffected.

**Test-suite compatibility:** gating every route would have broken all
M2–M8 API tests, which share one `client` fixture. Instead of touching each
test file, `tests/conftest.py`'s `client` fixture now creates a synthetic
user and logs in once per test (real session cookie + the CSRF header set
as TestClient defaults), so the ~10 existing test files needed zero
changes. A new `anon_client` fixture (same CSRF default, no login) covers
the auth-negative tests. Two test files that build their own `client`
fixture around real-committed rows (`test_parser_pipeline.py`, worker tests)
needed the same treatment applied locally since they don't inherit
conftest's fixture.

**Deletion (`services/privacy/deletion.py`):**
- `delete_raw_import` (`POST /api/imports/{id}/delete`, typed confirmation =
  the filename): always removes the ZIP + conversations + messages;
  `cascade=false` nulls `items.import_id/conversation_id/message_id`
  (message_id nulled *before* messages are deleted, to satisfy the FK);
  `cascade=true` also deletes the items, first clearing
  `enrichment_attempts` (no `ON DELETE CASCADE`) and any touched
  `duplicate_groups` (null every member's `duplicate_group_id`, delete the
  group — safe even for a member outside this import, since groups rebuild
  from scratch on the next extract/cluster run).
- `delete_project` (`DELETE /api/projects/{id}`, typed confirmation = the
  title): existing cascades do the rest; export files are deliberately left
  for the wipe's filesystem sweep (see PRIVACY_SECURITY.md).
- `wipe_everything` (`POST /api/privacy/wipe`, typed confirmation = the
  account email): the `delete_data` `JobKind` (pre-scaffolded since M1,
  unused until now) runs `run_delete_data` — truncates every table except
  `users` in FK-safe order, clears every stored file
  (`Storage.clear()`/`count_files()`, new protocol methods), reseeds the
  `settings`/`career_profile` singletons, and writes a verification report
  (before/after row counts, files-remaining check) into the job's own
  `payload` — `schemas/job.py::JobRead` now exposes `payload`, so the
  existing job-polling UI surfaces the report with no new endpoint. Also
  reachable synchronously via `python -m app.cli wipe-data` (no
  Redis/worker needed) for a stuck deployment. `wipe_everything` takes a
  plain `Session`, not a job id — its test
  (`tests/api/test_deletion.py`) runs it against the ordinary
  savepoint-scoped `db_session` on purpose, never the real-commit
  `pg_engine` pattern other worker tests use, since this backend's Postgres
  is the same long-lived instance behind the dev compose stack and a real
  wipe would destroy whatever's there.

**Log redaction (`services/privacy/log_filter.py`):** a `logging.Filter`
installed on the root logger (`install_redacting_filter`, called from both
`main.py` and `workers/runner.py`) that strips named `extra=` attributes
matching the redacted-field list and regex-redacts `field=value`-shaped
substrings in rendered messages, as defense-in-depth against a future
accidental leak — the codebase already never logs content by construction
(exception-class-name-only errors, IDs-only job payloads). The pipeline-wide
test (`tests/workers/test_log_redaction_pipeline.py`) runs the real
scan→extract pipeline over the rich synthetic fixture with `caplog`
capturing everything, asserting none of the fixture's known plaintext
strings appear — a regression guard, since nothing in the exercised path
currently attempts to log them.

**CLI (`app/cli.py`):** `create-user` (seed/update the single account;
password via `getpass` if omitted) and `wipe-data` (the same
`wipe_everything` service, run synchronously). `requeue-failed`, mentioned
only in this doc's own repository-layout comment through M1–M8, was never
implemented and isn't in M9's scope either — removed from that comment
rather than left aspirational.

## Production deployment (M9)

`docker-compose.prod.yml` is a **standalone** compose file, not an overlay
merged with `docker-compose.yml` via `-f docker-compose.yml -f
docker-compose.prod.yml` as earlier drafts of this doc assumed. Compose's
default merge semantics for list-valued keys (`volumes`, `ports`) are
additive across `-f` files, not "replace" — an overlay risked silently
keeping the dev bind mounts and published ports active in "production" (a
real security footgun, confirmed while validating this milestone), not
merely a style preference. A standalone file also makes the whole prod
topology auditable in one place.

- `backend/Dockerfile.prod` / `frontend/Dockerfile.prod`: multi-stage
  builds, no bind mounts. The backend stage builds a venv, then copies only
  `/opt/venv` into a slim runtime layer running as a non-root `appuser`;
  `/app/var/data` is pre-created and `chown`'d to `appuser` **before** the
  volume mount — Docker copies a named volume's mount-point content
  (ownership included) from the image on first attach, so skipping this
  leaves the volume root-owned and unwritable by the non-root process
  (caught and fixed during the restore-drill rehearsal below). The frontend
  stage builds Next's traced `output: "standalone"` bundle
  (`next.config.ts`) and runs `node server.js` as a non-root user.
- Only `caddy` has a `ports:` entry (`80:80`, `443:443`); postgres, redis,
  backend, and worker are reachable from other containers on the compose
  network but never published to the host.
- Migrations are an explicit step (`make deploy-migrate` →
  `docker compose -f docker-compose.prod.yml run --rm backend alembic
  upgrade head`), never run automatically on container start — unlike the
  dev image's `sh -c "alembic upgrade head && uvicorn ..."`.
- `Caddyfile`: a global `email {$ACME_EMAIL}` block plus one site block
  (`{$APP_DOMAIN}` → `reverse_proxy frontend:3000`) — Caddy issues and
  renews the Let's Encrypt certificate and redirects HTTP→HTTPS
  automatically for any non-`localhost` site address.
- `backend/scripts/backup.sh` / `restore.sh`: nightly `pg_dump` (gzipped) +
  `tar` of the `data_prod` volume; restore runs into an **isolated scratch
  compose project** (`-p inspiration-restore-drill`), never the live
  stack, so a drill can never overwrite real data. Rehearsed end-to-end
  during this milestone under a separate scratch project
  (`-p inspiration-drill`): seeded rows + a file in the data volume →
  backup → `down -v` (full simulated disaster, volumes included) → fresh
  `up` → restore both the dump and the tar → row counts and file contents
  matched exactly. Caddy/TLS themselves aren't exercisable in a local
  drill (no real domain), so that part of the deploy path is verified by
  inspection and the `Caddyfile`'s syntax only, not a live rehearsal.

## Real-data hardening (M10)

**Parser tolerance for Meta's known thread categories:** `_MESSAGE_ENTRY_RE`
(`services/ingest/instagram/export_reader.py`) and `MESSAGE_JSON_RE`
(`services/ingest/format_detection.py`, the single source of truth for
`KNOWN_MESSAGE_CATEGORIES` — the parser imports it from there) match
`messages/<category>/<dir>/message_N.json` for `category` in `inbox`,
`message_requests`, `filtered_threads`, `archived_threads` — Meta's own
documented export categories, not something inferred from any real user's
file. `thread_path` becomes `<category>/<dir>`, so a `message_requests`
thread can never collide with an `inbox` thread of the same directory name
under the existing `(import_id, thread_path)` unique constraint; every other
category is scanned, selected, and extracted exactly like `inbox` with no
special-casing elsewhere in the pipeline.

**Nothing the scan pass encounters is silently dropped.** `ScanIssues`
(`export_reader.py`) is threaded through `thread_entries`/`_parse_message`/
`iter_threads` and counts, without ever storing content: a non-dict page
payload, a non-object raw message, a message missing `sender_name`/
`timestamp_ms`, and — via the separate `scan_unrecognized_message_paths`
pass over the full ZIP namelist — a message-shaped JSON path under a
`messages/<category>/` directory that isn't one of the four known
categories (plus a small capped list of the distinct unrecognized category
*names* seen, a structural path segment, never message content). `
run_import_scan` writes the result into `imports.counts["skipped"]`
(freeform JSONB — no migration needed).

**Import verification report:** `services/ingest/verification.py::
build_verification_report` turns `Import.counts` (already computed by scan/
extract) plus a fresh `duplicate_groups` query into `GET
/api/imports/{id}/verification` (`app/api/imports.py`) — raw-vs-matched-vs-
parsed message-JSON counts, the full skip breakdown with a static per-
category description, and a duplicate-group summary **by reason only**
(`same_shortcode`/`same_canonical_url`/`near_text` group/item counts — no
per-group canonical URLs or timestamps; individual groups stay the existing
Inbox grouped-card UI from M4). The frontend
(`components/imports/verification-report.tsx`, rendered on the import
detail page once a scan has run) is the answer to "how much of the export
did we actually use, and why not the rest" — never a silent gap. Available
with zeros/empties before a scan has run; no gating on import status.

**Performance benchmark:** `backend/tests/fixture_builder.py::
build_perf_export_zip` builds a ~5,000-message export across 20 threads
(share/plain-text/occasional-duplicate mix) — deliberately **not** part of
`main()`'s default fixture set (would slow every e2e run), built on demand
by `backend/scripts/benchmark_import.py` or the opt-in `--perf-messages`/
`--perf-out` CLI flags. The benchmark script calls `run_import_scan`/
`run_import_extract` directly (no RQ/worker needed) against a throwaway
`imports` row, times each, then measures `GET /api/items` p95 latency via
`TestClient` logged in as an **existing** account (`--email`/`--password` or
`BENCHMARK_EMAIL`/`BENCHMARK_PASSWORD` — the script never creates or deletes
accounts) against the documented targets (scan < 60s, extract < 180s, p95 <
300ms). It commits real rows against whatever `DATABASE_URL` is configured,
like `app/cli.py`, so it cleans up its own throwaway import
(`delete_raw_import(cascade=True)`) in a `finally` block, including on a
mid-setup failure between saving the ZIP and creating its `imports` row.
Never logs or prints message content — only counts and timings.

**Real-data workflow:** this milestone's tooling is fully exercised against
*synthetic* fixtures (including the 5k-message benchmark, which is
synthetic by design — the perf targets are defined against it, not the real
export). Running it against Adam's actual Instagram export is a separate,
manual step documented in TESTING_STRATEGY.md's "Real-data workflow"
section — never performed inside an automated coding session.
