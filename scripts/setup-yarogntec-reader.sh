#!/usr/bin/env bash
# Installerar alla systemändringar för YAROGNTEC / SDZNKJLTD USB-läsare (ffff:0035).
#
# Det här är den läsare som annars kraschar Raspberry Pi xHCI via usbhid på iface 1.
# Övriga keyboard-wedge-läsare behöver normalt INTE det här scriptet.
#
# Gör:
#   - usbcore.authorized_default=0 + usbhid.quirks i cmdline
#   - udev-regler + prepare-helper (driver_override, säker authorize)
#   - modprobe quirks
#   - pyusb i venv
#   - config.json: READER.backend=usb, vendor/product
#
# Användning:
#   sudo ./scripts/setup-yarogntec-reader.sh
#   sudo vkc-kiosk setup-reader
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
INSTALLER="${ROOT_DIR}/deploy/install-usb-reader-quirk.sh"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Kör som root: sudo $0" >&2
  exit 1
fi

if [[ ! -x "${INSTALLER}" ]]; then
  echo "Hittar inte ${INSTALLER}" >&2
  exit 1
fi

cat <<EOF
============================================================
 VKC Kiosk — YAROGNTEC / SDZNKJLTD USB-läsare (ffff:0035)
============================================================
Detta applicerar alla Pi-systemändringar som krävs för att
läsaren ska fungera utan xHCI-krasch (HC died).

Övriga läsare (vanlig HID keyboard-wedge) ska använda
  vkc-kiosk configure-reader
i stället — inte det här scriptet.
============================================================
EOF

"${INSTALLER}"

# Se till att CARD_PROCESSING har rekommenderade startvärden för den här läsaren
# (användaren kan finjustera med configure-card-reader.py).
if [[ -f "${ROOT_DIR}/config.json" ]]; then
  KIOSK_USER="$(stat -c '%U' "${ROOT_DIR}" 2>/dev/null || echo vkc)"
  sudo -u "${KIOSK_USER}" python3 - <<PY
import json
from pathlib import Path
p = Path("${ROOT_DIR}/config.json")
cfg = json.loads(p.read_text(encoding="utf-8"))
card = cfg.setdefault("CARD_PROCESSING", {})
card.setdefault("FORMAT", "HEX10")
card.setdefault("BYTE_ORDER", "REVERSED")
card.setdefault("NIBBLE_ORDER", "REVERSED")
card.setdefault("hexUidChars", 8)
card.setdefault("minIdLength", 5)
card.setdefault("maxIdLength", 10)
card.setdefault("decimalPadLength", 10)
p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("config.json: CARD_PROCESSING defaults för YAROGNTEC satta (om saknades).")
PY
fi

cat <<EOF

Nästa steg efter reboot:
  1) sudo reboot
  2) Koppla läsaren (gärna via USB2-hub)
  3) Finjustera kortformat (rekommenderas):
       vkc-kiosk configure-reader
     eller:
       ./venv/bin/python scripts/configure-card-reader.py
  4) sudo systemctl restart vkc-kiosk vkc-kiosk-browser
EOF
