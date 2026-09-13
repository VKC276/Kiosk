#!/usr/bin/env python3
"""Skriv ut kiosk-URL:er från config.json (mode, health, browser, backend)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
server = cfg.get("SERVER") or {}
bind_host = server.get("host", "0.0.0.0")
host = "127.0.0.1" if bind_host in {"0.0.0.0", "::"} else bind_host
port = int(server.get("port", 8081))
cf = cfg.get("CLOUDFLARE") or {}
enabled = bool(cf.get("enabled"))
api = str(cf.get("apiUrl") or "").rstrip("/")
kiosk_id = str(cf.get("kioskId") or "reception")

if enabled and api:
    mode = "cloudflare"
    health = f"{api}/healthz"
    browser = f"{api}/?kiosk={kiosk_id}"
    backend = "agent"
else:
    mode = "local"
    health = f"http://{host}:{port}/healthz"
    browser = f"http://{host}:{port}/"
    backend = "gunicorn"

wanted = sys.argv[1] if len(sys.argv) > 1 else "all"
values = {
    "mode": mode,
    "health": health,
    "browser": browser,
    "backend": backend,
    "port": str(port),
    "host": host,
    "bind_host": bind_host,
    "api": api,
    "kiosk": kiosk_id,
}
if wanted == "all":
    for key, value in values.items():
        print(f"{key}={value}")
else:
    print(values.get(wanted, ""))
