#!/usr/bin/env bash
set -euo pipefail

if ! command -v pg_restore >/dev/null 2>&1; then
  echo "Ошибка: pg_restore не найден. Установите PostgreSQL client."
  exit 1
fi

BACKUP_FILE="${1:-}"
DATABASE_URL="${DATABASE_URL:-${2:-}}"

if [[ -z "$BACKUP_FILE" || -z "$DATABASE_URL" ]]; then
  echo "Использование: FORCE_RESTORE=YES DATABASE_URL='postgresql://...' ./scripts/restore_database.sh backups/file.dump"
  exit 1
fi

if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "Ошибка: файл не найден: $BACKUP_FILE"
  exit 1
fi

if [[ "${FORCE_RESTORE:-}" != "YES" ]]; then
  echo "Восстановление изменит целевую базу. Для подтверждения добавьте FORCE_RESTORE=YES."
  exit 1
fi

pg_restore --list "$BACKUP_FILE" >/dev/null
pg_restore \
  --dbname="$DATABASE_URL" \
  --clean \
  --if-exists \
  --no-owner \
  --no-acl \
  --exit-on-error \
  "$BACKUP_FILE"

echo "База восстановлена из: $BACKUP_FILE"
