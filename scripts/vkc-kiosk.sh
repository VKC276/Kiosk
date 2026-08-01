#!/usr/bin/env bash
# Enkel CLI för drift: vkc-kiosk status|restart|update|devices|logs|...
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_API="vkc-kiosk.service"
SERVICE_BROWSER="vkc-kiosk-browser.service"

usage() {
  cat <<EOF
Användning: vkc-kiosk <kommando>

Drift
  status              Tjänstestatus + /healthz
  start               Starta API
  stop                Stoppa browser + API
  restart             Starta om API (+ browser) och visa status
  logs                Följ journal-loggar
  devices             Lista input-/USB-läsare
  url                 Skriv ut lokal kiosk-URL

Kod & config
  pull                git pull (behåller config.json; stashar bara tracked)
  update              pull + pip + ominstallation/restart
  config              Öppna config.json i \$EDITOR
  save-config         Spegla nuvarande config.json → ~/.config/vkc-kiosk/
  restore-config      Återställ config.json från ~/.config/vkc-kiosk/

Kortläsare & kiosk
  setup-reader        YAROGNTEC/SDZNKJLTD systemfix (sudo + reboot)
  configure-reader    Välj läsare + kortformat → config.json
  slides              Karusell: URL, ordning, tid, refresh  (alias: karusell)

Dokumentation: INSTALLATION.md och README.md i git-repot.
EOF
}

port() {
  python3 - <<PY
import json
from pathlib import Path
cfg = json.loads(Path("${ROOT_DIR}/config.json").read_text(encoding="utf-8"))
print(int((cfg.get("SERVER") or {}).get("port", 8081)))
PY
}

cmd_status() {
  systemctl --no-pager --full status "${SERVICE_API}" || true
  if systemctl list-unit-files | grep -q "^${SERVICE_BROWSER}"; then
    systemctl --no-pager --full status "${SERVICE_BROWSER}" || true
  fi
  echo
  curl -fsS "http://127.0.0.1:$(port)/healthz" && echo
}

cmd_restart() {
  sudo systemctl restart "${SERVICE_API}"
  if systemctl list-unit-files | grep -q "^${SERVICE_BROWSER}"; then
    sudo systemctl restart "${SERVICE_BROWSER}" || true
  fi
  cmd_status
}

config_backup_dir() {
  # UTANFÖR git-repot så stash -u aldrig kan ta bort backupen.
  local home_dir="${HOME:-/home/${SUDO_USER:-dev}}"
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    home_dir="$(getent passwd "${SUDO_USER}" | cut -d: -f6)"
    home_dir="${home_dir:-/home/${SUDO_USER}}"
  fi
  echo "${home_dir}/.config/vkc-kiosk"
}

mirror_config_backup() {
  # Spegla NUVARANDE config.json till ~/.config (disaster recovery).
  # Anropas bara när working-tree-filen är den som ska bevaras.
  local src="${ROOT_DIR}/config.json"
  local dir stamp
  [[ -f "${src}" ]] || return 1
  dir="$(config_backup_dir)"
  mkdir -p "${dir}"
  stamp="$(date +%Y%m%d-%H%M%S 2>/dev/null || echo now)"
  cp -a "${src}" "${dir}/config.json"
  cp -a "${src}" "${dir}/config-${stamp}.json"
  cp -a "${src}" "${ROOT_DIR}/config.json.localbak"
  ls -1t "${dir}"/config-*.json 2>/dev/null | tail -n +11 | xargs -r rm -f || true
  echo "Backup speglad: ${dir}/config.json"
}

restore_config_from_home() {
  # Endast för kommandot restore-config — inte under pull.
  local dest="${ROOT_DIR}/config.json"
  local dir stable localbak
  dir="$(config_backup_dir)"
  stable="${dir}/config.json"
  localbak="${ROOT_DIR}/config.json.localbak"

  if [[ -f "${stable}" ]]; then
    cp -a "${stable}" "${dest}"
    echo "Återställde config.json från ${stable}"
    return 0
  fi
  if [[ -f "${localbak}" ]]; then
    cp -a "${localbak}" "${dest}"
    echo "Återställde config.json från ${localbak}"
    return 0
  fi
  return 1
}

