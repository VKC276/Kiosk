#!/usr/bin/env bash
# Stänger av lokal Flask/Gunicorn och gamla units.
# Rör INTE USB-quirk, udev, cmdline eller READER i config.json.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mVarning:\033[0m %s\n' "$*" >&2; }

if [[ "${EUID}" -ne 0 ]]; then
  echo "Kör som root: sudo $0" >&2
  exit 1
fi

log "Stoppar gammal lokal kiosk-stack (Flask/Gunicorn), behåller kortläsar-udev"

if [[ -f /etc/systemd/system/mifare-reader.service ]] || systemctl list-unit-files --no-legend | grep -q '^mifare-reader.service'; then
  systemctl disable --now mifare-reader.service >/dev/null 2>&1 || true
  warn "Inaktiverade mifare-reader.service"
fi

# Gammalt autostart-desktop som krockar med systemd-browser
KIOSK_USER="$(stat -c '%U' "${ROOT_DIR}" 2>/dev/null || true)"
if [[ -n "${KIOSK_USER}" && "${KIOSK_USER}" != "root" ]]; then
  rm -f "/home/${KIOSK_USER}/.config/autostart/vkc-kiosk.desktop"
  rm -f "/home/${KIOSK_USER}/.config/autostart/mifare-reader.desktop"
fi

# Gunicorn/Flask som kan ligga kvar på 8081 efter byte till agent.py
pkill -f "${ROOT_DIR}/venv/bin/gunicorn" >/dev/null 2>&1 || true
pkill -f "gunicorn .*-b .*:8081" >/dev/null 2>&1 || true
pkill -f "wsgi:app" >/dev/null 2>&1 || true

if command -v fuser >/dev/null 2>&1; then
  fuser -k 8081/tcp >/dev/null 2>&1 || true
fi

echo "Kvar (avsiktligt): USB-quirk, udev, cmdline, config.json READER/CARD_PROCESSING"
echo "vkc-kiosk.service ska nu köra agent.py mot Cloudflare, inte gunicorn."
