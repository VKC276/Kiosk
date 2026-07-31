#!/usr/bin/env bash
# udev-helper för ffff:0035 (authorized_default=0).
# Interface syns ofta först EFTER authorize — därför: authorize + busy-loop
# som sätter driver_override / unbind innan usbhid hinner förstöra bussen.
set -uo pipefail

DEVPATH="${1:-}"
if [[ -z "${DEVPATH}" || ! -d "/sys${DEVPATH}" ]]; then
  echo "prepare-sdznkj-reader: ogiltig DEVPATH='${DEVPATH}'" >&2
  exit 1
fi

SYS="/sys${DEVPATH}"

protect_ifaces() {
  local iface name driver
  shopt -s nullglob
  for iface in "${SYS}"/*:*.*; do
    if [[ -w "${iface}/driver_override" ]]; then
      echo -n "do-not-bind" > "${iface}/driver_override" 2>/dev/null || true
    fi
    if [[ -e "${iface}/driver" ]]; then
      name="$(basename "${iface}")"
      driver="$(basename "$(readlink -f "${iface}/driver")")"
      echo -n "${name}" > "/sys/bus/usb/drivers/${driver}/unbind" 2>/dev/null || true
    fi
  done
  shopt -u nullglob
}

# Authorize så interfaces dyker upp
if [[ -w "${SYS}/authorized" ]]; then
  echo -n 1 > "${SYS}/authorized" 2>/dev/null || true
fi

# Busy-loop ~3s: fånga iface 0/1 direkt när de skapas
end_ms=$(( $(date +%s%3N) + 3000 ))
while (( $(date +%s%3N) < end_ms )); do
  protect_ifaces
  # Klart när både .0 och .1 syns (eller minst en) och saknar driver
  shopt -s nullglob
  ifaces=( "${SYS}"/*:*.* )
  shopt -u nullglob
  if (( ${#ifaces[@]} >= 1 )); then
    unbound=0
    for iface in "${ifaces[@]}"; do
      [[ -e "${iface}/driver" ]] || unbound=$((unbound + 1))
    done
    if (( unbound == ${#ifaces[@]} )); then
      break
    fi
  fi
  sleep 0.001
done

protect_ifaces
logger -t vkc-kiosk "SDZNKJLTD reader prepared: ${DEVPATH}"
exit 0
