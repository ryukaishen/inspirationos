# InspirationOS — Deployment Plan

## Local development

- `docker compose up` runs: Postgres (pgvector image), Redis, FastAPI backend
  (reload), RQ worker, Next.js dev server. Works fully offline with
  `AI_PROVIDER=mock`.
- Config comes from `.env` (copied from `.env.example`).
- Makefile targets (`make dev / test / migrate / fixture / e2e`) wrap the
  canonical commands for CI and the VPS; on the Windows dev box (no `make`),
  run the underlying commands directly — they are listed in
  TESTING_STRATEGY.md.
- **Current machine caveat (2026-07-14):** the Windows 11 dev box has no
  Docker Desktop or WSL2. Until Docker Desktop is installed, the compose stack
  and service-dependent tests run only in CI. Everything else (unit tests,
  lint, typecheck, frontend tests) runs locally.

## Production — small VPS with HTTPS (M9)

Target: a small Linux VPS (Hetzner / DigitalOcean class), personal use,
private by default, structured so it could be exposed publicly later.

- `docker-compose.prod.yml` overlay: multi-stage-built images (no bind
  mounts), `restart: unless-stopped`, healthchecks gating startup order, named
  volumes for Postgres data and `var/data`.
- **Caddy** is the only exposed service: automatic Let's Encrypt TLS for
  `APP_DOMAIN`, HTTP→HTTPS redirect. Backend, worker, Postgres, Redis stay on
  the internal Docker network.
- Application access requires the app's single-user login (argon2 + Redis
  sessions) — TLS alone is not the access control.
- Secrets are environment variables on the VPS (root-owned `.env`, mode 600);
  never in git or images.

### Deploy workflow

1. Build and push images (or build on the VPS from a git checkout).
2. `docker compose -f docker-compose.yml -f docker-compose.prod.yml pull/build`
3. **Migrations are an explicit step** — `make deploy-migrate` (Alembic
   upgrade), first rehearsed against a copy of prod data in a scratch stack.
4. `docker compose ... up -d`, verify `/api/health`, verify HTTPS cert.

### Backups & restore

- Nightly cron: `pg_dump` + tar of `var/data`, retained N days, restricted
  permissions (backups contain private data).
- **Restore is tested, not assumed:** drill = restore into a scratch compose
  stack, run the app, verify row counts match the backup report.

### Monitoring & operations

- Structured JSON logs (post-redaction) to files with rotation.
- Optional Sentry behind an env flag, content scrubbing enabled.
- `/api/health` checks DB + Redis; uptime monitoring can poll it.
- Failed jobs visible in the UI with a Retry button; `cli.py requeue-failed`
  as the operator fallback.
- Security hygiene on the VPS: ssh keys only, ufw allowing 80/443/ssh,
  unattended-upgrades, port-scan check after deploy confirming only Caddy is
  exposed.

## Real data on production

Only after the M10 local verification passes (see TESTING_STRATEGY.md). The
real export is uploaded through the app over HTTPS — never copied onto the VPS
out-of-band — so it lives only in the app's private storage volume and is
covered by the deletion machinery.
