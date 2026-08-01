#!/usr/bin/env bash
# Enkel CLI för drift: vkc-kiosk status|restart|update|devices|logs|...
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_API="vkc-kiosk.service"
SERVICE_BROWSER="vkc-kiosk-browser.service"

usage() {
  cat <<EOF
Användning: vkc-kiosk <kommando>

  status              Visa tjänstestatus + healthz
  restart             Starta om API (och browser om den finns)
  stop                Stoppa tjänster
  start               Starta tjänster
  logs                Följ journal-loggar
  devices             Lista input-enheter (kortläsare)
  update              git pull (behåller config.json) + pip + restart
  pull                git pull och behåller din lokala config.json
  config              Öppna config.json i \$EDITOR
  url                 Skriv ut lokal kiosk-URL
  setup-reader        Installera YAROGNTEC/SDZNKJLTD USB-fix (systemändringar)
  configure-reader    Interaktiv assistent: läsare + kortformat → config.json
  slides              Hantera karusell: lägg till/ta bort URL, ordning, tid
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

cmd_pull() {
  # Behåll alltid lokal config.json. Övriga lokala ändringar stasas
  # så git pull inte stoppas (vanligt efter manuella hotfixes på Pi).
  cd "${ROOT_DIR}"
  local branch backup stash_msg dirty=0
  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
  backup="${ROOT_DIR}/config.json.localbak"
  stash_msg="vkc-kiosk pull auto-stash $(date -Iseconds 2>/dev/null || date)"

  if [[ -f "${ROOT_DIR}/config.json" ]]; then
    cp -a "${ROOT_DIR}/config.json" "${backup}"
  fi

  if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
    dirty=1
  fi

  if [[ "${dirty}" -eq 1 ]]; then
    echo "Lokala ändringar hittades — sparar i git stash innan pull..."
    git stash push -u -m "${stash_msg}" || {
      echo "Kunde inte stash:a lokala ändringar. Avbryter." >&2
      return 1
    }
    echo "Stash: ${stash_msg}"
    echo "Återställ vid behov: git stash list && git stash show -p"
  fi

  local rc=0
  git pull --ff-only origin "${branch}" || rc=$?

  if [[ -f "${backup}" ]]; then
    cp -a "${backup}" "${ROOT_DIR}/config.json"
    echo "Återställde din lokala config.json (backup: ${backup})"
  fi

  if [[ "${rc}" -ne 0 ]]; then
    echo "git pull misslyckades (kod ${rc}). Din config.json är återställd." >&2
    if [[ "${dirty}" -eq 1 ]]; then
      echo "Lokala filer ligger kvar i stash — se: git stash list" >&2
    fi
  fi
  return "${rc}"
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
    url)     echo "http://127.0.0.1:$(port)/" ;;
    setup-reader) cmd_setup_reader ;;
    configure-reader) cmd_configure_reader "$@" ;;
    slides|karusell) cmd_slides "$@" ;;
    -h|--help|help|"") usage ;;
    *) echo "Okänt kommando: ${cmd}" >&2; usage; exit 1 ;;
  esac
}

main "$@"
