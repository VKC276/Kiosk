#!/usr/bin/env bash
# VKC Kiosk — engångsinstallation för Raspberry Pi
#
# Användning:
#   curl -fsSL https://raw.githubusercontent.com/VKC276/Kiosk/main/install.sh | sudo bash
#   eller, i en klonad repo:
#   sudo ./install.sh
#
# Valfria miljövariabler:
#   KIOSK_USER=vkc
#   KIOSK_DIR=/home/vkc/vkc-kiosk
#   KIOSK_REPO=https://github.com/VKC276/Kiosk.git
#   KIOSK_BRANCH=main
#   SKIP_BROWSER=1          # installera bara API-tjänsten
#   SKIP_APT=1              # hoppa över apt-get
set -euo pipefail

REPO_DEFAULT="https://github.com/VKC276/Kiosk.git"
BRANCH_DEFAULT="main"

log()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mVarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mFel:\033[0m %s\n' "$*" >&2; exit 1; }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    die "Kör som root: sudo ./install.sh"
  fi
}

detect_user() {
  if [[ -n "${KIOSK_USER:-}" ]]; then
    echo "${KIOSK_USER}"
    return
  fi
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    echo "${SUDO_USER}"
    return
  fi
  if id -u vkc >/dev/null 2>&1; then
    echo "vkc"
    return
  fi
  if id -u pi >/dev/null 2>&1; then
    echo "pi"
    return
  fi
  die "Kunde inte avgöra användare. Sätt KIOSK_USER=..."
}

read_server_bind() {
  local cfg="$1"
  python3 - <<PY
import json
from pathlib import Path
cfg = json.loads(Path(${cfg@Q}).read_text(encoding="utf-8"))
server = cfg.get("SERVER") or {}
print(server.get("host", "0.0.0.0"))
print(int(server.get("port", 8081)))
PY
}

render_unit() {
  local src="$1"
  local dst="$2"
  sed \
    -e "s|__KIOSK_USER__|${KIOSK_USER}|g" \
    -e "s|__KIOSK_UID__|${KIOSK_UID}|g" \
    -e "s|__KIOSK_DIR__|${KIOSK_DIR}|g" \
    -e "s|__SERVER_HOST__|${SERVER_HOST}|g" \
    -e "s|__SERVER_PORT__|${SERVER_PORT}|g" \
    "${src}" > "${dst}"
}

install_apt_packages() {
  if [[ "${SKIP_APT:-0}" == "1" ]]; then
    warn "SKIP_APT=1 — hoppar över paketinstallation"
    return
  fi

  log "Uppdaterar apt och installerar beroenden"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y \
    git \
    curl \
    python3 \
    python3-venv \
    python3-dev \
    build-essential \
    ca-certificates \
    x11-xserver-utils

  # Chromium-paketnamn skiljer sig mellan Pi OS / Ubuntu
  if [[ "${SKIP_BROWSER:-0}" != "1" ]]; then
    if ! command -v chromium-browser >/dev/null 2>&1 && ! command -v chromium >/dev/null 2>&1; then
      if apt-cache show chromium-browser >/dev/null 2>&1; then
        apt-get install -y chromium-browser
      elif apt-cache show chromium >/dev/null 2>&1; then
        apt-get install -y chromium
      else
        warn "Hittade inget Chromium-paket. Installera manuellt och kör om installern."
      fi
    fi
  fi
}

