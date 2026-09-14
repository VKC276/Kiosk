#!/usr/bin/env python3
"""Slå på Cloudflare i config.json utan att röra READER / CARD_PROCESSING."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API = "https://vkc-kiosk.muddy-rice-38d4.workers.dev"
PLACEHOLDERS = {"", "REPLACE_ME", "REPLACE_ME_KIOSK_TOKEN"}


def is_placeholder(value: object) -> bool:
    return str(value or "").strip() in PLACEHOLDERS


def merge_cloudflare(
    cfg: dict,
    *,
    api_url: str,
    token: str | None,
    kiosk_id: str,
    kiosk_url: str,
    timeout_seconds: float,
) -> dict:
    reader = cfg.get("READER")
    card = cfg.get("CARD_PROCESSING")
    cf = dict(cfg.get("CLOUDFLARE") or {})
    existing_token = str(cf.get("token") or "")
    chosen = token if token is not None and not is_placeholder(token) else existing_token
    if is_placeholder(chosen):
        raise SystemExit(
            "CLOUDFLARE.token saknas. Sätt samma värde som Worker-secret KIOSK_TOKEN:\n"
            "  python3 scripts/enable-cloudflare-config.py --token 'DIN_KIOSK_TOKEN'"
        )
    cf.update(
        {
            "enabled": True,
            "apiUrl": api_url.rstrip("/"),
            "kioskUrl": kiosk_url,
            "kioskId": kiosk_id,
            "token": chosen,
            "adminToken": "",
            "timeoutSeconds": timeout_seconds,
        }
    )
    cfg["CLOUDFLARE"] = cf
    if isinstance(reader, dict):
        cfg["READER"] = reader
    if isinstance(card, dict):
        cfg["CARD_PROCESSING"] = card
    return cfg


def main() -> int:
    parser = argparse.ArgumentParser(description="Aktivera Cloudflare i config.json (behåller läsarinställningar)")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--api-url", default=DEFAULT_API)
    parser.add_argument("--token", default=None, help="KIOSK_TOKEN (annars befintlig config)")
    parser.add_argument("--kiosk-id", default="reception")
    parser.add_argument(
        "--kiosk-url",
        default="",
        help="Tom = Chromium öppnar Workern. Sätt GitHub Pages-URL om den redan har api=-stöd.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=5)
    args = parser.parse_args()

    if not args.config.is_file():
        print(f"Hittar inte {args.config}", file=sys.stderr)
        return 1

    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    before_reader = json.dumps(cfg.get("READER"), sort_keys=True)
    before_card = json.dumps(cfg.get("CARD_PROCESSING"), sort_keys=True)
    merge_cloudflare(
        cfg,
        api_url=args.api_url,
        token=args.token,
        kiosk_id=args.kiosk_id,
        kiosk_url=args.kiosk_url,
        timeout_seconds=args.timeout_seconds,
    )
    after_reader = json.dumps(cfg.get("READER"), sort_keys=True)
    after_card = json.dumps(cfg.get("CARD_PROCESSING"), sort_keys=True)
    if before_reader != after_reader or before_card != after_card:
        print("Avbrutet: READER eller CARD_PROCESSING skulle ha ändrats.", file=sys.stderr)
        return 1

    args.config.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Cloudflare på: {cfg['CLOUDFLARE']['apiUrl']} (READER/CARD_PROCESSING oförändrade)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
