#!/usr/bin/env bash
#
# Ночная резервная копия PostgreSQL.
#
# Запускается systemd-таймером из этого каталога. Снимает сжатый дамп, хранит
# последние KEEP_N дампов и по желанию копирует их за пределы машины.
#
#   sudo ./deploy/backup.sh
#
# Восстановление:
#   gunzip -c /opt/applytrack/backups/applytrack-20261109-030000.sql.gz \
#     | docker compose -f docker-compose.prod.yml exec -T db psql -U applytrack applytrack

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/applytrack/backups}"
KEEP_N="${KEEP_N:-14}"                      # две недели ночных дампов
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
PROJECT_DIR="${PROJECT_DIR:-/opt/applytrack}"
TIMESTAMP="$(date -u +%Y%m%d-%H%M%S)"
FILENAME="applytrack-${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

cd "$PROJECT_DIR"

echo "Снимаем резервную копию базы в ${BACKUP_DIR}/${FILENAME}"

# --clean --if-exists нужен, чтобы дамп можно было развернуть в базу, где
# схема уже есть.
docker compose -f "$COMPOSE_FILE" exec -T db \
    pg_dump --clean --if-exists --no-owner --no-privileges \
    -U "${POSTGRES_USER:-applytrack}" "${POSTGRES_DB:-applytrack}" \
  | gzip -9 > "${BACKUP_DIR}/${FILENAME}"

# Пустой дамп хуже, чем никакого дампа: он выглядит как успешный.
if [ ! -s "${BACKUP_DIR}/${FILENAME}" ]; then
    echo "ОШИБКА: резервная копия пустая" >&2
    exit 1
fi

gzip -t "${BACKUP_DIR}/${FILENAME}" || {
    echo "ОШИБКА: резервная копия повреждена" >&2
    exit 1
}

# Удаляем самые старые дампы, оставляя KEEP_N самых свежих.
ls -1t "${BACKUP_DIR}"/applytrack-*.sql.gz 2>/dev/null \
  | tail -n "+$((KEEP_N + 1))" \
  | xargs -r rm --

echo "Готово. На диске: $(du -h "${BACKUP_DIR}/${FILENAME}" | cut -f1)."

# Копия за пределы машины — раскомментируйте и укажите цель, если она нужна.
# rclone copy "${BACKUP_DIR}/${FILENAME}" remote:applytrack-backups/
