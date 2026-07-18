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
├── docker-compose.prod.yml       # prod overlay: caddy, restart policies (added in M9)
├── .env.example / .gitignore / Makefile / .pre-commit-config.yaml
├── .github/workflows/ci.yml
├── docs/
├── backend/
│   ├── pyproject.toml            # fastapi, sqlalchemy2, alembic, rq, pydantic2, pgvector,
│   │                             #   fastembed, anthropic, openai, argon2-cffi, psycopg
│   ├── alembic/                  # migrations
│   ├── app/
│   │   ├── main.py, config.py    # pydantic-settings from env
│   │   ├── api/                  # routers: auth, imports, conversations, items, clusters,
│   │   │                         #   projects, artifacts, jobs, settings, export, health
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
│   │   │   ├── storage/          # base.py (Protocol), local.py, (s3.py later)
│   │   │   └── privacy/          # deletion.py, log_filter.py
│   │   ├── workers/              # jobs.py (RQ tasks), runner.py
│   │   └── cli.py                # create-user, requeue-failed, wipe-data
│   └── tests/                    # unit/ api/ workers/ + fixtures/ + fixture_builder.py
├── frontend/
│   ├── next.config.ts            # rewrite /api/* -> backend (same-origin cookies)
│   ├── src/app/                  # login, import, conversations, inbox, review, clusters,
│   │   │                         #   projects, projects/[id], settings
│   │   ├── components/  lib/
│   └── tests/                    # vitest + React Testing Library
└── e2e/                          # playwright.config.ts + specs/
```

## Job processing

- Three queues — **imports**, **enrichment**, **ai** — so slow AI work never
  blocks an import. One worker consumes all three in dev; prod can scale
  per-queue.
- Every enqueue first creates a `jobs` row; the task updates
  status/progress/total as it runs. Frontend polls `GET /api/jobs/{id}`.
- **Recoverability:** `Retry(max=3, interval=[10, 60, 300])` for transient
  failures; permanent failures recorded in both the RQ failed registry and the
  `jobs` row (redacted error). Retry button in UI + `cli.py requeue-failed`.
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

## AI generation & structured output

- `LLMProvider.generate_structured(task, context, schema, budget) -> BaseModel`
  with three implementations: **Anthropic** (tool-use forced schema; default
  `claude-sonnet-5` generation, `claude-haiku-4-5` fast tasks), **OpenAI**
  (JSON-schema structured outputs), **Mock** (deterministic fixtures keyed by
  task + input hash; dev/CI default).
- Provider selection is configuration-only (env default, Settings override).
  All tasks are provider-agnostic and validate against the same Pydantic
  schemas.
- **Validation loop:** parse → on failure, one repair retry with validation
  errors appended → second failure fails the job. Malformed output is never
  silently accepted.
- **Prompt templates** are versioned files in `services/ai/prompts/`
  (instructions only — never user data); generated rows record
  `prompt_version`, provider, model.
- Task schemas: `TopicExtraction`, `ClusterLabel`, `ProjectIdeas` (sub-scores
  each with a one-line rationale), `CombinedProject`, `AdvisorReview`
  (commonality verdict, comparative strength, recruiter impact, prerequisites,
  week-by-week plan), `ReadmePlan`, `ResumeBullets`, `PortfolioDescription`,
  `InterviewAnswer`, `TechQuestions`.
- **Grounding:** ideas must cite source item/cluster IDs (echoed and verified
  server-side); only items with real text may enter generation context
  (enforced in code); a post-generation regex flags suspicious performance
  claims in artifacts.
- **Cost controls:** per-job token budget + monthly USD cap checked before
  each call; usage logged to `ai_requests` (tokens/cost/latency only — no
  content).
- Scoring is hybrid: LLM sub-scores with rationales; final score computed at
  read time as `Σ(weight_i × subscore_i)` from user weights — instant re-rank.
