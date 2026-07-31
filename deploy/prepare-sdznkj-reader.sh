#!/usr/bin/env bash
# Anropas av udev när ffff:0035 dyker upp (authorized_default=0).
# Sätter driver_override på alla interfaces, godkänner sedan enheten.
# Då kan PyUSB claima iface 0 utan att usbhid binder iface 1.
set -euo pipefail

DEVPATH="${1:-}"
if [[ -z "${DEVPATH}" ]]; then
  echo "prepare-sdznkj-reader: saknar DEVPATH" >&2
  exit 1
fi

SYS="/sys${DEVPATH}"
if [[ ! -d "${SYS}" ]]; then
  echo "prepare-sdznkj-reader: ${SYS} finns inte" >&2
  exit 1
fi

# Vänta tills interfaces syns i sysfs
for _ in $(seq 1 100); do
  shopt -s nullglob
  ifaces=("${SYS}"/*:*.*)
  shopt -u nullglob
  if (( ${#ifaces[@]} > 0 )); then
    break
  fi
  sleep 0.05
done

shopt -s nullglob
for iface in "${SYS}"/*:*.*; do
  if [[ -w "${iface}/driver_override" ]]; then
    echo -n "do-not-bind" > "${iface}/driver_override" || true
  fi
  # Om något redan bundit: försök unbind
  if [[ -e "${iface}/driver" ]]; then
    name="$(basename "${iface}")"
    driver="$(basename "$(readlink -f "${iface}/driver")")"
    echo -n "${name}" > "/sys/bus/usb/drivers/${driver}/unbind" 2>/dev/null || true
  fi
done
shopt -u nullglob

if [[ -w "${SYS}/authorized" ]]; then
  echo -n 1 > "${SYS}/authorized"
fi

logger -t vkc-kiosk "SDZNKJLTD reader prepared (overrides set, authorized=1): ${DEVPATH}"
