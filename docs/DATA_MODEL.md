# InspirationOS — Data Model

PostgreSQL 16 + pgvector, defined as SQLAlchemy 2.0 models with Alembic
migrations. Conventions: integer PKs, `created_at`/`updated_at` timestamps
(UTC), enums as Postgres enums, JSONB for structured payloads. **Job payloads
and `ai_requests` never contain message content — IDs and counts only.**

## Identity & configuration

| Table | Columns (key) | Notes |
| --- | --- | --- |
| `users` | id, email, password_hash (argon2id), created_at | Single user, but real auth. |
| `settings` | id (singleton), enrichment_enabled (bool, default **false**), enrichment_consent_at, enrichment_rate_limit, ai_provider (`anthropic\|openai\|mock`), model_overrides (jsonb), monthly_budget_usd, scoring_weights (jsonb), review_prefs (jsonb) | One row, seeded by the initial migration (id=1, enrichment off, provider `mock`); consent timestamp records the explicit opt-in. |
| `career_profile` | id (singleton), background_md, skills (jsonb), target_domains (text[]), experience_level, constraints (jsonb: time/compute), interests_md | Injected into generation prompts. |

## Import pipeline

| Table | Columns (key) | Notes |
| --- | --- | --- |
| `imports` | id, source (default `instagram`), filename (sanitized display name), storage_key (nullable — NULL for rejected HTML uploads, which keep no file), size_bytes (bigint), checksum_sha256, export_format (`json\|html_detected`), status (`uploaded→scanning→scanned→extracting→extracted→failed→deleted`), counts (jsonb — scan writes `total_entries`/`message_files`/`conversations`/`messages`/`links`; extract adds `extracted_messages`/`items`/`duplicate_groups`), error (static message or exception class name only), created_at | Original ZIP retained in private storage until deleted. Dedupe: **partial unique index** `uq_imports_checksum_active` on checksum_sha256 `WHERE status NOT IN ('failed','deleted')` — race-safe at the DB level; failed/deleted rows never block a re-upload. |
| `conversations` | id, import_id FK, thread_path, title, participant_names (jsonb), message_count, link_count, is_self_dm_candidate, is_selected, first_message_at, last_message_at, created_at | Populated by the scan pass — summaries only. Unique (import_id, thread_path) is the scan-idempotency upsert key; `thread_path` is derived from ZIP entry names (`inbox/<dir>`), identical across export layout variants. |
| `messages` | id, conversation_id FK, sender_name, sent_at, text, share_link, share_text, created_at | **Persisted only for user-selected conversations** (two-pass privacy design). Index (conversation_id, sent_at). Extract delete-and-reinserts per conversation, so re-runs converge and deselected conversations lose their rows. |

## Inspiration items

| Table | Columns (key) | Notes |
| --- | --- | --- |
| `items` | id, source (default `instagram`), import_id, conversation_id, message_id (source FKs nullable — M9 raw-import deletion may null them), url_raw, url_canonical, shortcode, item_type (`reel\|post\|tv\|story\|external\|unknown`), shared_at, share_text, adjacent_text, enriched_title, enriched_caption, enriched_author, enriched_source (`oembed\|og`, nullable), context_note, status (`new\|needs_context\|reviewed\|archived\|ignored`), tags (text[]), duplicate_group_id FK, embedding vector(384), embedding_model, timestamps | Core entity; one row per link occurrence (repeat shares stay separate rows — the "shared again" signal). Partial **non-unique** index on shortcode (`WHERE shortcode IS NOT NULL`) for dedupe lookups; the uniqueness invariant is the partial unique index on (message_id, url_canonical). `enriched_*` kept separate from export-derived text and labeled by origin in the UI — `enriched_source` (M5) records which source last wrote them, so the UI can label "via oEmbed"/"via OpenGraph" without joining `enrichment_attempts`. `status` defaults to `needs_context` at extract time when an item carries no `share_text`/`adjacent_text` at all (`services/enrichment/policy.py::initial_status_for`), `new` otherwise. `embedding vector(384)`/`embedding_model` (migration `0006`) hold the M6 semantic embedding of the item's combined real text; both stay NULL for textless items, and the embedding is **never serialized into any API response** (it is derived from private text). No ANN index at single-user scale — analysis reads the full matrix in-process. M4 adds `ix_items_fts`, a GIN index over `to_tsvector('english', coalesce(share_text,'') || ' ' || coalesce(adjacent_text,'') || ' ' || coalesce(context_note,''))` (`concat()` is not IMMUTABLE-eligible for a Postgres expression index), backing `GET /api/items?search=`. |
| `duplicate_groups` | id, canonical_item_id FK, reason (`same_shortcode\|same_canonical_url\|near_text`), created_at | Exact groups rebuilt from scratch by every extract run (canonical item = earliest share); `near_text` groups from M6 embedding similarity. |
| `enrichment_attempts` | id, item_id FK, source (`oembed\|og`), status (`success\|blocked\|not_found\|error\|disabled`), http_status, fetched_title, fetched_caption, fetched_author, error, attempted_at | Full audit (M5, migration `0005`); every attempted source is a row, never overwritten. Cache: a source with an existing `success`/`not_found` row for an item is never re-fetched; an item that already has `enriched_source` set (succeeded via an earlier source on a prior run) is skipped entirely. Partial index on `(item_id, source) WHERE status IN ('success','not_found')` backs the cache lookup. |