cmd_pull() {
  # Bevara EXAKT den config.json som finns just nu — inte en gammal
  # ~/.config-kopia (det skrev över manuellt inskrivna configs).
  cd "${ROOT_DIR}"
  local branch stash_msg dirty=0 rc=0 pull_bak=""
  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
  stash_msg="vkc-kiosk pull auto-stash $(date -Iseconds 2>/dev/null || date)"

  if [[ -f "${ROOT_DIR}/config.json" ]]; then
    pull_bak="$(mktemp /tmp/vkc-kiosk-config.XXXXXX.json)"
    cp -a "${ROOT_DIR}/config.json" "${pull_bak}"
    mirror_config_backup || true
    echo "Pull-skydd: ${pull_bak}"
  else
    echo "Varning: config.json saknas före pull — försöker hem-backup efteråt." >&2
  fi

  # Sluta tracka config lokalt (äldre kloner).
  if git ls-files --error-unmatch config.json >/dev/null 2>&1; then
    git rm --cached -f config.json >/dev/null 2>&1 || true
  fi

  # Stasha BARA tracked ändringar — aldrig -u.
  if ! git diff --quiet || ! git diff --cached --quiet; then
    dirty=1
    echo "Lokala kodändringar hittades — sparar i git stash (bara tracked)..."
    git stash push -m "${stash_msg}" || {
      echo "Kunde inte stash:a. Avbryter." >&2
      if [[ -n "${pull_bak}" && -f "${pull_bak}" ]]; then
        cp -a "${pull_bak}" "${ROOT_DIR}/config.json"
        rm -f "${pull_bak}"
      fi
      return 1
    }
    echo "Stash: ${stash_msg}"
  fi

  git pull --ff-only origin "${branch}" || rc=$?

  if [[ -n "${pull_bak}" && -f "${pull_bak}" ]]; then
    cp -a "${pull_bak}" "${ROOT_DIR}/config.json"
    mirror_config_backup || true
    rm -f "${pull_bak}"
    echo "Återställde config.json från denna pulls skyddskopia (inte gammal backup)."
  elif [[ ! -f "${ROOT_DIR}/config.json" ]]; then
    if restore_config_from_home; then
      :
    else
      echo "Varning: ingen config.json efter pull." >&2
      echo "  Skriv in den igen, sedan: mkdir -p ~/.config/vkc-kiosk && cp -a config.json ~/.config/vkc-kiosk/" >&2
      rc=1
    fi
  fi

  if [[ "${rc}" -ne 0 ]]; then
    echo "git pull misslyckades eller config-skydd fel (kod ${rc})." >&2
    if [[ "${dirty}" -eq 1 ]]; then
      echo "Lokala filer kan ligga i stash — se: git stash list" >&2
    fi
  fi
  return "${rc}"
}

cmd_restore_config() {
  cd "${ROOT_DIR}"
  local dir
  dir="$(config_backup_dir)"
  echo "Backupkatalog: ${dir}"
  ls -la "${dir}" 2>/dev/null || echo "(tom / saknas)"
  echo
  if restore_config_from_home; then
    mirror_config_backup || true
    echo "Klart. Starta om: vkc-kiosk restart"
  else
    echo "Ingen backup hittades." >&2
    return 1
  fi
}

cmd_save_config() {
  # Spegla nuvarande (bra) config till hem-backup — kör efter manuell edit.
  cd "${ROOT_DIR}"
  if [[ ! -f "${ROOT_DIR}/config.json" ]]; then
    echo "config.json saknas." >&2
    return 1
  fi
  mirror_config_backup
  echo "Din nuvarande config är sparad som backup. Framtida pull rör den inte felaktigt."
}

cmd_update() {
  cd "${ROOT_DIR}"
  cmd_pull
  if [[ -x "${ROOT_DIR}/venv/bin/pip" ]]; then
    "${ROOT_DIR}/venv/bin/pip" install -r requirements.txt
  fi
  sudo cp "${ROOT_DIR}/deploy/99-vkc-kiosk-input.rules" /etc/udev/rules.d/ 2>/dev/null || true
  # Rendera om units om install.sh finns
  if [[ -x "${ROOT_DIR}/install.sh" ]]; then
    sudo SKIP_APT=1 "${ROOT_DIR}/install.sh"
  else
    sudo systemctl restart "${SERVICE_API}"
  fi
}

cmd_devices() {
  if [[ -x "${ROOT_DIR}/venv/bin/python" ]]; then
    "${ROOT_DIR}/venv/bin/python" "${ROOT_DIR}/scripts/list_input_devices.py"
  else
    python3 "${ROOT_DIR}/scripts/list_input_devices.py"
  fi
  echo
  curl -fsS "http://127.0.0.1:$(port)/api/input-devices" || true
  echo
}

python_bin() {
  if [[ -x "${ROOT_DIR}/venv/bin/python" ]]; then
    echo "${ROOT_DIR}/venv/bin/python"
  else
    echo "python3"
  fi
}

cmd_setup_reader() {
  sudo "${ROOT_DIR}/scripts/setup-yarogntec-reader.sh"
}

cmd_configure_reader() {
  exec "$(python_bin)" "${ROOT_DIR}/scripts/configure-card-reader.py" "$@"
}

cmd_slides() {
  exec "$(python_bin)" "${ROOT_DIR}/scripts/manage-slides.py" "$@"
}

main() {
  local cmd="${1:-}"
  shift || true
  case "${cmd}" in
    status)  cmd_status ;;
    restart) cmd_restart ;;
    start)   sudo systemctl start "${SERVICE_API}" ;;
    stop)    sudo systemctl stop "${SERVICE_BROWSER}" 2>/dev/null || true
             sudo systemctl stop "${SERVICE_API}" ;;
    logs)    sudo journalctl -u "${SERVICE_API}" -u "${SERVICE_BROWSER}" -f ;;
    devices) cmd_devices ;;
    update)  cmd_update ;;
    pull)    cmd_pull ;;
    config)  "${EDITOR:-nano}" "${ROOT_DIR}/config.json" ;;
    save-config) cmd_save_config ;;
    restore-config) cmd_restore_config ;;
    url)     echo "http://127.0.0.1:$(port)/" ;;
    setup-reader) cmd_setup_reader ;;
    configure-reader) cmd_configure_reader "$@" ;;
    slides|karusell) cmd_slides "$@" ;;
    -h|--help|help|"") usage ;;
    *) echo "Okänt kommando: ${cmd}" >&2; usage; exit 1 ;;
  esac
}

main "$@"