bootstrap_repo() {
  local self_dir=""
  if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
    self_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  fi

  if [[ -n "${self_dir}" && -f "${self_dir}/wsgi.py" && -f "${self_dir}/app.py" ]]; then
    KIOSK_DIR="${KIOSK_DIR:-${self_dir}}"
    log "Använder befintlig kodkatalog: ${KIOSK_DIR}"
    # Om vi kör från en annan användares kopia, säkerställ ägarskap senare
    return
  fi

  KIOSK_REPO="${KIOSK_REPO:-${REPO_DEFAULT}}"
  KIOSK_BRANCH="${KIOSK_BRANCH:-${BRANCH_DEFAULT}}"
  KIOSK_DIR="${KIOSK_DIR:-/home/${KIOSK_USER}/vkc-kiosk}"

  # Säkerställ hem/katalog
  mkdir -p "$(dirname "${KIOSK_DIR}")"
  chown "${KIOSK_USER}:${KIOSK_USER}" "$(dirname "${KIOSK_DIR}")" 2>/dev/null || true

  if [[ -d "${KIOSK_DIR}/.git" ]]; then
    log "Uppdaterar befintlig klon i ${KIOSK_DIR}"
    chown -R "${KIOSK_USER}:${KIOSK_USER}" "${KIOSK_DIR}"
    sudo -u "${KIOSK_USER}" git -C "${KIOSK_DIR}" fetch origin
    sudo -u "${KIOSK_USER}" git -C "${KIOSK_DIR}" checkout "${KIOSK_BRANCH}"
    sudo -u "${KIOSK_USER}" git -C "${KIOSK_DIR}" pull --ff-only origin "${KIOSK_BRANCH}" || true
  else
    log "Klonar ${KIOSK_REPO} (${KIOSK_BRANCH}) → ${KIOSK_DIR}"
    if [[ -d "${KIOSK_DIR}" && -z "$(ls -A "${KIOSK_DIR}" 2>/dev/null || true)" ]]; then
      rmdir "${KIOSK_DIR}" 2>/dev/null || true
    fi
    if [[ -e "${KIOSK_DIR}" && ! -d "${KIOSK_DIR}/.git" ]]; then
      die "${KIOSK_DIR} finns redan och är inte ett git-repo. Välj annan KIOSK_DIR=..."
    fi
    sudo -u "${KIOSK_USER}" git clone --branch "${KIOSK_BRANCH}" "${KIOSK_REPO}" "${KIOSK_DIR}"
  fi
}

ensure_config() {
  # config.json trackas inte i git — kopiera exempel vid första installation.
  if [[ ! -f "${KIOSK_DIR}/config.json" ]]; then
    if [[ -f "${KIOSK_DIR}/config.example.json" ]]; then
      log "Skapar config.json från config.example.json (redigera GAS-URL:er m.m.)"
      sudo -u "${KIOSK_USER}" cp -a "${KIOSK_DIR}/config.example.json" "${KIOSK_DIR}/config.json"
    else
      die "Saknar både config.json och config.example.json i ${KIOSK_DIR}"
    fi
  else
    log "Behåller befintlig config.json"
  fi
}

setup_python() {
  log "Skapar venv och installerar Python-paket"
  sudo -u "${KIOSK_USER}" python3 -m venv "${KIOSK_DIR}/venv"
  sudo -u "${KIOSK_USER}" "${KIOSK_DIR}/venv/bin/pip" install --upgrade pip wheel
  sudo -u "${KIOSK_USER}" "${KIOSK_DIR}/venv/bin/pip" install -r "${KIOSK_DIR}/requirements.txt"
}

setup_permissions() {
  log "Sätter behörigheter för kortläsare (input-gruppen)"
  getent group input >/dev/null || groupadd input
  usermod -aG input "${KIOSK_USER}"

  if [[ -f "${KIOSK_DIR}/deploy/99-vkc-kiosk-input.rules" ]]; then
    cp "${KIOSK_DIR}/deploy/99-vkc-kiosk-input.rules" /etc/udev/rules.d/99-vkc-kiosk-input.rules
  fi
  # SDZNKJLTD-läsare (ffff:0035): iface 1 kan döda xHCI på Pi
  if [[ -x "${KIOSK_DIR}/deploy/install-usb-reader-quirk.sh" ]]; then
    "${KIOSK_DIR}/deploy/install-usb-reader-quirk.sh" || warn "USB-reader quirk installerades inte"
  elif [[ -f "${KIOSK_DIR}/deploy/99-sdznkj-usb-reader.rules" ]]; then
    cp "${KIOSK_DIR}/deploy/99-sdznkj-usb-reader.rules" /etc/udev/rules.d/99-sdznkj-usb-reader.rules
  fi
  udevadm control --reload-rules || true
  udevadm trigger || true

  chown -R "${KIOSK_USER}:${KIOSK_USER}" "${KIOSK_DIR}"
  chmod +x "${KIOSK_DIR}/install.sh" \
           "${KIOSK_DIR}/deploy/start-browser.sh" \
           "${KIOSK_DIR}/scripts/"*.sh \
           "${KIOSK_DIR}/scripts/"*.py 2>/dev/null || true
}

