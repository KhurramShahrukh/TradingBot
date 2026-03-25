#!/usr/bin/env bash
# Run from the TradingBot project root on the server (as the app user, e.g. tradingbot).
# Creates .venv and installs Python dependencies.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ ! -f "${ROOT}/requirements.txt" ]]; then
  echo "requirements.txt not found under ${ROOT}" >&2
  exit 1
fi

echo "==> Create venv at ${ROOT}/.venv"
python3 -m venv "${ROOT}/.venv"
# shellcheck source=/dev/null
source "${ROOT}/.venv/bin/activate"

echo "==> pip install"
pip install --upgrade pip
pip install -r "${ROOT}/requirements.txt"

echo "==> Ensure logs directory exists"
mkdir -p "${ROOT}/logs"

echo "==> Done. Copy config.json if needed, create .env (see .env.example), chmod 600 .env"
echo "    Then run: python test_run.py"
echo "    Then: sudo ./deploy/install-systemd.sh"
