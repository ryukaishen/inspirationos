#!/usr/bin/env bash
# Nightly backup (M9, see DEPLOYMENT_PLAN.md): pg_dump + tar of the private
# data volume, run against the production compose stack. Intended to run via
# cron on the VPS; both outputs are private data (contain everything the
# app's deletion machinery promises to erase), so BACKUP_DIR must stay
# root-owned/mode 600 like the .env file.
set -euo pipefail

cd "$(dirname "$0")/../.."

COMPOSE="docker compose -f docker-compose.prod.yml"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
POSTGRES_USER="${POSTGRES_USER:-inspiration}"
POSTGRES_DB="${POSTGRES_DB:-inspiration}"

mkdir -p "$BACKUP_DIR"
umask 077

$COMPOSE exec -T -e PGPASSWORD="${POSTGRES_PASSWORD:-}" postgres \
  pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
  | gzip > "$BACKUP_DIR/db-$TIMESTAMP.sql.gz"

$COMPOSE exec -T backend tar czf - -C /app/var data \
  > "$BACKUP_DIR/data-$TIMESTAMP.tar.gz"

echo "backup written:"
echo "  $BACKUP_DIR/db-$TIMESTAMP.sql.gz"
echo "  $BACKUP_DIR/data-$TIMESTAMP.tar.gz"

find "$BACKUP_DIR" -name '*.gz' -mtime "+$RETENTION_DAYS" -delete
