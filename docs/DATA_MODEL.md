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
| `imports` | id, source (default `instagram`), filename, storage_key, size_bytes, checksum_sha256, export_format (`json\|html_detected`), status (`uploaded→scanning→scanned→extracting→extracted→failed→deleted`), counts (jsonb), error, created_at | Original ZIP retained in private storage until deleted; checksum dedupes re-uploads. |
| `conversations` | id, import_id FK, thread_path, title, participant_names (jsonb), message_count, link_count, is_self_dm_candidate, is_selected, first_message_at, last_message_at | Populated by the scan pass — summaries only. |
| `messages` | id, conversation_id FK, sender_name, sent_at, text, share_link, share_text | **Persisted only for user-selected conversations** (two-pass privacy design). Index (conversation_id, sent_at). |

## Inspiration items

| Table | Columns (key) | Notes |
| --- | --- | --- |
| `items` | id, source (default `instagram`), import_id, conversation_id, message_id, url_raw, url_canonical, shortcode, item_type (`reel\|post\|tv\|story\|external\|unknown`), shared_at, share_text, adjacent_text, enriched_title, enriched_caption, enriched_author, context_note, status (`new\|needs_context\|reviewed\|archived\|ignored`), tags (text[]), duplicate_group_id FK, embedding vector(384), embedding_model, timestamps | Core entity. Partial unique index on shortcode. `enriched_*` kept separate from export-derived text and labeled by origin in the UI. |
| `duplicate_groups` | id, canonical_item_id FK, reason (`same_shortcode\|same_canonical_url\|near_text`), created_at | Exact groups at extract time; `near_text` groups from M6 embedding similarity. |
| `enrichment_attempts` | id, item_id FK, source (`oembed\|og`), status (`success\|blocked\|not_found\|error\|disabled`), http_status, fetched_title, fetched_caption, fetched_author, error, attempted_at | Full audit; cache: successes and permanent 404s are never re-fetched. |

## Analysis

| Table | Columns (key) | Notes |
| --- | --- | --- |
| `topics` | id, name, slug | |
| `item_topics` | item_id FK, topic_id FK, confidence | |
| `cluster_runs` | id, method, params (jsonb), embedding_model, status, created_at | Clustering is versioned; re-running creates a new run. |
| `clusters` | id, run_id FK, label, description_md, size | Labels AI-generated, user-editable. |
| `item_clusters` | item_id FK, cluster_id FK | |

## Projects & artifacts

| Table | Columns (key) | Notes |
| --- | --- | --- |
| `projects` | id, title, one_liner, summary_md, domains (text[]), difficulty, duration_estimate, datasets (jsonb), tech_stack (jsonb), skills_demonstrated (jsonb), risks (jsonb), scores (jsonb — sub-scores 0–10 each with rationale string), status (`idea\|shortlisted\|planned\|in_progress\|completed\|archived`), source (jsonb: item_ids, cluster_ids, prompt_version, provider, model), parent_project_ids (int[]), timestamps | `parent_project_ids` links combined ideas to both parents. Source item/cluster IDs are verified to exist. |
| `project_milestones` | id, project_id FK, title, description, sort_order, status (`todo\|doing\|done`), target_date | Roadmap tracking. |
| `artifacts` | id, project_id FK, kind (`readme\|resume_bullets\|portfolio_desc\|interview_answer\|tech_questions\|advisor_review`), content_md, payload (jsonb, nullable), provider, model, prompt_version, version, created_at | Versioned — regeneration appends v2, v3… `payload` holds the structured AdvisorReview data. |

## Operations

| Table | Columns (key) | Notes |
| --- | --- | --- |
| `jobs` | id, rq_job_id, kind (`demo\|import_scan\|import_extract\|enrich_batch\|embed_batch\|cluster\|topics\|generate_projects\|generate_artifact\|export_bundle\|delete_data`), status (`queued\|running\|succeeded\|failed\|cancelled`), progress, total, payload (jsonb — **IDs only**), error (redacted: exception class name, never message text), created_at, started_at, finished_at | Mirror of RQ state, DB is source of truth for the UI. `demo` is the M1 job-loop proof task. |
| `ai_requests` | id, job_id FK, provider, model, task, prompt_tokens, completion_tokens, est_cost_usd, latency_ms, status, created_at | **No prompt/response bodies** — cost observability without content. |

Sessions live in Redis (server-side), not in Postgres.

## Modeling rules

- **Score computation:** final project score = `Σ(weight_i × subscore_i)` from
  `settings.scoring_weights`, computed at read time. Changing weights re-ranks
  instantly; stored data never changes.
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
