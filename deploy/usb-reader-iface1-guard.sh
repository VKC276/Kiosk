#!/usr/bin/env bash
# Håller koll på SDZNKJLTD USB Reader (ffff:0035) och avbinder interface 1
# innan usbhid hinner hänga xHCI (~10 s efter inkoppling).
set -uo pipefail

VENDOR="ffff"
PRODUCT="0035"
INTERVAL_SEC="0.05"

log() { printf '%s %s\n' "$(date -Iseconds)" "$*"; }

block_iface() {
  local iface_path="$1"
  local name
  name="$(basename "${iface_path}")"

  # Hindra framtida bindning
  if [[ -w "${iface_path}/driver_override" ]]; then
    echo -n "do-not-bind" > "${iface_path}/driver_override" 2>/dev/null || true
  fi

  # Avbind från usbhid om den redan sitter där
  if [[ -e "${iface_path}/driver" ]]; then
    local driver
    driver="$(basename "$(readlink -f "${iface_path}/driver")")"
    if [[ -d "/sys/bus/usb/drivers/${driver}" ]]; then
      echo -n "${name}" > "/sys/bus/usb/drivers/${driver}/unbind" 2>/dev/null || true
      log "Unbind ${name} från ${driver}"
    fi
  fi
}

scan_once() {
  local iface parent vend prod
  for iface in /sys/bus/usb/devices/*:*.1; do
    [[ -d "${iface}" ]] || continue
    # Interface-nummer måste vara 1 (filen bInterfaceNumber)
    [[ -f "${iface}/bInterfaceNumber" ]] || continue
    [[ "$(cat "${iface}/bInterfaceNumber" 2>/dev/null | tr -d '[:space:]')" == "1" ]] || continue

    parent="$(dirname "${iface}")"
    vend="$(cat "${parent}/idVendor" 2>/dev/null | tr -d '[:space:]')"
    prod="$(cat "${parent}/idProduct" 2>/dev/null | tr -d '[:space:]')"
    [[ "${vend}" == "${VENDOR}" && "${prod}" == "${PRODUCT}" ]] || continue

    block_iface "${iface}"
  done
}

log "Startar USB-reader iface1-guard (ffff:0035)"
while true; do
  scan_once
  sleep "${INTERVAL_SEC}"
done
