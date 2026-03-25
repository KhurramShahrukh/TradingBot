#!/usr/bin/env bash
# Add a swap file (most useful on 512 MB droplets). Run once with sudo.
# Default: 1G at /swapfile. Override: SWAP_SIZE=2G sudo -E bash deploy/add-swap.sh

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo bash $0" >&2
  exit 1
fi

SWAP_SIZE="${SWAP_SIZE:-1G}"
SWAP_FILE="${SWAP_FILE:-/swapfile}"

if [[ -f "${SWAP_FILE}" ]]; then
  echo "${SWAP_FILE} already exists; aborting." >&2
  exit 1
fi

echo "==> Creating ${SWAP_SIZE} swap at ${SWAP_FILE}"
fallocate -l "${SWAP_SIZE}" "${SWAP_FILE}"
chmod 600 "${SWAP_FILE}"
mkswap "${SWAP_FILE}"
swapon "${SWAP_FILE}"

if ! grep -qF "${SWAP_FILE}" /etc/fstab 2>/dev/null; then
  echo "${SWAP_FILE} none swap sw 0 0" >> /etc/fstab
fi

sysctl vm.swappiness=10
if ! grep -q vm.swappiness /etc/sysctl.conf 2>/dev/null; then
  echo "vm.swappiness=10" >> /etc/sysctl.conf
fi

swapon --show
free -h
echo "==> Done."
