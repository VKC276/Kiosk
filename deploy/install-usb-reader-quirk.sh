#!/usr/bin/env bash
# SDZNKJLTD USB Reader (ffff:0035) på Raspberry Pi:
# - Stoppa usbhid från att binda enheten (iface 1 dödar xHCI)
# - Appen läser iface 0 via PyUSB (READER.backend = "usb")
#
# OBS: usbhid är ofta inbyggd i Pi-kerneln → modprobe.d räcker INTE.
# Quirken måste även ligga i /boot/firmware/cmdline.txt (eller /boot/cmdline.txt).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
QUIRK_TOKEN="usbhid.quirks=0xffff:0x0035:0x4"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Kör som root: sudo $0" >&2
  exit 1
fi

install -d /etc/modprobe.d
cp "${SCRIPT_DIR}/modprobe.d/usbhid-sdznkj.conf" /etc/modprobe.d/usbhid-sdznkj.conf
chmod 644 /etc/modprobe.d/usbhid-sdznkj.conf

cp "${SCRIPT_DIR}/99-sdznkj-usb-permissions.rules" /etc/udev/rules.d/99-sdznkj-usb-permissions.rules
chmod 644 /etc/udev/rules.d/99-sdznkj-usb-permissions.rules

getent group plugdev >/dev/null || groupadd plugdev
KIOSK_USER="$(stat -c '%U' "${ROOT_DIR}" 2>/dev/null || echo vkc)"
if id -u "${KIOSK_USER}" >/dev/null 2>&1; then
  usermod -aG plugdev "${KIOSK_USER}" || true
fi

rm -f /etc/udev/rules.d/99-sdznkj-usb-reader.rules
systemctl disable --now vkc-usb-reader-guard.service 2>/dev/null || true
rm -f /etc/systemd/system/vkc-usb-reader-guard.service

# --- Kernel cmdline (krävs när usbhid är built-in) ---
CMDLINE=""
for candidate in /boot/firmware/cmdline.txt /boot/cmdline.txt; do
  if [[ -f "${candidate}" ]]; then
    CMDLINE="${candidate}"
    break
  fi
done

if [[ -n "${CMDLINE}" ]]; then
  if grep -q "usbhid.quirks=" "${CMDLINE}"; then
    # Ersätt befintlig usbhid.quirks=...
    sed -i -E "s/usbhid\.quirks=[^ ]+/${QUIRK_TOKEN}/g" "${CMDLINE}"
  else
    # cmdline.txt måste vara EN rad
    current="$(tr -d '\n' < "${CMDLINE}")"
    printf '%s %s\n' "${current}" "${QUIRK_TOKEN}" > "${CMDLINE}"
  fi
  echo "Uppdaterade ${CMDLINE} med ${QUIRK_TOKEN}"
else
  echo "VARNING: Hittade ingen cmdline.txt — lägg manuellt till: ${QUIRK_TOKEN}" >&2
fi

udevadm control --reload-rules
udevadm trigger --subsystem-match=usb || true
systemctl daemon-reload || true

if [[ -x "${ROOT_DIR}/venv/bin/pip" ]]; then
  sudo -u "${KIOSK_USER}" "${ROOT_DIR}/venv/bin/pip" install -q 'pyusb>=1.2,<2' || true
fi

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
echo "Installerat."
echo "Kontrollera cmdline:"
echo "  cat ${CMDLINE:-/boot/firmware/cmdline.txt}"
echo
echo "Reboot KRÄVS:"
echo "  sudo reboot"
echo
echo "Efter reboot:"
echo "  cat /proc/cmdline | tr ' ' '\\n' | grep usbhid"
echo "  # dmesg ska visa USB Reader UTAN hid-generic/Keyboard och UTAN HC died"
