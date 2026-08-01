#!/usr/bin/env bash
# Spara WiFi permanent i NetworkManager (överlever reboot, ingen nyckelring).
#
# På netplan+NM-hybrider (Ubuntu/Pi) tar vi bort vår tidigare netplan-wifi-fil
# som skapade /run/...-profiler utan pålitlig PSK efter reboot, och skriver
# i stället en root-ägd keyfile under /etc/NetworkManager/system-connections/.
#
# Användning (enkla citattecken om lösenordet innehåller !):
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

command -v nmcli >/dev/null 2>&1 || die "nmcli saknas."
command -v python3 >/dev/null 2>&1 || die "python3 saknas."
systemctl is-active --quiet NetworkManager || die "NetworkManager körs inte."

WIFI_IFACE="$(nmcli -c no -t -f DEVICE,TYPE device status 2>/dev/null | awk -F: '$2=="wifi"{print $1; exit}')"
WIFI_IFACE="${WIFI_IFACE:-wlan0}"
CONN_ID="vkc-kiosk-wifi"
KEYFILE="/etc/NetworkManager/system-connections/${CONN_ID}.nmconnection"
NETPLAN_VKC="/etc/netplan/99-vkc-kiosk-wifi.yaml"

log "Nuvarande anslutningar"
nmcli -c no -f NAME,UUID,TYPE,DEVICE,FILENAME connection show 2>/dev/null | cat || true
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

if [[ "${#PSK}" -lt 8 ]]; then
  warn "WPA-lösenord är normalt minst 8 tecken — fortsätter ändå."
fi

# --- Städa konflikter -------------------------------------------------------

log "Städar konflikterande WiFi-profiler"
# Tidigare netplan-wifi från vkc (skapade opålitliga /run-profiler)
if [[ -f "${NETPLAN_VKC}" ]]; then
  warn "Tar bort ${NETPLAN_VKC} (byts mot permanent NM-keyfile)"
  rm -f "${NETPLAN_VKC}"
fi

# Radera NM-wifi med samma SSID, skräpnamnet "1", och tidigare vkc-profil
while IFS=: read -r name uuid type; do
  [[ "${type}" == "802-11-wireless" ]] || continue
  delete=0
  [[ "${name}" == "${CONN_ID}" || "${name}" == "${SSID}" || "${name}" == "1" ]] && delete=1
  # netplan-genererade för samma SSID
  case "${name}" in
    netplan-*"${SSID}"*|netplan-"${WIFI_IFACE}"-"${SSID}") delete=1 ;;
  esac
  if [[ "${delete}" -eq 1 ]]; then
    warn "Tar bort anslutning '${name}' (${uuid})"
    nmcli connection delete uuid "${uuid}" >/dev/null 2>&1 || true
  fi
done < <(nmcli -c no -t -f NAME,UUID,TYPE connection show 2>/dev/null || true)

# Andra netplan-filer som styr wifi? varna (rör dem inte automatiskt)
if command -v netplan >/dev/null 2>&1; then
  if grep -R --include='*.yaml' --include='*.yml' -l 'access-points:' /etc/netplan /lib/netplan 2>/dev/null | grep -v "${NETPLAN_VKC}" >/tmp/vkc-netplan-wifi-files 2>/dev/null; then
    if [[ -s /tmp/vkc-netplan-wifi-files ]]; then
      warn "Andra netplan-filer definierar fortfarande WiFi (kan konkurrera):"
      cat /tmp/vkc-netplan-wifi-files >&2 || true
    fi
  fi
  rm -f /tmp/vkc-netplan-wifi-files
  # Applicera borttagning av 99-filen
  netplan apply 2>/dev/null || true
fi

# --- Skriv permanent NM-keyfile ---------------------------------------------

log "Skriver permanent NM-keyfile: ${KEYFILE}"
python3 - <<'PY' "${KEYFILE}" "${CONN_ID}" "${WIFI_IFACE}" "${SSID}" "${PSK}"
import sys, uuid
from pathlib import Path

path, conn_id, iface, ssid, psk = sys.argv[1:6]
uid = str(uuid.uuid4())

def esc(value: str) -> str:
    # NM keyfile: escape backslash and semicolon/hash at line starts via normal assignment
    return value.replace("\\", "\\\\").replace("\n", "")

content = f"""[connection]
id={esc(conn_id)}
uuid={uid}
type=wifi
interface-name={esc(iface)}
autoconnect=true
autoconnect-priority=999
autoconnect-retries=0
permissions=

[wifi]
mode=infrastructure
ssid={esc(ssid)}

[wifi-security]
key-mgmt=wpa-psk
psk={esc(psk)}

[ipv4]
method=auto

[ipv6]
method=auto
"""

p = Path(path)
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(content, encoding="utf-8")
p.chmod(0o600)
print(f"Skrev {p} (uuid={uid})")
PY

chmod 600 "${KEYFILE}"
nmcli connection reload
sleep 1

# Verifiera att PSK faktiskt finns i profilen (root)
STORED_PSK="$(nmcli -c no -s -g 802-11-wireless-security.psk connection show "${CONN_ID}" 2>/dev/null || true)"
if [[ -z "${STORED_PSK}" ]]; then
  die "PSK sparades inte i ${CONN_ID}. Avbryter."
fi
if [[ "${STORED_PSK}" != "${PSK}" ]]; then
  die "Sparad PSK matchar inte angivet lösenord (citattecken/history-expansion?). Prova enkla citattecken."
fi
echo "PSK sparad i profilen: ja (${#STORED_PSK} tecken)"

log "Aktiverar ${CONN_ID}"
# Koppla ner andra wifi-profiler på iface först
nmcli -w 10 device disconnect "${WIFI_IFACE}" >/dev/null 2>&1 || true
if ! nmcli -w 45 connection up "${CONN_ID}" ifname "${WIFI_IFACE}"; then
  warn "connection up misslyckades — provar wifi connect..."
  nmcli -w 45 device wifi connect "${SSID}" password "${PSK}" ifname "${WIFI_IFACE}" name "${CONN_ID}" \
    || warn "Kunde inte ansluta just nu. Kontrollera SSID/lösenord / radio."
fi

FILENAME="$(nmcli -c no -g connection.filename connection show "${CONN_ID}" 2>/dev/null || true)"
STATE="$(nmcli -c no -t -f DEVICE,STATE,CONNECTION device status 2>/dev/null | awk -F: -v d="${WIFI_IFACE}" '$1==d{print $2" / "$3}')"

echo
log "Klart"
echo "Anslutning: ${CONN_ID}"
echo "SSID:       ${SSID}"
echo "Iface:      ${WIFI_IFACE}"
echo "Fil:        ${FILENAME:-${KEYFILE}}"
echo "Status:     ${STATE:-okänd}"
echo
nmcli -c no -f NAME,DEVICE,FILENAME connection show --active 2>/dev/null | cat || true
echo
echo "Test: ping -c2 1.1.1.1"
echo "Efter reboot ska '${CONN_ID}' autoconnecta utan lösenordsruta."
echo "Spara inte nätet via skrivbordsdialogen (då kommer nyckelringsfelet tillbaka)."
echo
echo "Om det fortfarande frågar lösen efter reboot:"
echo "  nmcli -f NAME,FILENAME connection show"
echo "  sudo cat ${KEYFILE} | grep -E '^(id|ssid|psk|autoconnect)'"
