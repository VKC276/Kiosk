#!/usr/bin/env python3
"""Importera medlems- och 10-kortslistor från Google Apps Script till Cloudflare D1."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]


def load_config() -> dict:
    path = ROOT / "config.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_json(url: str, timeout: int) -> list:
    print(f"Hämtar {url} ...")
    response = requests.get(
        url,
        headers={"Accept": "application/json", "User-Agent": "vkc-kiosk-import"},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise SystemExit(f"Förväntade JSON-lista från {url}, fick {type(data)}")
    print(f"  {len(data)} rader")
    return data


def post_import(api: str, token: str, path: str, rows: list) -> None:
    url = f"{api.rstrip('/')}{path}"
    response = requests.post(
        url,
        json=rows,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=60,
    )
    if not response.ok:
        raise SystemExit(f"Importfel {path}: HTTP {response.status_code} {response.text[:300]}")
    print(f"  Cloudflare {path}: {response.json()}")


def main() -> int:
    cfg = load_config()
    cf = cfg.get("CLOUDFLARE") or {}
    parser = argparse.ArgumentParser(description="Importera GAS-listor till Cloudflare Worker")
    parser.add_argument("--api-url", default=cf.get("apiUrl") or "")
    parser.add_argument("--admin-token", default=cf.get("adminToken") or "")
    parser.add_argument("--members-url", default=cfg.get("DATA_URL") or "")
    parser.add_argument("--tencards-url", default=cfg.get("TEN_VISIT_DATA_URL") or "")
    parser.add_argument("--timeout", type=int, default=45)
    args = parser.parse_args()

    if not args.api_url or not args.admin_token:
        print("Saknar --api-url och/eller --admin-token (eller CLOUDFLARE i config.json).", file=sys.stderr)
        return 1

    if args.members_url:
        members = fetch_json(args.members_url, args.timeout)
        post_import(args.api_url, args.admin_token, "/api/admin/import/members", members)
    else:
        print("Hoppar över medlemmar (ingen DATA_URL / --members-url).")

    if args.tencards_url:
        tencards = fetch_json(args.tencards_url, args.timeout)
        post_import(args.api_url, args.admin_token, "/api/admin/import/tencards", tencards)
    else:
        print("Hoppar över 10-kort (ingen TEN_VISIT_DATA_URL / --tencards-url).")

    stats = requests.get(
        f"{args.api_url.rstrip('/')}/api/admin/stats",
        headers={"Authorization": f"Bearer {args.admin_token}"},
        timeout=20,
    )
    if stats.ok:
        print("Stats:", stats.json())
    print("Klart.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
