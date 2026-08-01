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
  pull                git pull (behåller config.json; stashar övrigt)
  update              pull + pip + ominstallation/restart
  config              Öppna config.json i \$EDITOR

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

cmd_pull() {
  # config.json ska ALDRIG komma från git. Backup → (unstash kod) → pull → restore.
  cd "${ROOT_DIR}"
  local branch backup stash_msg dirty=0
  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
  backup="${ROOT_DIR}/config.json.localbak"
  stash_msg="vkc-kiosk pull auto-stash $(date -Iseconds 2>/dev/null || date)"

  if [[ ! -f "${ROOT_DIR}/config.json" ]]; then
    echo "Varning: config.json saknas innan pull." >&2
  else
    cp -a "${ROOT_DIR}/config.json" "${backup}"
    echo "Säkerhetskopia: ${backup}"
  fi

  # Sluta tracka config lokalt (äldre kloner) innan pull kan skriva över den.
  if git ls-files --error-unmatch config.json >/dev/null 2>&1; then
    git rm --cached -f config.json >/dev/null 2>&1 || true
  fi

  if ! git diff --quiet || ! git diff --cached --quiet \
     || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
    dirty=1
    echo "Lokala kodändringar hittades — sparar i git stash innan pull..."
    git stash push -u -m "${stash_msg}" || {
      echo "Kunde inte stash:a lokala ändringar. Avbryter." >&2
      [[ -f "${backup}" ]] && cp -a "${backup}" "${ROOT_DIR}/config.json"
      return 1
    }
    echo "Stash: ${stash_msg}"
  fi

  local rc=0
  git pull --ff-only origin "${branch}" || rc=$?

  # Alltid återställ config från backup tagen FÖRE stash/pull.
  if [[ -f "${backup}" ]]; then
    cp -a "${backup}" "${ROOT_DIR}/config.json"
    echo "Återställde din lokala config.json från ${backup}"
  elif [[ ! -f "${ROOT_DIR}/config.json" && -f "${ROOT_DIR}/config.example.json" ]]; then
    cp -a "${ROOT_DIR}/config.example.json" "${ROOT_DIR}/config.json"
    echo "Varning: skapade config.json från example — fyll i dina URL:er." >&2
  fi

  if [[ "${rc}" -ne 0 ]]; then
    echo "git pull misslyckades (kod ${rc})." >&2
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
