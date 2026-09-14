#!/usr/bin/env bash
# Tar bort systemd-tjänster och /usr/local/bin/vkc-kiosk.
# Raderar INTE kodkatalogen, config.json eller USB-udev om du inte sätter
# REMOVE_DIR=1 / REMOVE_READER=1.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Kör som root: sudo ./uninstall.sh" >&2
  exit 1
fi

systemctl disable --now vkc-kiosk-browser.service 2>/dev/null || true
systemctl disable --now vkc-kiosk.service 2>/dev/null || true
rm -f /etc/systemd/system/vkc-kiosk-browser.service
rm -f /etc/systemd/system/vkc-kiosk.service
rm -f /usr/local/bin/vkc-kiosk
systemctl daemon-reload

if [[ "${REMOVE_READER:-0}" == "1" ]]; then
  rm -f /etc/udev/rules.d/99-vkc-kiosk-input.rules
  echo "Tog bort udev-regler för kortläsare (REMOVE_READER=1)."
else
  echo "Behåller udev/USB-quirk för kortläsaren. Ta bort med REMOVE_READER=1 om du vill."
fi

if [[ "${REMOVE_DIR:-0}" == "1" ]]; then
  ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  echo "Tar bort ${ROOT_DIR}"
  rm -rf "${ROOT_DIR}"
fi

echo "VKC Kiosk avinstallerad från systemd."
