#!/usr/bin/env bash
# udev-helper för ffff:0035 (authorized_default=0).
#
# Interface syns först EFTER authorize. usbhid hinner då prova iface 1
# innan driver_override sätts.
#
# Strategi (tangentbord får INTE dö):
# 1) Skriv usbhid-ignore-quirk live innan authorize
# 2) Authorize
# 3) Busy-loop: driver_override + unbind på läsarens iface
# 4) Bara om INGET annat använder usbhid: tillfällig unload kring authorize
set -uo pipefail

DEVPATH="${1:-}"
if [[ -z "${DEVPATH}" || ! -d "/sys${DEVPATH}" ]]; then
  echo "prepare-sdznkj-reader: ogiltig DEVPATH='${DEVPATH}'" >&2
  exit 1
fi

SYS="/sys${DEVPATH}"
USBHID_QUIRK="0xffff:0x0035:0x4"
RELOAD_USBHID=0

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

apply_usbhid_quirk() {
  local quirks_file="/sys/module/usbhid/parameters/quirks"
  [[ -w "${quirks_file}" ]] || return 1
  # Ersätt/ange quirk-listan så denna VID:PID ignoreras vid probe
  echo "${USBHID_QUIRK}" > "${quirks_file}" 2>/dev/null || return 1
  logger -t vkc-kiosk "SDZNKJLTD: usbhid quirks set to ${USBHID_QUIRK}"
  return 0
}

usbhid_has_other_devices() {
  local d name
  shopt -s nullglob
  for d in /sys/bus/usb/drivers/usbhid/*:*; do
    [[ -e "${d}" ]] || continue
    name="$(basename "${d}")"
    [[ "${name}" == *:* ]] || continue
    # Annan enhet håller usbhid (t.ex. tangentbord) — unload är olämpligt
    shopt -u nullglob
    return 0
  done
  shopt -u nullglob
  return 1
}

unload_usbhid_if_idle() {
  [[ -d /sys/module/usbhid ]] || return 1
  if usbhid_has_other_devices; then
    logger -t vkc-kiosk "SDZNKJLTD: usbhid in use (keyboard?) — skip unload"
    return 1
  fi

  if modprobe -r usbhid 2>/dev/null || rmmod usbhid 2>/dev/null; then
    RELOAD_USBHID=1
    logger -t vkc-kiosk "SDZNKJLTD: usbhid unloaded before authorize"
    return 0
  fi
  return 1
}

reload_usbhid() {
  (( RELOAD_USBHID == 1 )) || return 0
  modprobe usbhid "quirks=${USBHID_QUIRK}" 2>/dev/null \
    || modprobe usbhid 2>/dev/null \
    || true
  apply_usbhid_quirk || true
  logger -t vkc-kiosk "SDZNKJLTD: usbhid reloaded"
}

# 1) Live-quirk först — påverkar inte ActiveJet/övriga HID
apply_usbhid_quirk || true

# 2) Unload bara om ingen annan HID-enhet är bunden
unload_usbhid_if_idle || true

# 3) Authorize → interfaces dyker upp
if [[ -w "${SYS}/authorized" ]]; then
  echo -n 1 > "${SYS}/authorized" 2>/dev/null || true
fi

# 4) Busy-loop: fånga iface innan/efter usbhid hinner binda
end_ms=$(( $(date +%s%3N) + 3000 ))
while (( $(date +%s%3N) < end_ms )); do
  protect_ifaces
  shopt -s nullglob
  ifaces=( "${SYS}"/*:*.* )
  shopt -u nullglob
  if (( ${#ifaces[@]} >= 2 )); then
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
reload_usbhid
protect_ifaces

logger -t vkc-kiosk "SDZNKJLTD reader prepared: ${DEVPATH}"
exit 0
