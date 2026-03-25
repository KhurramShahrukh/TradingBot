#!/usr/bin/env bash
# Install and enable the systemd unit. Run with sudo from the project root.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="${SERVICE_NAME:-tradingbot}"
APP_USER="${APP_USER:-tradingbot}"
UNIT_SRC="${ROOT}/deploy/tradingbot.service"
UNIT_DST="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi

if [[ ! -f "${UNIT_SRC}" ]]; then
  echo "Missing ${UNIT_SRC}" >&2
  exit 1
fi

echo "==> Install unit (APP_DIR=${ROOT}, User=${APP_USER})"
sed \
  -e "s|__APP_DIR__|${ROOT}|g" \
  -e "s|__APP_USER__|${APP_USER}|g" \
  "${UNIT_SRC}" > "${UNIT_DST}"

chmod 644 "${UNIT_DST}"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

echo "==> Status:"
systemctl status "${SERVICE_NAME}" --no-pager || true

echo "==> Logs: journalctl -u ${SERVICE_NAME} -f"
