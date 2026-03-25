#!/usr/bin/env bash
# Copy SQLite and compound state to a backup directory. Run from project root or via cron.
# Example cron (daily 03:00): 0 3 * * * /opt/tradingbot/deploy/backup-state.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${BACKUP_DEST:-${ROOT}/backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "${DEST}/${STAMP}"

for f in trades.db compound_state.json; do
  if [[ -f "${ROOT}/${f}" ]]; then
    cp -a "${ROOT}/${f}" "${DEST}/${STAMP}/"
    echo "Backed up ${f}"
  fi
done

echo "Backup directory: ${DEST}/${STAMP}"
