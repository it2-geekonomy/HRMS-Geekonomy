#!/usr/bin/env bash
# Nightly Horilla HRMS full backup: Postgres dump + media files.
# Run on the DigitalOcean droplet (cron at midnight IST).
# Keeps the last KEEP_DAYS dated backups under BACKUP_DIR.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/hrms/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/hrms}"
DB_CONTAINER="${DB_CONTAINER:-horilla-database}"
APP_CONTAINER="${APP_CONTAINER:-horilla-hrms}"
DB_NAME="${POSTGRES_DB:-horilla}"
DB_USER="${POSTGRES_USER:-postgres}"
STAMP="$(TZ=Asia/Kolkata date +%Y%m%d_%H%M%S)"
LOG_FILE="${BACKUP_DIR}/backup.log"

DUMP_FILE="${BACKUP_DIR}/horilla_${STAMP}.dump"
MEDIA_FILE="${BACKUP_DIR}/horilla_media_${STAMP}.tar.gz"
BUNDLE_FILE="${BACKUP_DIR}/horilla_full_${STAMP}.tar"

mkdir -p "${BACKUP_DIR}"
cd "${COMPOSE_DIR}"

log() {
  echo "[$(TZ=Asia/Kolkata date -Iseconds)] $*" | tee -a "${LOG_FILE}"
}

# Load POSTGRES_* from .env if needed
if [[ -z "${POSTGRES_PASSWORD:-}" && -f "${COMPOSE_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC2046
  export $(grep -E '^POSTGRES_(DB|USER|PASSWORD)=' "${COMPOSE_DIR}/.env" | xargs) || true
  set +a
fi

if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  log "ERROR: POSTGRES_PASSWORD not set"
  exit 1
fi

log "Starting full backup (DB + media) stamp=${STAMP}"

# ---- 1) Database dump (custom format) ----
docker exec -e PGPASSWORD="${POSTGRES_PASSWORD}" "${DB_CONTAINER}" \
  pg_dump -U "${DB_USER}" -d "${DB_NAME}" -F c -f "/tmp/horilla_backup.dump"

docker cp "${DB_CONTAINER}:/tmp/horilla_backup.dump" "${DUMP_FILE}"
docker exec "${DB_CONTAINER}" rm -f /tmp/horilla_backup.dump
log "DB OK ${DUMP_FILE} ($(du -h "${DUMP_FILE}" | awk '{print $1}'))"

# ---- 2) Media files from app container volume ----
docker exec "${APP_CONTAINER}" \
  tar czf /tmp/horilla_media_backup.tar.gz -C /app/media .

docker cp "${APP_CONTAINER}:/tmp/horilla_media_backup.tar.gz" "${MEDIA_FILE}"
docker exec "${APP_CONTAINER}" rm -f /tmp/horilla_media_backup.tar.gz
log "Media OK ${MEDIA_FILE} ($(du -h "${MEDIA_FILE}" | awk '{print $1}'))"

# ---- 3) Optional single bundle (dump + media tar) for easy download ----
tar -cf "${BUNDLE_FILE}" -C "${BACKUP_DIR}" \
  "$(basename "${DUMP_FILE}")" \
  "$(basename "${MEDIA_FILE}")"
log "Bundle OK ${BUNDLE_FILE} ($(du -h "${BUNDLE_FILE}" | awk '{print $1}'))"

# Stable "latest" pointers for pull scripts
ln -sfn "${DUMP_FILE}" "${BACKUP_DIR}/horilla_latest.dump"
ln -sfn "${MEDIA_FILE}" "${BACKUP_DIR}/horilla_media_latest.tar.gz"
ln -sfn "${BUNDLE_FILE}" "${BACKUP_DIR}/horilla_full_latest.tar"

# ---- 4) Prune old dated backups ----
prune_glob() {
  local pattern="$1"
  find "${BACKUP_DIR}" -maxdepth 1 -type f -name "${pattern}" -mtime "+${KEEP_DAYS}" -print -delete \
    | while read -r f; do log "pruned ${f}"; done
}

prune_glob 'horilla_20*.dump'
prune_glob 'horilla_media_20*.tar.gz'
prune_glob 'horilla_full_20*.tar'

log "Done full backup"
