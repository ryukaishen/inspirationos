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

> **Status: Milestones 1-9 implemented.** Import, parsing, inbox, enrichment,
> AI analysis, project generation, career artifacts, and single-user auth +
> deletion + private-VPS deployment all exist. Milestone 10 (real-data
> hardening) remains. Implementation proceeds milestone-by-milestone per
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
unless enrichment is explicitly enabled *and* triggered per item or batch, or you
run the `transcribe-reels` command yourself (it uses your own exported browser
cookies, keeps no videos, and transcribes locally). The app never asks for your
Instagram password and never automates Instagram login.
See [docs/PRIVACY_SECURITY.md](docs/PRIVACY_SECURITY.md).

## Getting started

### Full stack (Docker)

```bash
cp .env.example .env    # optional — the dev stack runs with built-in dev defaults
docker compose up --build
docker compose exec backend python -m app.cli create-user --email you@example.com
```

- Every page requires signing in (M9) — visit <http://localhost:3000>,
  you'll be redirected to `/login`; sign in with the account you just
  created.
- API health: <http://localhost:8000/api/health> (also proxied at
  `http://localhost:3000/api/health`) — the one route that never requires a
  session, for uptime monitoring.
- The backend container applies Alembic migrations on start; the worker
  consumes the `imports` / `enrichment` / `ai` queues.
- Production deployment (private VPS, HTTPS via Caddy, backups) uses
  `docker-compose.prod.yml` instead — see
  [docs/DEPLOYMENT_PLAN.md](docs/DEPLOYMENT_PLAN.md).

### Without Docker (e.g. the current Windows dev box)

```bash
# Backend — unit tests, lint, and type checks need no services;
# integration tests skip with an explicit message when Postgres/Redis are absent.
cd backend
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/python -m ruff format --check . && .venv/Scripts/python -m ruff check .
.venv/Scripts/python -m mypy app
.venv/Scripts/python -m pytest -q

# Frontend
cd frontend
npm install
npm run lint && npx tsc --noEmit && npm run test -- --run
npm run dev     # expects the backend on :8000 for live data

# E2E (requires the compose stack; CI runs it on every push/PR)
docker compose exec backend python -m app.cli create-user \
  --email e2e@example.com --password e2e-test-password-not-a-secret
cd e2e
npm install
npx playwright test
```

### Transcribe your saved reels (host only)

The export only contains reel *links*. To get what each reel actually says and
shows, run this once on your own computer with the app's Postgres reachable
(the compose stack up, or `DATABASE_URL` set in `backend/.env`) after you've
imported and selected your self-DM conversation:

```bash
cd backend
.venv/Scripts/pip install -e ".[media]"   # yt-dlp, faster-whisper, Pillow (one-time)
```

1. **Export your Instagram cookies** (Edge or Chrome): install a "Get
   cookies.txt LOCALLY"-style extension, log into instagram.com (a secondary
   account is safer), and export `cookies.txt` for instagram.com. Keep it
   outside the repo (or under `var/`) — it is a login credential.
   (`--cookies-from-browser firefox` also works; Chrome/Edge direct reading
   usually fails on Windows.)
2. Optional: set `ANTHROPIC_API_KEY` in `backend/.env` so reels with little
   speech get their on-screen text read (a few frames per reel, counted
   against the monthly AI budget). Without it, only speech is transcribed.
3. Try a small batch first, then the rest:

```bash
.venv/Scripts/python -m app.cli transcribe-reels --cookies C:/path/to/cookies.txt --dry-run
.venv/Scripts/python -m app.cli transcribe-reels --cookies C:/path/to/cookies.txt --limit 25
.venv/Scripts/python -m app.cli transcribe-reels --cookies C:/path/to/cookies.txt
```

It paces itself (~8s between reels), skips reels already done, stops if
Instagram starts refusing (refresh `cookies.txt`, wait, re-run), and deletes
each video right after transcribing it. Then open **Clusters → Run analysis**
so search, clustering, and project ideas use the new text. Details:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ("Reel media extraction") and
[docs/PRIVACY_SECURITY.md](docs/PRIVACY_SECURITY.md).

Enable the pre-commit hooks (ruff, gitleaks, frontend lint) once per clone:

```bash
backend/.venv/Scripts/pre-commit install
```
