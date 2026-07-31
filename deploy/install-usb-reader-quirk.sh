#!/usr/bin/env bash
# Installerar udev-quirk för SDZNKJLTD USB Reader (ffff:0035).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RULE_SRC="${SCRIPT_DIR}/99-sdznkj-usb-reader.rules"
RULE_DST="/etc/udev/rules.d/99-sdznkj-usb-reader.rules"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Kör som root: sudo $0" >&2
  exit 1
fi

# Ta bort gammal felaktig regel om den finns (bInterfaceNumber 01 matchade inte)
rm -f /etc/udev/rules.d/99-sdznkj-usb-reader.rules

cp "${RULE_SRC}" "${RULE_DST}"
chmod 644 "${RULE_DST}"

udevadm control --reload-rules
udevadm trigger --subsystem-match=usb --action=add || true

echo "Installerad: ${RULE_DST}"
echo
echo "Dra ur USB-läsaren, vänta 3 sekunder, sätt i igen."
echo "Kontrollera sedan:"
echo "  sudo dmesg -T | tail -30"
echo "  (ska visa Keyboard/USB Reader utan 'HC died')"
echo "  vkc-kiosk devices"
