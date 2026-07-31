#!/usr/bin/env bash
# Startar Chromium i fullskärm (inte hårdlåst kiosk) så Pi Connect m.m. fungerar.
# Använder flock så systemd/autostart inte öppnar nya flikar i en loop.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PORT="$(python3 - <<PY
import json
from pathlib import Path
cfg = json.loads(Path("${ROOT_DIR}/config.json").read_text(encoding="utf-8"))
print(int((cfg.get("SERVER") or {}).get("port", 8081)))
PY
)"
URL="http://127.0.0.1:${PORT}/"
PROFILE_DIR="${HOME}/.config/vkc-kiosk-chromium"
LOCK_FILE="${PROFILE_DIR}/.start.lock"
mkdir -p "${PROFILE_DIR}"

# Systemd saknar ofta session-DBus → Chromium loggar "Unknown address type".
# Sätt en giltig unix-address om session-bussen finns.
UID_NUM="$(id -u)"
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/${UID_NUM}}"
export XDG_RUNTIME_DIR="${RUNTIME_DIR}"
if [[ -S "${RUNTIME_DIR}/bus" ]]; then
  export DBUS_SESSION_BUS_ADDRESS="unix:path=${RUNTIME_DIR}/bus"
elif [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
  unset DBUS_SESSION_BUS_ADDRESS || true
fi

# Wayland (Pi OS Bookworm/labwc) om socket finns; annars X11.
if [[ -z "${WAYLAND_DISPLAY:-}" ]]; then
  for candidate in wayland-0 wayland-1; do
    if [[ -S "${RUNTIME_DIR}/${candidate}" ]]; then
      export WAYLAND_DISPLAY="${candidate}"
      break
    fi
  done
fi
export DISPLAY="${DISPLAY:-:0}"
if [[ -z "${XAUTHORITY:-}" && -f "${HOME}/.Xauthority" ]]; then
  export XAUTHORITY="${HOME}/.Xauthority"
fi

BROWSER=""
for candidate in chromium-browser chromium google-chrome google-chrome-stable; do
  if command -v "${candidate}" >/dev/null 2>&1; then
    BROWSER="$(command -v "${candidate}")"
    break
  fi
done

if [[ -z "${BROWSER}" ]]; then
  echo "Ingen Chromium/Chrome hittades. Installera med: sudo apt install chromium" >&2
  exit 1
fi

# En enda instans per profil — annars öppnar Chromium bara en ny flik
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "VKC Kiosk-browser körs redan (lock ${LOCK_FILE}) — ingen ny start."
  exit 0
fi

# Om en Chromium med samma profil redan lever: låt den vara
if pgrep -f -- "--user-data-dir=${PROFILE_DIR}" >/dev/null 2>&1; then
  echo "Chromium med kiosk-profil körs redan — ingen ny start."
  exit 0
fi

if [[ -z "${WAYLAND_DISPLAY:-}" ]] && command -v xset >/dev/null 2>&1; then
  xset s off >/dev/null 2>&1 || true
  xset -dpms >/dev/null 2>&1 || true
  xset s noblank >/dev/null 2>&1 || true
fi

echo "Startar ${BROWSER} → ${URL} (DISPLAY=${DISPLAY:-?} WAYLAND=${WAYLAND_DISPLAY:--} DBUS=${DBUS_SESSION_BUS_ADDRESS:-unset})"

# Behåll denna process som förgrund (viktigt för systemd).
# Ingen --kiosk (hårdlås); fullskärm räcker för Pi Connect.
exec "${BROWSER}" \
  --start-fullscreen \
  --user-data-dir="${PROFILE_DIR}" \
  --noerrdialogs \
  --disable-session-crashed-bubble \
  --disable-restore-session-state \
  --check-for-update-interval=31536000 \
  --autoplay-policy=no-user-gesture-required \
  --no-first-run \
  --no-default-browser-check \
  "${URL}"
