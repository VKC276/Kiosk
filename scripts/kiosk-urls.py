#!/usr/bin/env python3
"""Skriv ut kiosk-URL:er från config.json (mode, health, browser, backend)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
cfg_path = ROOT / "config.json"
if not cfg_path.is_file():
    print("config.json saknas", file=sys.stderr)
    sys.exit(1)

cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
cf = cfg.get("CLOUDFLARE") or {}
api = str(cf.get("apiUrl") or "").rstrip("/")
token = str(cf.get("token") or "").strip()
kiosk_id = str(cf.get("kioskId") or "reception")
kiosk_url = str(cf.get("kioskUrl") or "").strip()
enabled = bool(cf.get("enabled", True))

if enabled and api and token and token not in {"REPLACE_ME", "REPLACE_ME_KIOSK_TOKEN"}:
    mode = "cloudflare"
    health = f"{api}/healthz"
    if kiosk_url:
        joiner = "&" if "?" in kiosk_url else "?"
        browser = f"{kiosk_url}{joiner}api={api}&kiosk={kiosk_id}"
    else:
        browser = f"{api}/?kiosk={kiosk_id}"
    backend = "agent"
else:
    mode = "unconfigured"
    health = ""
    browser = ""
    backend = "none"

wanted = sys.argv[1] if len(sys.argv) > 1 else "all"
values = {
    "mode": mode,
    "health": health,
    "browser": browser,
    "backend": backend,
    "api": api,
    "kiosk": kiosk_id,
}
if wanted == "all":
    for key, value in values.items():
        print(f"{key}={value}")
else:
    print(values.get(wanted, ""))
