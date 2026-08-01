#!/usr/bin/env bash
# Spara WiFi så det överlever reboot utan nyckelrings-dialog.
#
# Stödjer:
#   - NetworkManager system-connections
#   - netplan→NM (vanligt på Ubuntu/Pi: profiler under /run/NetworkManager/...)
#
# Användning (använd enkla citattecken om lösenordet innehåller !):
#   sudo vkc-kiosk fix-wifi
#   sudo vkc-kiosk fix-wifi 'Mobile-bridge_24' 'pjoskVector4G!'
#
set -euo pipefail

export PAGER=cat
export SYSTEMD_PAGER=cat
export NMCLI_NO_PAGER=1

log()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mVarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mFel:\033[0m %s\n' "$*" >&2; exit 1; }

if [[ "${EUID}" -ne 0 ]]; then
  die "Kör med sudo: sudo vkc-kiosk fix-wifi 'SSID' 'losenord'"
fi

command -v nmcli >/dev/null 2>&1 || die "nmcli saknas. Är NetworkManager installerat?"
systemctl is-active --quiet NetworkManager || die "NetworkManager körs inte."

WIFI_IFACE="$(nmcli -c no -t -f DEVICE,TYPE device status 2>/dev/null | awk -F: '$2=="wifi"{print $1; exit}')"
WIFI_IFACE="${WIFI_IFACE:-wlan0}"

log "Nuvarande anslutningar"
nmcli -c no -f NAME,UUID,TYPE,DEVICE,FILENAME connection show 2>/dev/null | cat || \
  nmcli -f NAME,UUID,TYPE,DEVICE connection show | cat || true
echo
nmcli -c no -t -f DEVICE,TYPE,STATE,CONNECTION device status 2>/dev/null | cat || true
echo

SSID="${1:-}"
PSK="${2:-}"

mapfile -t WIFI_SSIDS < <(nmcli -c no -t -f SSID device wifi list 2>/dev/null | sed '/^$/d' | sort -u || true)
ACTIVE_SSID="$(nmcli -c no -t -f ACTIVE,SSID device wifi list 2>/dev/null | awk -F: '$1=="yes"{print $2; exit}' || true)"

if [[ ${#WIFI_SSIDS[@]} -gt 0 ]]; then
  echo "Synliga nät:"
  i=1
  for s in "${WIFI_SSIDS[@]}"; do
    mark=""
    [[ "${s}" == "${ACTIVE_SSID}" ]] && mark=" (aktiv)"
    printf '  %2d) %s%s\n' "${i}" "${s}" "${mark}"
    i=$((i + 1))
  done
  echo
fi

DEFAULT_SSID="${ACTIVE_SSID:-}"
if [[ -z "${DEFAULT_SSID}" ]]; then
  DEFAULT_SSID="$(nmcli -c no -t -f NAME,TYPE connection show 2>/dev/null | awk -F: '$2=="802-11-wireless"{print $1; exit}' || true)"
fi

if [[ -z "${SSID}" ]]; then
  [[ -t 0 ]] || die "Ange SSID: sudo vkc-kiosk fix-wifi 'SSID' 'losenord'"
  printf 'SSID [%s]: ' "${DEFAULT_SSID}" >&2
  read -r SSID || true
  SSID="${SSID:-${DEFAULT_SSID}}"
fi
[[ -n "${SSID}" ]] || die "SSID krävs."

if [[ -z "${PSK}" ]]; then
  [[ -t 0 ]] || die "Ange lösenord: sudo vkc-kiosk fix-wifi '${SSID}' 'losenord'"
  printf 'WiFi-lösenord: ' >&2
  read -r -s PSK || true
  echo >&2
fi
[[ -n "${PSK}" ]] || die "Lösenord krävs."

# bash history-expansion kan äta ! i dubbla citattecken hos anroparen
if [[ "${PSK}" == *'!'* ]]; then
  echo "Tips: lösenord med ! bör anges i enkla citattecken: 'losen!'"
fi

NETPLAN_MODE=0
if compgen -G "/etc/netplan/*.yaml" >/dev/null 2>&1 || compgen -G "/etc/netplan/*.yml" >/dev/null 2>&1; then
  NETPLAN_MODE=1
fi
if nmcli -c no -t -f NAME,FILENAME connection show 2>/dev/null | grep -q '/run/NetworkManager/system-connections/netplan-'; then
  NETPLAN_MODE=1
fi

yaml_escape() {
  # Enkel YAML double-quoted escape
  python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"
}

write_netplan_wifi() {
  local ssid_json psk_json dest
  ssid_json="$(yaml_escape "${SSID}")"
  psk_json="$(yaml_escape "${PSK}")"
  dest="/etc/netplan/99-vkc-kiosk-wifi.yaml"

  log "Skriver netplan: ${dest}"
  cat > "${dest}" <<EOF
# Hanteras av vkc-kiosk fix-wifi — skriv inte lösenord i nyckelringen.
network:
  version: 2
  wifis:
    ${WIFI_IFACE}:
      dhcp4: true
      optional: true
      access-points:
        ${ssid_json}:
          password: ${psk_json}
EOF
  chmod 600 "${dest}"

  # Ta bort trasiga NM-dubbletter vi kan ha skapat tidigare
  local name uuid
  while IFS=: read -r name uuid _; do
    [[ "${name}" == "${SSID}" ]] || continue
    warn "Tar bort NM-dubblett '${name}' (${uuid})"
    nmcli connection delete uuid "${uuid}" >/dev/null 2>&1 || true
  done < <(nmcli -c no -t -f NAME,UUID,TYPE connection show 2>/dev/null || true)

  log "netplan apply"
  if command -v netplan >/dev/null 2>&1; then
    netplan apply || die "netplan apply misslyckades"
  else
    die "netplan saknas men systemet ser netplan-hanterat ut"
  fi
}

write_nm_system_wifi() {
  local existing_uuid filename target
  existing_uuid="$(nmcli -c no -t -f NAME,UUID,TYPE connection show 2>/dev/null \
    | awk -F: -v n="${SSID}" '$1==n && $3=="802-11-wireless"{print $2; exit}' || true)"

  # Viktigt: wifi-sec.* måste komma EFTER '--' annars sparas inte PSK/key-mgmt.
  if [[ -n "${existing_uuid}" ]]; then
    filename="$(nmcli -c no -g connection.filename connection show "${existing_uuid}" 2>/dev/null || true)"
    case "${filename}" in
      /run/NetworkManager/*|/etc/netplan/*)
        warn "Befintlig profil är netplan-genererad (${filename}) — byter till netplan-läge."
        write_netplan_wifi
        return
        ;;
    esac
    log "Uppdaterar NM-profil ${existing_uuid}"
    nmcli connection modify "${existing_uuid}" \
      connection.id "${SSID}" \
      connection.autoconnect yes \
      connection.autoconnect-retries 0 \
      connection.permissions "" \
      802-11-wireless.ssid "${SSID}" \
      -- \
      802-11-wireless-security.key-mgmt wpa-psk \
      802-11-wireless-security.psk "${PSK}"
    target="${existing_uuid}"
  else
    log "Skapar NM systemprofil"
    nmcli connection add \
      type wifi \
      con-name "${SSID}" \
      ifname "${WIFI_IFACE}" \
      ssid "${SSID}" \
      connection.autoconnect yes \
      connection.autoconnect-retries 0 \
      connection.permissions "" \
      -- \
      wifi-sec.key-mgmt wpa-psk \
      wifi-sec.psk "${PSK}"
    target="${SSID}"
  fi

  chmod 600 /etc/NetworkManager/system-connections/*.nmconnection 2>/dev/null || true
  nmcli connection reload || true

  log "Aktiverar ${target}"
  nmcli -w 30 connection up "${target}" \
    || nmcli -w 30 device wifi connect "${SSID}" password "${PSK}" ifname "${WIFI_IFACE}" \
    || warn "Kunde inte aktivera just nu — reboota och kontrollera."

  filename="$(nmcli -c no -g connection.filename connection show "${target}" 2>/dev/null || true)"
  echo
  log "Klart (NetworkManager)"
  echo "Anslutning: ${target}"
  echo "Fil:        ${filename:-okänd}"
}

if [[ "${NETPLAN_MODE}" -eq 1 ]]; then
  log "Netplan/NM-hybrid upptäckt — sparar WiFi i netplan (rekommenderat)"
  write_netplan_wifi
  sleep 2
  echo
  log "Klart (netplan)"
  echo "SSID:  ${SSID}"
  echo "Iface: ${WIFI_IFACE}"
  echo "Fil:   /etc/netplan/99-vkc-kiosk-wifi.yaml"
  echo
  nmcli -c no -f NAME,DEVICE,FILENAME connection show --active 2>/dev/null | cat || true
  echo
  echo "Kontroll: ping -c2 1.1.1.1"
else
  write_nm_system_wifi
  echo
  nmcli -c no -f NAME,DEVICE,FILENAME connection show --active 2>/dev/null | cat || true
fi

echo
echo "Använd alltid enkla citattecken om lösenordet innehåller ! :"
echo "  sudo vkc-kiosk fix-wifi '${SSID}' 'dittlösen!'"
echo "Spara inte nätet via skrivbordsdialogen efteråt."
