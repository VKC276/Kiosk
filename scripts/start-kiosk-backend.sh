#!/usr/bin/env bash
# Startar kortläsar-agenten mot Cloudflare Worker.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

PYTHON="${ROOT_DIR}/venv/bin/python"
if [[ ! -x "${PYTHON}" ]]; then
  PYTHON="python3"
fi

if [[ ! -f "${ROOT_DIR}/config.json" ]]; then
  echo "FEL: config.json saknas. Kopiera config.example.json och fyll i CLOUDFLARE." >&2
  exit 1
fi

MODE="$("${PYTHON}" "${ROOT_DIR}/scripts/kiosk-urls.py" mode)"
if [[ "${MODE}" != "cloudflare" ]]; then
  echo "FEL: CLOUDFLARE.apiUrl och token måste vara satta i config.json." >&2
  echo "Tips: sudo KIOSK_TOKEN='...' ./scripts/switch-to-cloudflare.sh" >&2
  exit 1
fi

echo "VKC backend: agent.py → $("${PYTHON}" "${ROOT_DIR}/scripts/kiosk-urls.py" api)"
exec "${PYTHON}" "${ROOT_DIR}/agent.py"
