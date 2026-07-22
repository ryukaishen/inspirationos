#!/usr/bin/env bash
# Restore drill (M9, see DEPLOYMENT_PLAN.md): restores a backup pair into an
# ISOLATED scratch compose project — never the live prod stack — so running
# a drill can never overwrite real data. Tear down afterwards with:
#   docker compose -p inspiration-restore-drill -f docker-compose.prod.yml down -v
set -euo pipefail

cd "$(dirname "$0")/../.."

DB_BACKUP="${1:?usage: restore.sh <db-backup.sql.gz> <data-backup.tar.gz>}"
DATA_BACKUP="${2:?usage: restore.sh <db-backup.sql.gz> <data-backup.tar.gz>}"
POSTGRES_USER="${POSTGRES_USER:-inspiration}"
POSTGRES_DB="${POSTGRES_DB:-inspiration}"
PROJECT="inspiration-restore-drill"
COMPOSE="docker compose -p $PROJECT -f docker-compose.prod.yml"

$COMPOSE up -d postgres redis
until $COMPOSE exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"; do
  sleep 2
done

gunzip -c "$DB_BACKUP" | $COMPOSE exec -T -e PGPASSWORD="${POSTGRES_PASSWORD:-}" postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"

$COMPOSE up -d backend worker
gunzip -c "$DATA_BACKUP" | $COMPOSE exec -T backend tar xzf - -C /app/var

echo "restore drill complete under compose project '$PROJECT'."
echo "Verify row counts against the backup's own report, then tear down with:"
echo "  docker compose -p $PROJECT -f docker-compose.prod.yml down -v"
