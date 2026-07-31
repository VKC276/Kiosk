#!/usr/bin/env bash
# SDZNKJLTD USB Reader (ffff:0035) på Raspberry Pi:
# - Stoppa usbhid från att binda enheten (iface 1 dödar xHCI)
# - Appen läser iface 0 via PyUSB (READER.backend = "usb")
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Kör som root: sudo $0" >&2
  exit 1
fi

install -d /etc/modprobe.d
cp "${SCRIPT_DIR}/modprobe.d/usbhid-sdznkj.conf" /etc/modprobe.d/usbhid-sdznkj.conf
chmod 644 /etc/modprobe.d/usbhid-sdznkj.conf

cp "${SCRIPT_DIR}/99-sdznkj-usb-permissions.rules" /etc/udev/rules.d/99-sdznkj-usb-permissions.rules
chmod 644 /etc/udev/rules.d/99-sdznkj-usb-permissions.rules

# plugdev för pyusb-behörighet
getent group plugdev >/dev/null || groupadd plugdev
KIOSK_USER="$(stat -c '%U' "${ROOT_DIR}" 2>/dev/null || echo vkc)"
if id -u "${KIOSK_USER}" >/dev/null 2>&1; then
  usermod -aG plugdev "${KIOSK_USER}" || true
fi

# Gamla ineffektiva unbind-regler/guard behövs inte med usbhid IGNORE
rm -f /etc/udev/rules.d/99-sdznkj-usb-reader.rules
systemctl disable --now vkc-usb-reader-guard.service 2>/dev/null || true
rm -f /etc/systemd/system/vkc-usb-reader-guard.service

udevadm control --reload-rules
udevadm trigger --subsystem-match=usb || true
systemctl daemon-reload || true

# Säkerställ pyusb i venv
if [[ -x "${ROOT_DIR}/venv/bin/pip" ]]; then
  sudo -u "${KIOSK_USER}" "${ROOT_DIR}/venv/bin/pip" install -q 'pyusb>=1.2,<2' || true
fi

# Sätt backend=usb i config om möjligt (jq eller python)
if [[ -f "${ROOT_DIR}/config.json" ]]; then
  sudo -u "${KIOSK_USER}" python3 - <<PY
import json
from pathlib import Path
p = Path("${ROOT_DIR}/config.json")
cfg = json.loads(p.read_text(encoding="utf-8"))
reader = cfg.setdefault("READER", {})
reader["backend"] = "usb"
reader["usbVendor"] = "0xffff"
reader["usbProduct"] = "0x0035"
reader["nameContains"] = reader.get("nameContains") or "USB Reader"
p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("config.json: READER.backend=usb")
PY
fi

echo
echo "Installerat usbhid-quirk + PyUSB-behörighet."
echo
echo "VIKTIGT: reboot krävs så usbhid laddas om med quirk:"
echo "  sudo reboot"
echo
echo "Efter reboot ska dmesg visa enheten UTAN hid-generic/Keyboard"
echo "(ingen 'HC died'). Appen läser via PyUSB."
echo "  sudo systemctl restart vkc-kiosk"
echo "  journalctl -u vkc-kiosk -f"
