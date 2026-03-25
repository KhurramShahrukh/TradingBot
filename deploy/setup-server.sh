#!/usr/bin/env bash
# Run once on a fresh Ubuntu 24.04 droplet (as root or with sudo).
# Prepares OS packages, optional firewall, and a dedicated user + app directory.

set -euo pipefail

APP_USER="${APP_USER:-tradingbot}"
APP_DIR="${APP_DIR:-/opt/tradingbot}"

echo "==> apt update && upgrade"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y

echo "==> Install Python, venv, pip, git"
apt-get install -y python3 python3-venv python3-pip git ufw

echo "==> Create user ${APP_USER} (system user, no login shell) if missing"
if ! id -u "${APP_USER}" &>/dev/null; then
  useradd --system --create-home --shell /usr/sbin/nologin "${APP_USER}"
fi

echo "==> Create ${APP_DIR} and set ownership"
mkdir -p "${APP_DIR}"
chown "${APP_USER}:${APP_USER}" "${APP_DIR}"

echo "==> ufw: allow SSH, enable (confirm with 'y' if prompted)"
ufw allow OpenSSH || true
ufw --force enable || true

echo "==> Done. Next: clone or copy the TradingBot repo into ${APP_DIR},"
echo "    run deploy/install-app.sh as ${APP_USER}, add .env, then deploy/install-systemd.sh"