install_cli() {
  log "Installerar kommandot vkc-kiosk"
  cat > /usr/local/bin/vkc-kiosk <<EOF
#!/usr/bin/env bash
exec "${KIOSK_DIR}/scripts/vkc-kiosk.sh" "\$@"
EOF
  chmod +x /usr/local/bin/vkc-kiosk
}

install_services() {
  log "Installerar systemd-tjänster"

  mapfile -t BIND < <(read_server_bind "${KIOSK_DIR}/config.json")
  SERVER_HOST="${BIND[0]}"
  SERVER_PORT="${BIND[1]}"
  KIOSK_UID="$(id -u "${KIOSK_USER}")"

  render_unit "${KIOSK_DIR}/deploy/vkc-kiosk.service.in" /etc/systemd/system/vkc-kiosk.service

  if [[ "${SKIP_BROWSER:-0}" != "1" ]]; then
    render_unit "${KIOSK_DIR}/deploy/vkc-kiosk-browser.service.in" /etc/systemd/system/vkc-kiosk-browser.service
  fi

  # Behåll bakåtkompatibel alias-länk om gammal unit fanns
  if [[ -f /etc/systemd/system/mifare-reader.service ]]; then
    warn "Hittade gammal mifare-reader.service — inaktiverar den till förmån för vkc-kiosk.service"
    systemctl disable --now mifare-reader.service >/dev/null 2>&1 || true
  fi

  systemctl daemon-reload
  systemctl enable vkc-kiosk.service
  systemctl restart vkc-kiosk.service

  if [[ "${SKIP_BROWSER:-0}" != "1" ]]; then
    # En startväg bara: systemd-browser. Autostart-desktop tas bort om den finns,
    # annars startas Chromium dubbelt och öppnar nya flikar i en loop.
    local autostart_file="/home/${KIOSK_USER}/.config/autostart/vkc-kiosk.desktop"
    if [[ -f "${autostart_file}" ]]; then
      warn "Tar bort ${autostart_file} (undviker dubbelstart av Chromium)"
      rm -f "${autostart_file}"
    fi

    systemctl enable vkc-kiosk-browser.service
    systemctl restart vkc-kiosk-browser.service \
      || warn "Browser-tjänsten startade inte ännu (saknas display?). Den startar vid nästa grafiska login/reboot."
  fi
}

print_summary() {
  cat <<EOF

────────────────────────────────────────────────────────
VKC Kiosk installerad

  Kod:      ${KIOSK_DIR}
  Användare:${KIOSK_USER}
  API:      http://127.0.0.1:${SERVER_PORT}/
  Tjänster: vkc-kiosk.service$([ "${SKIP_BROWSER:-0}" = "1" ] || echo " + vkc-kiosk-browser.service")

Nästa steg:
  1) Lista kortläsare:   vkc-kiosk devices
  2) Justera config:     nano ${KIOSK_DIR}/config.json
  3) Starta om:          vkc-kiosk restart
  4) Status/loggar:      vkc-kiosk status

Tips: logga ut/in (eller reboot) så input-gruppens behörighet tar effekt.
────────────────────────────────────────────────────────
EOF
}

main() {
  require_root
  KIOSK_USER="$(detect_user)"
  log "Installerar som användare: ${KIOSK_USER}"

  install_apt_packages
  bootstrap_repo
  ensure_config
  setup_python
  setup_permissions
  install_cli
  install_services
  print_summary
}

main "$@"
