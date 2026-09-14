#!/usr/bin/env bash
# Byt en redan installerad Pi från lokal Flask/GAS till Cloudflare-agent.
# Behåller config.json READER + CARD_PROCESSING. Kör inte setup-reader.
#
#   sudo KIOSK_TOKEN='samma-som-wrangler-secret' ./scripts/switch-to-cloudflare.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRANCH_DEFAULT="cursor/cloudflare-kiosk-checkin-a077"
API_DEFAULT="https://vkc-kiosk.muddy-rice-38d4.workers.dev"

log()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mVarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mFel:\033[0m %s\n' "$*" >&2; exit 1; }

if [[ "${EUID}" -ne 0 ]]; then
  die "Kör som root: sudo KIOSK_TOKEN=... ./scripts/switch-to-cloudflare.sh"
fi

KIOSK_USER="${KIOSK_USER:-${SUDO_USER:-}}"
if [[ -z "${KIOSK_USER}" || "${KIOSK_USER}" == "root" ]]; then
  KIOSK_USER="$(stat -c '%U' "${ROOT_DIR}")"
fi
[[ -n "${KIOSK_USER}" && "${KIOSK_USER}" != "root" ]] || die "Sätt KIOSK_USER=..."

KIOSK_BRANCH="${KIOSK_BRANCH:-${BRANCH_DEFAULT}}"
KIOSK_TOKEN="${KIOSK_TOKEN:-}"
API_URL="${API_URL:-${API_DEFAULT}}"
KIOSK_URL="${KIOSK_URL:-}"
KIOSK_ID="${KIOSK_ID:-reception}"

as_user() {
  sudo -u "${KIOSK_USER}" -- "$@"
}

log "Användare ${KIOSK_USER}, katalog ${ROOT_DIR}, gren ${KIOSK_BRANCH}"

cd "${ROOT_DIR}"

if [[ ! -f "${ROOT_DIR}/config.json" ]]; then
  die "config.json saknas. Avbryter så läsarinställningar inte skrivs över av example."
fi

pull_bak="$(mktemp /tmp/vkc-kiosk-config.XXXXXX.json)"
cp -a "${ROOT_DIR}/config.json" "${pull_bak}"
as_user mkdir -p "/home/${KIOSK_USER}/.config/vkc-kiosk"
as_user cp -a "${ROOT_DIR}/config.json" "/home/${KIOSK_USER}/.config/vkc-kiosk/config.json"
log "Sparade config.json (${pull_bak} och ~/.config/vkc-kiosk/)"

if [[ -d "${ROOT_DIR}/.git" ]]; then
  log "Hämtar kod (${KIOSK_BRANCH})"
  as_user git -C "${ROOT_DIR}" fetch origin
  if ! as_user git -C "${ROOT_DIR}" checkout -B "${KIOSK_BRANCH}" "origin/${KIOSK_BRANCH}"; then
    die "Kunde inte checka ut origin/${KIOSK_BRANCH}. Finns grenen på GitHub?"
  fi
fi

cp -a "${pull_bak}" "${ROOT_DIR}/config.json"
chown "${KIOSK_USER}:${KIOSK_USER}" "${ROOT_DIR}/config.json"

log "Slår på Cloudflare i config (READER orörd)"
enable_args=(
  "${ROOT_DIR}/scripts/enable-cloudflare-config.py"
  --config "${ROOT_DIR}/config.json"
  --api-url "${API_URL}"
  --kiosk-id "${KIOSK_ID}"
  --kiosk-url "${KIOSK_URL}"
)
if [[ -n "${KIOSK_TOKEN}" ]]; then
  enable_args+=(--token "${KIOSK_TOKEN}")
fi
if [[ -x "${ROOT_DIR}/venv/bin/python" ]]; then
  as_user "${ROOT_DIR}/venv/bin/python" "${enable_args[@]}"
else
  as_user python3 "${enable_args[@]}"
fi

as_user cp -a "${ROOT_DIR}/config.json" "/home/${KIOSK_USER}/.config/vkc-kiosk/config.json"
rm -f "${pull_bak}"

log "Städar Flask/Gunicorn (inte USB-läsare)"
"${ROOT_DIR}/scripts/retire-local-kiosk.sh"

log "Ominstallerar tjänster utan apt och utan USB-quirk"
export SKIP_APT=1
export SKIP_READER=1
export KIOSK_USER
export KIOSK_DIR="${ROOT_DIR}"
"${ROOT_DIR}/install.sh"

log "Klart. Chromium ska öppna Workern, vkc-kiosk.service ska köra agent.py"
echo "Kontroll:"
echo "  vkc-kiosk url"
echo "  vkc-kiosk status"
echo "  journalctl -u vkc-kiosk -f"
