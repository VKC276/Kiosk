#!/usr/bin/env bash
# Flytta WiFi till systemanslutning så lösenordet inte ligger i användarnyckelringen.
#
# Användning:
#   sudo vkc-kiosk fix-wifi
#   sudo vkc-kiosk fix-wifi "MittWifi" "losenordet"
#
# Kräver: NetworkManager (Pi OS Bookworm standard)
set -euo pipefail

# nmcli öppnar annars "less/more" och det ser ut som att scriptet stannar efter listan.
export PAGER=cat
export SYSTEMD_PAGER=cat
export NMCLI_NO_PAGER=1

log()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mVarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mFel:\033[0m %s\n' "$*" >&2; exit 1; }

if [[ "${EUID}" -ne 0 ]]; then
  die "Kör med sudo: sudo vkc-kiosk fix-wifi"
fi

command -v nmcli >/dev/null 2>&1 || die "nmcli saknas. Är NetworkManager installerat?"
systemctl is-active --quiet NetworkManager || die "NetworkManager körs inte."

log "Nuvarande anslutningar"
nmcli -c no -f NAME,UUID,TYPE,DEVICE,FILENAME connection show 2>/dev/null | cat || \
  nmcli -f NAME,UUID,TYPE,DEVICE connection show | cat || true
echo
nmcli -c no -t -f DEVICE,TYPE,STATE,CONNECTION device status 2>/dev/null | cat || true

echo
echo "============================================================"
echo " Nästa steg: ange SSID + lösenord (systemanslutning)."
echo " Eller kör: sudo vkc-kiosk fix-wifi \"SSID\" \"losenord\""
echo "============================================================"
echo

SSID="${1:-}"
PSK="${2:-}"

mapfile -t WIFI_SSIDS < <(nmcli -c no -t -f SSID device wifi list 2>/dev/null | sed '/^$/d' | sort -u || true)
ACTIVE_SSID="$(nmcli -c no -t -f ACTIVE,SSID device wifi list 2>/dev/null | awk -F: '$1=="yes"{print $2; exit}' || true)"

if [[ ${#WIFI_SSIDS[@]} -gt 0 ]]; then
  echo "Synliga nät:"
  i=1
  for ssid in "${WIFI_SSIDS[@]}"; do
    mark=""
    [[ "${ssid}" == "${ACTIVE_SSID}" ]] && mark=" (aktiv)"
    printf '  %2d) %s%s\n' "${i}" "${ssid}" "${mark}"
    i=$((i + 1))
  done
  echo
fi

DEFAULT_SSID="${ACTIVE_SSID:-}"
if [[ -z "${DEFAULT_SSID}" ]]; then
  DEFAULT_SSID="$(nmcli -c no -t -f NAME,TYPE connection show 2>/dev/null | awk -F: '$2=="802-11-wireless"{print $1; exit}' || true)"
fi

if [[ -z "${SSID}" ]]; then
  if [[ ! -t 0 ]]; then
    die "Ingen SSID angiven och stdin är inte en terminal. Kör: sudo vkc-kiosk fix-wifi \"SSID\" \"losenord\""
  fi
  printf 'SSID [%s]: ' "${DEFAULT_SSID}" >&2
  read -r SSID || true
  SSID="${SSID:-${DEFAULT_SSID}}"
fi
[[ -n "${SSID}" ]] || die "SSID krävs."

if [[ -z "${PSK}" ]]; then
  if [[ ! -t 0 ]]; then
    die "Inget lösenord angivet. Kör: sudo vkc-kiosk fix-wifi \"${SSID}\" \"losenord\""
  fi
  printf 'WiFi-lösenord: ' >&2
  read -r -s PSK || true
  echo >&2
fi
[[ -n "${PSK}" ]] || die "Lösenord krävs."

EXISTING_UUID="$(nmcli -c no -t -f NAME,UUID,TYPE connection show 2>/dev/null \
  | awk -F: -v n="${SSID}" '$1==n && $3=="802-11-wireless"{print $2; exit}' || true)"

log "Sparar systemanslutning för '${SSID}'"

if [[ -n "${EXISTING_UUID}" ]]; then
  FILENAME="$(nmcli -c no -g connection.filename connection show "${EXISTING_UUID}" 2>/dev/null || true)"
  case "${FILENAME}" in
    /etc/NetworkManager/system-connections/*) ;;
    *)
      if [[ -n "${FILENAME}" ]]; then
        warn "Tar bort användarprofil: ${FILENAME}"
        nmcli connection delete "${EXISTING_UUID}" >/dev/null || true
        EXISTING_UUID=""
      fi
      ;;
  esac
fi

if [[ -n "${EXISTING_UUID}" ]]; then
  nmcli connection modify "${EXISTING_UUID}" \
    connection.id "${SSID}" \
    connection.autoconnect yes \
    connection.autoconnect-retries 0 \
    connection.permissions "" \
    802-11-wireless.ssid "${SSID}" \
    802-11-wireless-security.key-mgmt wpa-psk \
    802-11-wireless-security.psk "${PSK}"
  TARGET="${EXISTING_UUID}"
else
  nmcli connection add \
    type wifi \
    con-name "${SSID}" \
    ifname "*" \
    ssid "${SSID}" \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "${PSK}" \
    connection.autoconnect yes \
    connection.autoconnect-retries 0 \
    connection.permissions ""
  TARGET="${SSID}"
fi

chmod 600 /etc/NetworkManager/system-connections/*.nmconnection 2>/dev/null || true
nmcli connection reload || true

log "Testar anslutning"
if ! nmcli connection up "${TARGET}"; then
  warn "connection up misslyckades — provar device wifi connect..."
  nmcli device wifi connect "${SSID}" password "${PSK}" || warn "Kunde inte ansluta just nu."
fi

FILENAME="$(nmcli -c no -g connection.filename connection show "${TARGET}" 2>/dev/null || true)"
echo
log "Klart"
echo "Anslutning: ${TARGET}"
echo "Fil:        ${FILENAME:-okänd}"
case "${FILENAME}" in
  /etc/NetworkManager/system-connections/*)
    echo "OK: systemanslutning (överlever reboot utan nyckelring)."
    ;;
  *)
    warn "Filen ser inte ut som system-connection. Kontrollera med:"
    echo "  nmcli -f NAME,FILENAME connection show"
    ;;
esac
echo
echo "Tips: spara inte WiFi via skrivbordsdialogen — den lägger lösen i nyckelringen igen."
echo
nmcli -c no -f NAME,DEVICE,FILENAME connection show --active 2>/dev/null | cat || true
