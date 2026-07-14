# InspirationOS

A private, single-user AI-powered inspiration platform. It ingests an official
Instagram data export (ZIP/JSON), extracts every reel/post shared in your
self-DM along with its surrounding context, helps you review and semantically
cluster them, and generates original, career-targeted portfolio project ideas —
with transparent scoring, roadmaps, and career artifacts (READMEs, resume
bullets, interview answers).

Instagram is the *first* importer behind a `SourceImporter` abstraction; the
data model supports future sources (GitHub stars, YouTube Watch Later, X
bookmarks, Reddit saved, …) without schema changes.

> **Status: documentation phase.** The plan is approved; no application code
> exists yet. Implementation proceeds milestone-by-milestone per
> [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

## What it will do

1. Secure upload of the Instagram export ZIP (validated against zip-slip/zip-bomb; never extracted wholesale).
2. Conversation discovery with self-DM auto-detection (user-confirmed, never assumed).
3. Extraction of shared reel/post URLs with share text, adjacent messages, and timestamps.
4. Duplicate and near-duplicate grouping.
5. An "Inspiration Inbox" with search, filters, statuses, notes, and tags.
6. Semantic clustering *before* manual review, so related reels are handled together.
7. A keyboard-driven review queue for fast one-sentence context entry.
8. Consent-gated, per-item/batch public-metadata enrichment (off by default; import is fully offline).
9. AI project generation tailored to data science, healthcare AI, applied AI, and quantitative finance.
10. Transparent sub-scores with user-adjustable ranking weights (instant re-rank, no regeneration).
11. Project comparison, idea combination, and a Project Advisor critique mode.
12. Persistent project library with statuses and roadmap milestones.
13. README / portfolio / interview-answer / resume-bullet generation, with a fabricated-claims guard.
14. Markdown and JSON export.
15. Single-user authentication, redacted logging, recoverable background jobs, and full data deletion.

## Stack

Next.js (TypeScript, Tailwind, shadcn/ui) · FastAPI (Pydantic v2) · PostgreSQL +
pgvector (SQLAlchemy/Alembic) · Redis + RQ workers · fastembed local embeddings ·
Anthropic / OpenAI / Mock LLM providers behind one interface · Docker Compose ·
pytest / Vitest / Playwright · GitHub Actions.

## Documentation

| Document | Contents |
| --- | --- |
| [docs/PRODUCT_SPEC.md](docs/PRODUCT_SPEC.md) | Full product scope, constraints, required vs. optional features |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture, repo layout, jobs, parsing, enrichment, AI design |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Database schema and modeling rules |
| [docs/PRIVACY_SECURITY.md](docs/PRIVACY_SECURITY.md) | Privacy model, auth, logging redaction, deletion scopes |
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | 10 milestones with checkboxes, acceptance criteria, test commands |
| [docs/TESTING_STRATEGY.md](docs/TESTING_STRATEGY.md) | Fixture system, test layers, real-data workflow |
| [docs/DEPLOYMENT_PLAN.md](docs/DEPLOYMENT_PLAN.md) | Local dev and private VPS deployment, backups, monitoring |
| [CLAUDE.md](CLAUDE.md) | Working rules for AI coding sessions in this repo |

## Privacy, in one paragraph

This app handles private Instagram messages. Raw exports, uploaded files,
extracted messages, secrets, and generated user data live only under gitignored
paths (`var/`, `private-data/`, `.env`) and are never committed. Logs never
contain message bodies. Importing is fully offline; nothing contacts Instagram
unless enrichment is explicitly enabled *and* triggered per item or batch. The
app never asks for your Instagram password and never automates Instagram login.
See [docs/PRIVACY_SECURITY.md](docs/PRIVACY_SECURITY.md).

## Getting started

Not yet — Milestone 1 (Foundation) will introduce the Docker Compose dev stack
and the quickstart instructions here. Until then, there is nothing to run.
