#!/usr/bin/env bash
# Flytta WiFi till systemanslutning så lösenordet inte ligger i användarnyckelringen.
#
# Symptom som detta löser:
#   - Ibland: "Ange lösenord" trots att nätet redan är sparat
#   - "Visa lösenord" visar skräp / fel värde
#   - Connect gör ingenting efter autologin / omstart
#
# Kräver: NetworkManager (Pi OS Bookworm standard)
set -euo pipefail

log()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mVarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mFel:\033[0m %s\n' "$*" >&2; exit 1; }

if [[ "${EUID}" -ne 0 ]]; then
  die "Kör med sudo: sudo vkc-kiosk fix-wifi"
fi

command -v nmcli >/dev/null 2>&1 || die "nmcli saknas. Är NetworkManager installerat?"
systemctl is-active --quiet NetworkManager || die "NetworkManager körs inte."

log "Nuvarande anslutningar"
nmcli -f NAME,UUID,TYPE,DEVICE,FILENAME connection show || true
echo
nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status || true

echo
echo "Det här sparar WiFi-lösenordet som systemanslutning under"
echo "/etc/NetworkManager/system-connections/ (bara root kan läsa),"
echo "inte i din inloggningsnyckelring. Då funkar autoconnect efter"
echo "reboot utan lösenordsruta."
echo

mapfile -t WIFI_SSIDS < <(nmcli -t -f SSID device wifi list 2>/dev/null | sed '/^$/d' | sort -u || true)
ACTIVE_SSID="$(nmcli -t -f ACTIVE,SSID device wifi list 2>/dev/null | awk -F: '$1=="yes"{print $2; exit}' || true)"

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
  DEFAULT_SSID="$(nmcli -t -f NAME,TYPE connection show 2>/dev/null | awk -F: '$2=="802-11-wireless"{print $1; exit}' || true)"
fi

read -r -p "SSID [${DEFAULT_SSID}]: " SSID
SSID="${SSID:-${DEFAULT_SSID}}"
[[ -n "${SSID}" ]] || die "SSID krävs."

read -r -s -p "WiFi-lösenord: " PSK
echo
[[ -n "${PSK}" ]] || die "Lösenord krävs."

EXISTING_UUID="$(nmcli -t -f NAME,UUID,TYPE connection show \
  | awk -F: -v n="${SSID}" '$1==n && $3=="802-11-wireless"{print $2; exit}')"

log "Sparar systemanslutning för '${SSID}' (körs som root → systemfil)"

# Ta bort ev. användarprofil med samma namn så vi inte får dubbletter i nyckelringen.
if [[ -n "${EXISTING_UUID}" ]]; then
  FILENAME="$(nmcli -g connection.filename connection show "${EXISTING_UUID}" 2>/dev/null || true)"
  if [[ -n "${FILENAME}" && "${FILENAME}" != /etc/NetworkManager/system-connections/* ]]; then
    warn "Tar bort användarprofil: ${FILENAME}"
    nmcli connection delete "${EXISTING_UUID}" >/dev/null
    EXISTING_UUID=""
  fi
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
  # Root-nmcli skapar fil under /etc/NetworkManager/system-connections/
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

FILENAME="$(nmcli -g connection.filename connection show "${TARGET}" 2>/dev/null || true)"
echo
log "Klart"
echo "Anslutning: ${TARGET}"
echo "Fil:        ${FILENAME:-okänd}"
if [[ -n "${FILENAME}" && "${FILENAME}" == /etc/NetworkManager/system-connections/* ]]; then
  echo "OK: systemanslutning (överlever reboot utan nyckelring)."
else
  warn "Filen ser inte ut som system-connection. Kontrollera: nmcli -f NAME,FILENAME connection show"
fi
echo
echo "Tips: spara inte WiFi via skrivbordsdialogen — den lägger lösen i nyckelringen igen."
echo
nmcli -f NAME,DEVICE,FILENAME connection show --active || true
