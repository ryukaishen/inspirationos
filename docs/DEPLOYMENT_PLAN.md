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
- **Docker Desktop** was installed 2026-07-15; the compose stack and
  service-dependent tests (integration pytest, e2e) run locally now, in
  addition to CI.

## Production — small VPS with HTTPS (M9)

Target: a small Linux VPS (Hetzner / DigitalOcean class), personal use,
private by default, structured so it could be exposed publicly later.

- `docker-compose.prod.yml` is a **standalone** compose file — not an
  overlay merged with `docker-compose.yml`. Compose's default merge
  semantics for list-valued keys (`volumes`, `ports`) are additive across
  `-f` files rather than "replace", so an overlay risked silently keeping
  the dev bind mounts and published ports active in "production"; a
  standalone file also keeps the whole prod topology auditable in one
  place. `backend/Dockerfile.prod` / `frontend/Dockerfile.prod`:
  multi-stage builds (no bind mounts, no `--reload`/`next dev`),
  `restart: unless-stopped`, healthchecks gating startup order, named
  volumes for Postgres data (`pgdata_prod`) and `var/data` (`data_prod`).
- **Caddy** is the only exposed service (`Caddyfile`): automatic Let's
  Encrypt TLS for `APP_DOMAIN`, HTTP→HTTPS redirect. Backend, worker,
  Postgres, Redis have no `ports:` entry — reachable from other containers
  on the compose network, never from outside the host.
- Application access requires the app's single-user login (argon2id +
  Redis sessions) — TLS alone is not the access control.
- Secrets are environment variables on the VPS (root-owned `.env`, mode
  600); never in git or images. Required: `POSTGRES_PASSWORD`,
  `SECRET_KEY` (generate with
  `python -c "import secrets; print(secrets.token_urlsafe(48))"`),
  `APP_DOMAIN`, `ACME_EMAIL` — `docker-compose.prod.yml` refuses to start
  without them (`${VAR:?...}` required-variable syntax).

### Deploy workflow

1. `git pull` on the VPS (or build/push images elsewhere and pull).
2. `make deploy-build` — `docker compose -f docker-compose.prod.yml build`.
3. **Migrations are an explicit step**, never automatic on container start
   (unlike the dev image) — `make deploy-migrate`, first rehearsed against a
   copy of prod data in a scratch stack (see below).
4. `make deploy-up` — `docker compose -f docker-compose.prod.yml up -d`,
   then verify `curl -fsS https://$APP_DOMAIN/api/health` and the HTTPS
   certificate.

### Backups & restore

- `backend/scripts/backup.sh` (wrapped by `make backup`): nightly cron,
  gzipped `pg_dump` + gzipped tar of the `data_prod` volume, retained
  `BACKUP_RETENTION_DAYS` (default 14), restricted permissions (backups
  contain private data).
- **Restore is tested, not assumed:** `backend/scripts/restore.sh
  <db-backup.sql.gz> <data-backup.tar.gz>` (wrapped by `make restore
  DB_BACKUP=... DATA_BACKUP=...`) restores into an **isolated scratch
  compose project** (`-p inspiration-restore-drill`) — never the live
  stack — so a drill can never overwrite real data; verify row counts
  against the backup's own report, then tear down with
  `docker compose -p inspiration-restore-drill -f docker-compose.prod.yml
  down -v`.
- Rehearsed end-to-end during M9 under a separate scratch project
  (seed rows + a data-volume file → backup → full simulated disaster
  (`down -v`, volumes included) → fresh `up` → restore both the dump and
  the tar → row counts and file contents matched exactly). Caddy/TLS
  themselves need a real domain and weren't part of that local rehearsal.

### Monitoring & operations

- Structured JSON logs (post-redaction via `services/privacy/log_filter.py`)
  to files with rotation.
- Optional Sentry behind an env flag, content scrubbing enabled.
- `/api/health` checks DB + Redis and requires no session; uptime monitoring
  can poll it.
- Security hygiene on the VPS: ssh keys only, ufw allowing 80/443/ssh,
  unattended-upgrades, port-scan check after deploy confirming only Caddy is
  exposed.

## Real data on production

Only after the M10 local verification passes (see TESTING_STRATEGY.md). The
real export is uploaded through the app over HTTPS — never copied onto the VPS
out-of-band — so it lives only in the app's private storage volume and is
covered by the deletion machinery.
