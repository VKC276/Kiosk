#!/usr/bin/env bash
# SDZNKJLTD USB Reader (ffff:0035) på Raspberry Pi.
# Stoppar usbhid helt via usbcore.authorized_default=0 + udev.
# Appen läser iface 0 via PyUSB.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Båda behövs: authorized_default blockerar bind; usbhid.quirks är extra skydd
CMDLINE_TOKENS=(
  "usbcore.authorized_default=0"
  "usbhid.quirks=0xffff:0x0035:0x4"
)

if [[ "${EUID}" -ne 0 ]]; then
  echo "Kör som root: sudo $0" >&2
  exit 1
fi

install -d /etc/modprobe.d
cp "${SCRIPT_DIR}/modprobe.d/usbhid-sdznkj.conf" /etc/modprobe.d/usbhid-sdznkj.conf
chmod 644 /etc/modprobe.d/usbhid-sdznkj.conf

install -d /usr/local/lib/vkc-kiosk
cp "${SCRIPT_DIR}/prepare-sdznkj-reader.sh" /usr/local/lib/vkc-kiosk/prepare-sdznkj-reader.sh
chmod 755 /usr/local/lib/vkc-kiosk/prepare-sdznkj-reader.sh

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

CMDLINE=""
for candidate in /boot/firmware/cmdline.txt /boot/cmdline.txt; do
  if [[ -f "${candidate}" ]]; then
    CMDLINE="${candidate}"
    break
  fi
done

if [[ -z "${CMDLINE}" ]]; then
  echo "VARNING: Hittade ingen cmdline.txt" >&2
else
  current="$(tr -d '\n' < "${CMDLINE}")"
  # Ta bort gamla varianter av våra tokens
  current="$(echo "${current}" | sed -E 's/usbcore\.authorized_default=[^ ]+//g; s/usbhid\.quirks=[^ ]+//g; s/  +/ /g; s/^ //; s/ $//')"
  for token in "${CMDLINE_TOKENS[@]}"; do
    current="${current} ${token}"
  done
  printf '%s\n' "${current}" > "${CMDLINE}"
  echo "Uppdaterade ${CMDLINE}:"
  cat "${CMDLINE}"
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
echo "Reboot KRÄVS:"
echo "  sudo reboot"
echo
echo "Efter reboot, kontrollera:"
echo "  cat /proc/cmdline | tr ' ' '\\n' | grep -E 'authorized_default|usbhid.quirks'"
echo "  # Båda måste synas (authorized_default=0 är kritisk)"
echo
echo "Vid inkoppling:"
echo "  journalctl -t vkc-kiosk -n 20"
echo "  # ska innehålla: usbhid unloaded before authorize + reader prepared"
echo "  dmesg: INGEN usbhid 1-2.x:1.1-fel, INGEN HC died"
echo "Sedan: sudo systemctl restart vkc-kiosk && journalctl -u vkc-kiosk -f"
echo
echo "Om usbhid inte kan unloadas (in use / built-in) och felet kvarstår:"
echo "  echo 'blacklist usbhid' | sudo tee /etc/modprobe.d/blacklist-usbhid-vkc.conf"
echo "  sudo reboot"
echo "  # OBS: USB-tangentbord fungerar då inte (använd Pi Connect)."
