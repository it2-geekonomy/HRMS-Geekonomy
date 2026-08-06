#!/usr/bin/env bash
# Copy latest Horilla backups from droplet -> QNAP NAS (via Tailscale LAN).
# Run after backup_full.sh (same cron, or chained).
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/hrms/backups}"
LOG_FILE="${BACKUP_DIR}/backup.log"

# --- edit these for your NAS ---
NAS_USER="${NAS_USER:-admins}"
NAS_HOST="${NAS_HOST:-10.0.0.178}"          # QNAP LAN IP (reachable via Tailscale routes)
NAS_PATH="${NAS_PATH:-/share/HRMS-Backups}" # create this folder on QNAP first
SSH_KEY="${SSH_KEY:-/root/.ssh/id_ed25519_nas}"

log() {
  echo "[$(TZ=Asia/Kolkata date -Iseconds)] $*" | tee -a "${LOG_FILE}"
}

if [[ ! -f "${SSH_KEY}" ]]; then
  log "ERROR: SSH key not found: ${SSH_KEY}"
  log "Create one and copy to NAS: ssh-copy-id -i ${SSH_KEY}.pub ${NAS_USER}@${NAS_HOST}"
  exit 1
fi

SSH_OPTS=(-i "${SSH_KEY}" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)

log "Syncing backups to ${NAS_USER}@${NAS_HOST}:${NAS_PATH}"

# Ensure remote folder exists
ssh "${SSH_OPTS[@]}" "${NAS_USER}@${NAS_HOST}" "mkdir -p '${NAS_PATH}'"

# Prefer rsync if available; else scp latest files
if command -v rsync >/dev/null 2>&1; then
  rsync -avz --timeout=120 \
    -e "ssh -i ${SSH_KEY} -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
    --include='horilla_*.dump' \
    --include='horilla_media_*.tar.gz' \
    --include='horilla_full_*.tar' \
    --include='horilla_latest.dump' \
    --include='horilla_media_latest.tar.gz' \
    --include='horilla_full_latest.tar' \
    --exclude='*' \
    "${BACKUP_DIR}/" \
    "${NAS_USER}@${NAS_HOST}:${NAS_PATH}/"
else
  scp "${SSH_OPTS[@]}" \
    "${BACKUP_DIR}/horilla_latest.dump" \
    "${BACKUP_DIR}/horilla_media_latest.tar.gz" \
    "${BACKUP_DIR}/horilla_full_latest.tar" \
    "${NAS_USER}@${NAS_HOST}:${NAS_PATH}/"
fi

log "NAS sync Done"
