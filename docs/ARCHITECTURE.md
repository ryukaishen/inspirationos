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

## Instagram parsing

Export realities handled (each with a synthetic fixture):
- Path variants: `your_instagram_activity/messages/inbox/<thread>/message_N.json`
  (current) and legacy `messages/inbox/…`; multiple paginated
  `message_N.json` per thread (reverse-chronological).
- **Mojibake:** Instagram encodes UTF-8 bytes as latin-1 escapes. Every string
  passes through `s.encode('latin-1', 'ignore').decode('utf-8', 'ignore')`
  with safe fallback; emoji/non-ASCII names are explicit test cases.
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

## Metadata enrichment (consent-gated; see PRIVACY_SECURITY.md)

Order per item: (1) Instagram oEmbed, (2) OpenGraph tags from the public page
— anonymous GET, honest User-Agent, no login/cookies/headless/CAPTCHA. Token-
bucket rate limit (~1 req/3s default), timeouts, exponential backoff, circuit
breaker after N consecutive blocks, caching (successes and permanent 404s are
never re-fetched), every attempt audited in `enrichment_attempts`.
Limitations are documented in UI copy: expect low hit rates; Instagram blocks
anonymous access aggressively; captions often unavailable. Enriched fields are
stored separately (`enriched_*`) and labeled by source.

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