## Analysis

All added by migration `0006` (M6), purely additive. Membership FKs
(`item_topics.item_id`, `item_clusters.item_id`) are `ON DELETE CASCADE` so
the extract pass's delete-and-reinsert of items never blocks; analysis rows
are simply recomputed by re-running the pipeline.

| Table | Columns (key) | Notes |
| --- | --- | --- |
| `topics` | id, name, slug (unique) | Upserted by slug (`services/analysis/topics.py::slugify`), so re-running topic extraction never duplicates. |
| `item_topics` | item_id FK (cascade), topic_id FK (cascade), confidence — PK (item_id, topic_id) | Delete-and-reinserted per item by the topics job; confidence 0–1 from the LLM (max kept when two names slug identically). |
| `cluster_runs` | id, method, params (jsonb: distance_threshold, linkage, metric, min_cluster_size, near_duplicate_similarity_threshold), embedding_model, status (`running\|succeeded\|failed` enum `cluster_run_status`), created_at | Clustering is versioned; every execution creates a new run and older runs are retained. |
| `clusters` | id, run_id FK (cascade), label (nullable), description_md (nullable), size | Only clusters of ≥ 2 members are persisted (singletons stay unclustered). Label/description are AI-filled **only while NULL** and user-editable via `PATCH /api/clusters/{id}` — edits survive topic-job re-runs. |
| `item_clusters` | item_id FK (cascade), cluster_id FK (cascade) — PK (item_id, cluster_id) | |

## Projects & artifacts

All added by migration `0007` (M7), purely additive; `career_profile` (above)
is seeded empty (id=1) by the same migration so `GET /api/career-profile`
always has a row. `project_milestones`/`artifacts` FKs cascade on project
deletion.

| Table | Columns (key) | Notes |
| --- | --- | --- |
| `projects` | id, title, one_liner, summary_md, domains (text[]), difficulty, duration_estimate, datasets (jsonb), tech_stack (jsonb), skills_demonstrated (jsonb), risks (jsonb), scores (jsonb — sub-scores 0–10 each with rationale string), status (`idea\|shortlisted\|planned\|in_progress\|completed\|archived`), source (jsonb: item_ids, cluster_ids, prompt_version, provider, model), parent_project_ids (int[]), timestamps | `parent_project_ids` links combined ideas to both parents. Source item/cluster IDs are verified to exist. |
| `project_milestones` | id, project_id FK, title, description, sort_order, status (`todo\|doing\|done`), target_date | Roadmap tracking. |
| `artifacts` | id, project_id FK, kind (`readme\|resume_bullets\|portfolio_desc\|interview_answer\|tech_questions\|advisor_review`), content_md, payload (jsonb, nullable), provider, model, prompt_version, version, created_at | Versioned — regeneration appends v2, v3… `payload` holds the structured AdvisorReview data. |

## Operations

| Table | Columns (key) | Notes |
| --- | --- | --- |
| `jobs` | id, rq_job_id, kind (`demo\|import_scan\|import_extract\|enrich_batch\|embed_batch\|cluster\|topics\|generate_projects\|generate_artifact\|export_bundle\|delete_data`), status (`queued\|running\|succeeded\|failed\|cancelled`), progress, total, payload (jsonb — **IDs only**), error (redacted: exception class name, never message text), created_at, started_at, finished_at | Mirror of RQ state, DB is source of truth for the UI. `demo` is the M1 job-loop proof task. |
| `ai_requests` | id, job_id FK (nullable), provider, model, task, prompt_tokens, completion_tokens, est_cost_usd (numeric 10,6), latency_ms, status (`success\|invalid_output\|error` enum `ai_request_status`), created_at | **Content-free by construction — the table has no text columns at all.** One row per provider call including repair retries and failures, committed immediately so the audit survives job-failure rollbacks. `ix_ai_requests_created_at` backs the monthly-budget SUM (migration `0006`). |

Sessions live in Redis (server-side), not in Postgres.

## Modeling rules

- **Score computation:** final project score = `Σ(weight_i × subscore_i)` from
  `settings.scoring_weights`, computed at read time. Changing weights re-ranks
  instantly; stored data never changes. The five fixed dimensions (M7) are
  `career_alignment`, `technical_depth`, `originality`, `feasibility`,
  `recruiter_appeal` — defined once by the `ProjectScores` AI schema
  (`services/ai/schemas.py`) and reused as `SCORE_DIMENSIONS` in
  `services/generation/scoring.py`; the frontend's `lib/scoring.ts` mirrors the
  same constant and math so client-side re-rank matches the backend exactly.
  Weights are floats in `[0.0, 2.0]` (default `1.0` for an omitted dimension),
  validated by `scoring.validate_weights` and set via
  `PATCH /api/settings/scoring`.
- **Anti-hallucination invariant:** an item may enter AI-generation context
  only if at least one of share_text / adjacent_text / enriched_caption /
  context_note is non-empty. Enforced in the query that assembles generation
  input, not just in prompts.
- **Deletion scopes** (see PRIVACY_SECURITY.md): raw-import deletion removes
  the ZIP + conversations + messages (user chooses whether derived items
  survive with nulled source refs, or cascade); project deletion removes
  project + milestones + artifacts; complete wipe truncates everything except
  `users` and removes all stored files, then produces a verification report.
- Schema changes require an Alembic migration and an update to this document
  in the same change.
