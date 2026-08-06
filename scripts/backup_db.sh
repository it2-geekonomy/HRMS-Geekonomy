#!/usr/bin/env bash
# Nightly Horilla HRMS Postgres backup (run on DigitalOcean droplet).
# Keeps the last KEEP_DAYS dumps under BACKUP_DIR.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/hrms/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/hrms/docker-compose.prod.yaml}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/hrms}"
CONTAINER="${DB_CONTAINER:-horilla-database}"
DB_NAME="${POSTGRES_DB:-horilla}"
DB_USER="${POSTGRES_USER:-postgres}"
STAMP="$(TZ=Asia/Kolkata date +%Y%m%d_%H%M%S)"
OUT_FILE="${BACKUP_DIR}/horilla_${STAMP}.dump"
LOG_FILE="${BACKUP_DIR}/backup.log"

mkdir -p "${BACKUP_DIR}"
cd "${COMPOSE_DIR}"

# Load POSTGRES_PASSWORD from .env if not already set
if [[ -z "${POSTGRES_PASSWORD:-}" && -f "${COMPOSE_DIR}/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  # Only export POSTGRES_* lines (ignore comments / bad lines)
  # shellcheck disable=SC2046
  export $(grep -E '^POSTGRES_(DB|USER|PASSWORD)=' "${COMPOSE_DIR}/.env" | xargs) || true
  set +a
fi

if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  echo "[$(TZ=Asia/Kolkata date -Iseconds)] ERROR: POSTGRES_PASSWORD not set" | tee -a "${LOG_FILE}"
  exit 1
fi

echo "[$(TZ=Asia/Kolkata date -Iseconds)] Starting backup -> ${OUT_FILE}" | tee -a "${LOG_FILE}"

docker exec -e PGPASSWORD="${POSTGRES_PASSWORD}" "${CONTAINER}" \
  pg_dump -U "${DB_USER}" -d "${DB_NAME}" -F c -f "/tmp/horilla_backup.dump"

docker cp "${CONTAINER}:/tmp/horilla_backup.dump" "${OUT_FILE}"
docker exec "${CONTAINER}" rm -f /tmp/horilla_backup.dump

# Optional: also dump a plain SQL gzip (easier inspect; larger)
# docker exec -e PGPASSWORD=... pg_dump -F p | gzip > "${BACKUP_DIR}/horilla_${STAMP}.sql.gz"

SIZE="$(du -h "${OUT_FILE}" | awk '{print $1}')"
echo "[$(TZ=Asia/Kolkata date -Iseconds)] OK ${OUT_FILE} (${SIZE})" | tee -a "${LOG_FILE}"

# Prune old dumps
find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'horilla_*.dump' -mtime "+${KEEP_DAYS}" -print -delete \
  | while read -r f; do echo "[$(TZ=Asia/Kolkata date -Iseconds)] pruned ${f}" | tee -a "${LOG_FILE}"; done

# Keep a stable "latest" symlink for easy pull scripts
ln -sfn "${OUT_FILE}" "${BACKUP_DIR}/horilla_latest.dump"

echo "[$(TZ=Asia/Kolkata date -Iseconds)] Done" | tee -a "${LOG_FILE}"
