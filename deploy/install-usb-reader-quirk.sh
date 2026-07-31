#!/usr/bin/env bash
# Installerar udev-quirk + snabb guard-tjänst för SDZNKJLTD USB Reader (ffff:0035).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RULE_SRC="${SCRIPT_DIR}/99-sdznkj-usb-reader.rules"
RULE_DST="/etc/udev/rules.d/99-sdznkj-usb-reader.rules"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Kör som root: sudo $0" >&2
  exit 1
fi

rm -f /etc/udev/rules.d/99-sdznkj-usb-reader.rules
cp "${RULE_SRC}" "${RULE_DST}"
chmod 644 "${RULE_DST}"
chmod +x "${SCRIPT_DIR}/usb-reader-iface1-guard.sh"

# Rendera och installera guard-tjänst
sed -e "s|__KIOSK_DIR__|${ROOT_DIR}|g" \
  "${SCRIPT_DIR}/vkc-usb-reader-guard.service.in" \
  > /etc/systemd/system/vkc-usb-reader-guard.service

udevadm control --reload-rules
udevadm trigger --subsystem-match=usb --action=add || true

systemctl daemon-reload
systemctl enable --now vkc-usb-reader-guard.service

echo
echo "Installerat:"
echo "  ${RULE_DST}"
echo "  vkc-usb-reader-guard.service (kör nu)"
echo
echo "Nästa steg:"
echo "  1) sudo reboot          # viktigt om USB redan dött (HC died)"
echo "  2) Efter boot: sätt i läsaren"
echo "  3) sudo dmesg -T | tail -40"
echo "     — ska visa Keyboard utan 'HC died'"
echo "  4) vkc-kiosk devices"
echo "  5) Sätt nameContains till \"USB Reader\" i config.json"
