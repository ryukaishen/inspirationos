# InspirationOS — Product Specification

## Vision & positioning

InspirationOS is an AI-powered inspiration/knowledge platform for a single
user (Adam), not "an Instagram parser." Instagram's official data export is
the **first importer** behind a `SourceImporter` abstraction; every inspiration
item carries a `source` field from day one so future importers (GitHub stars,
YouTube Watch Later, X bookmarks, Reddit saved posts, …) slot in without
schema changes. Only the Instagram importer is in scope for the complete
personal-use version.

The end state is a **complete, reliable personal application** used regularly
with Adam's real Instagram export — not a demonstration MVP. It is also his
flagship portfolio project: every architectural choice must be simple enough
to explain in a technical interview.

## The complete personal-use version (required scope)

### Import & extraction
1. **Secure Instagram ZIP/JSON upload** — streamed, size-capped, validated
   against zip-slip and zip-bomb attacks; HTML-format exports rejected with an
   actionable "re-request as JSON" message; the original ZIP is retained in
   private storage (so re-selection never needs re-upload) until deleted.
2. **Conversation discovery and selection** — all conversations listed with
   names, participant and message/link counts; the user chooses which to
   extract.
3. **Self-DM identification** — auto-detected via owner-name heuristics,
   flagged as a *candidate* and confirmed by the user, never assumed.
4. **Reel/post URL extraction** — from `share.link` fields and URLs embedded in
   message text; canonicalized (tracking params stripped, shortcode extracted,
   type classified: reel / post / tv / story / external).
5. **Context extraction** — share text, adjacent messages from the same sender
   within a time window, timestamps, and any export-embedded metadata.
6. **Duplicate & near-duplicate detection** — exact (same shortcode/canonical
   URL) at import time; near-duplicate text grouping via embedding similarity
   later. Repeat shares are kept as a "shared again" signal.

### Review
7. **Review queue** for items lacking context (`needs_context`), designed so
   the user does **not** have to describe every reel individually.
8. **One-click opening** of the original reel on instagram.com.
9. **Fast keyboard-assisted review** — j/k navigate, o open original, e edit,
   Enter saves a one-sentence context note and advances, s skip, number keys
   set status.
10. **Bulk classification and bulk status updates** — over selections,
    duplicate groups, or entire clusters.
11. **Clustering before manual review** — so 40 related reels can be described
    once at cluster level.

### Enrichment (consent-gated)
12. Import is **fully offline** — no network request ever occurs during
    upload/scan/extract. Optional public-metadata enrichment (oEmbed →
    OpenGraph, anonymous GET only) requires explicit opt-in with clear "your
    URLs will be sent over the network" disclosure, and runs **only per item,
    selection, group, or cluster — never as a global crawl**. Strict rate
    limits, timeouts, retries, caching, circuit breaker, full audit trail.
    Items that remain undescribed stay `needs_context`. Enriched fields are
    stored separately and labeled by source. **The app never fabricates what a
    reel is about.**

### AI analysis & generation
13. **Topic extraction and semantic clustering** — local embeddings
    (fastembed) stored in pgvector; versioned cluster runs; AI-generated
    cluster labels (editable).
14. **Original project generation** tailored to data science, healthcare AI,
    applied AI, and quantitative finance, grounded in the user's career
    profile and cited source items/clusters (IDs verified server-side).
15. **Transparent scoring** — per-project sub-scores (0–10) each with a
    one-line rationale; **adjustable ranking weights** re-rank instantly
    without regeneration.
16. **Project comparison** (side-by-side) and **idea combination** (two
    parents → new linked project).
17. **Project Advisor mode** — critiques generated ideas: commonality/
    originality verdict, comparative strength across the library,
    recruiter-impact reasoning, prerequisite concepts, week-by-week build
    order.
18. **Persistent project library** with statuses (idea → shortlisted → planned
    → in_progress → completed → archived) and **roadmap milestone tracking**.
19. **Career artifacts** per project: README plan, portfolio description,
    interview explanation, resume bullets, likely technical questions —
    versioned, regenerable, with a fabricated-performance-claims guard.
20. **Markdown and JSON export** — per project and full library, schema-stable.

### Platform
21. **Settings & career-profile personalization** — background, skills, target
    domains, experience level, constraints; AI provider/model/budget;
    enrichment consent; scoring weights.
22. **Configurable LLM providers** — Anthropic (default) and OpenAI adapters
    plus a deterministic no-key Mock provider; switching is configuration-only;
    all outputs validate against shared Pydantic schemas with a repair retry.
23. **Single-user authentication** (argon2 + Redis sessions) before any
    deployment.
24. **Data deletion** — raw-import data, individual projects, and complete
    account-data wipe with verification report.
25. **Reliability** — error handling; logging that excludes private message
    content; recoverable, idempotent background jobs; local dev via Docker
    Compose; private VPS production deployment; tests on synthetic fixtures;
    a documented workflow for safely testing with the real export locally.

## Hard constraints

- Never ask for the Instagram password; never automate login or bypass
  Instagram access controls; no cookies, headless browsers, or CAPTCHA
  handling anywhere.
- Do not assume a reel URL exposes its caption or video; enrichment is
  best-effort bonus data, never load-bearing.
- Never hallucinate a reel's subject; insufficiently described content is
  marked `needs_context` and excluded from generation input in code.
- Never commit raw exports, private messages, API keys, uploaded files, or
  generated user data to git.
- Avoid unnecessary enterprise complexity, but never replace reliable
  persistence, security, testing, or job processing with fragile shortcuts.
- Every milestone ends with working tests and explicit acceptance criteria;
  the system is built sequentially, never in one pass.

## Explicitly out of scope for the personal version (optional extensions)

Additional source importers (GitHub stars, YouTube, X, Reddit, Notion,
bookmarks, PDFs/papers); S3-compatible storage adapter; SSE/WebSocket live job
progress; more providers (Gemini, local models via Ollama); Whisper
transcription; Notion/Obsidian export; browser-extension/PWA capture; spaced
"revisit" reminders; GitHub repo scaffolding from a README; TOTP second
factor; multi-user support; media thumbnail extraction; topic-trend analytics;
public read-only portfolio mode (the deployment already supports going public
later — private by default).
