#!/usr/bin/env bash
# Startar antingen Cloudflare-agenten eller den lokala Flask/Gunicorn-servern.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

PYTHON="${ROOT_DIR}/venv/bin/python"
if [[ ! -x "${PYTHON}" ]]; then
  PYTHON="python3"
fi

MODE="$("${PYTHON}" "${ROOT_DIR}/scripts/kiosk-urls.py" mode)"
BACKEND="$("${PYTHON}" "${ROOT_DIR}/scripts/kiosk-urls.py" backend)"
HOST="$("${PYTHON}" "${ROOT_DIR}/scripts/kiosk-urls.py" bind_host)"
PORT="$("${PYTHON}" "${ROOT_DIR}/scripts/kiosk-urls.py" port)"

echo "VKC backend: mode=${MODE} backend=${BACKEND}"

if [[ "${BACKEND}" == "agent" ]]; then
  exec "${PYTHON}" "${ROOT_DIR}/agent.py"
fi

exec "${PYTHON}" -m gunicorn \
  -w 1 \
  -k gthread \
  --threads 4 \
  --timeout 0 \
  -b "${HOST}:${PORT}" \
  wsgi:app
