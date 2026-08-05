#!/usr/bin/env bash
set -euo pipefail

if ! command -v pg_dump >/dev/null 2>&1; then
  echo "Ошибка: pg_dump не найден. Установите PostgreSQL client."
  exit 1
fi

DATABASE_URL="${DATABASE_URL:-${1:-}}"
if [[ -z "$DATABASE_URL" ]]; then
  echo "Использование: DATABASE_URL='postgresql://...' ./scripts/backup_database.sh"
  exit 1
fi

mkdir -p backups
FILE="backups/fleetai_$(date -u +'%Y-%m-%d_%H-%M-%S_UTC').dump"

pg_dump \
  --dbname="$DATABASE_URL" \
  --format=custom \
  --compress=9 \
  --no-owner \
  --no-acl \
  --file="$FILE"

pg_restore --list "$FILE" >/dev/null
sha256sum "$FILE" > "$FILE.sha256"
echo "Резервная копия создана: $FILE"
