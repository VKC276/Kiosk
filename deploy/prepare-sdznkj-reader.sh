#!/usr/bin/env bash
# udev-helper för ffff:0035 (authorized_default=0).
#
# Interface syns först EFTER authorize. usbhid hinner då prova iface 1
# innan driver_override sätts — därför: ta bort usbhid-modulen, authorize,
# lås iface med driver_override, ladda tillbaka usbhid med ignore-quirk.
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
      # Valfri icke-tom sträng blockerar autobind
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

unload_usbhid() {
  # Om usbhid är modul: ta bort den så authorize inte triggar probe av iface 1.
  # Built-in usbhid går inte att rmmoda — då faller vi tillbaka till busy-loop.
  [[ -d /sys/module/usbhid ]] || return 1

  local d name
  shopt -s nullglob
  for d in /sys/bus/usb/drivers/usbhid/*:*; do
    [[ -e "${d}" ]] || continue
    name="$(basename "${d}")"
    [[ "${name}" == *:* ]] || continue
    echo -n "${name}" > /sys/bus/usb/drivers/usbhid/unbind 2>/dev/null || true
  done
  shopt -u nullglob

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
  if [[ -w /sys/module/usbhid/parameters/quirks ]]; then
    # Append quirk if module param accepts it live
    echo "${USBHID_QUIRK}" > /sys/module/usbhid/parameters/quirks 2>/dev/null || true
  fi
  logger -t vkc-kiosk "SDZNKJLTD: usbhid reloaded (quirk ${USBHID_QUIRK})"
}

unload_usbhid || true

# Authorize så interfaces dyker upp (utan usbhid = ingen farlig probe)
if [[ -w "${SYS}/authorized" ]]; then
  echo -n 1 > "${SYS}/authorized" 2>/dev/null || true
fi

# Busy-loop ~3s: sätt override / unbind även om unload misslyckades
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
# Efter reload: se till att vår enhet inte band till usbhid igen
protect_ifaces

logger -t vkc-kiosk "SDZNKJLTD reader prepared: ${DEVPATH}"
exit 0
