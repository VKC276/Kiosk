#!/usr/bin/env python3
"""Hantera kiosk-karusellen (KIOSK.slides) i config.json.

Lägg till / ta bort / ändra webbadresser, ordning och visningstid
utan manuell JSON-redigering.

Exempel:
  ./venv/bin/python scripts/manage-slides.py
  vkc-kiosk slides
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(cfg: dict) -> None:
    backup = CONFIG_PATH.with_suffix(".json.bak")
    if CONFIG_PATH.exists():
        shutil.copy2(CONFIG_PATH, backup)
    CONFIG_PATH.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nSparade {CONFIG_PATH}")
    print(f"Backup:  {backup}")


def prompt(text: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{text}{suffix}: ").strip()
    if not value and default is not None:
        return default
    return value


def prompt_yes(text: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    value = input(f"{text} [{hint}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "j", "ja"}


def prompt_int(text: str, default: int | None = None, minimum: int = 1) -> int:
    while True:
        raw = prompt(text, str(default) if default is not None else None)
        try:
            value = int(raw)
            if value < minimum:
                print(f"Måste vara minst {minimum}.")
                continue
            return value
        except ValueError:
            print("Ange ett heltal.")


def slides_of(cfg: dict) -> list[dict]:
    kiosk = cfg.setdefault("KIOSK", {})
    slides = kiosk.setdefault("slides", [])
    if not isinstance(slides, list):
        slides = []
        kiosk["slides"] = slides
    return slides


def global_reload_default(cfg: dict) -> int:
    try:
        return int((cfg.get("KIOSK") or {}).get("reloadIntervalSeconds", 300))
    except (TypeError, ValueError):
        return 300


def slide_duration_seconds(slide: dict) -> int:
    if slide.get("durationSeconds") is not None:
        return max(1, int(float(slide["durationSeconds"])))
    if slide.get("durationMs") is not None:
        return max(1, int(round(float(slide["durationMs"]) / 1000)))
    return 30


def slide_reload_label(slide: dict, global_default: int) -> str:
    if "reloadIntervalSeconds" not in slide or slide.get("reloadIntervalSeconds") is None:
        return f"default({global_default}s)"
    try:
        value = int(slide["reloadIntervalSeconds"])
    except (TypeError, ValueError):
        return f"default({global_default}s)"
    if value <= 0:
        return "aldrig"
    return f"{value}s"


def prompt_reload_interval(slide: dict | None, global_default: int) -> int | None:
    """Returnerar int, eller None = ärv global standard (ta bort nyckel)."""
    print(
        "Refresh-intervall: hur ofta sidan får hämtas om när den visas.\n"
        "  heltal sekunder  = egen refresh (t.ex. 120 för tidskritiskt)\n"
        "  0               = aldrig refresh (statiskt tills kiosk-omstart)\n"
        "  d / default     = använd global KIOSK.reloadIntervalSeconds"
        f" (nu {global_default}s)"
    )
    if slide is not None and "reloadIntervalSeconds" in slide and slide.get("reloadIntervalSeconds") is not None:
        current = str(int(slide["reloadIntervalSeconds"]))
    else:
        current = "d"
    raw = prompt("Refresh-intervall", current).strip().lower()
    if raw in {"", "d", "default", "global"}:
        return None
    try:
        value = int(raw)
    except ValueError:
        print("Ogiltigt värde — behåller previous/default.")
        if slide is not None and "reloadIntervalSeconds" in slide:
            try:
                return int(slide["reloadIntervalSeconds"])
            except (TypeError, ValueError):
                return None
        return None
    return max(0, value)


def apply_reload_interval(slide: dict, value: int | None) -> None:
    if value is None:
        slide.pop("reloadIntervalSeconds", None)
    else:
        slide["reloadIntervalSeconds"] = int(value)


def normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise ValueError("Tom webbadress")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.netloc:
        raise ValueError(f"Ogiltig webbadress: {url}")
    return url


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text or "slide"


def unique_id(slides: list[dict], base: str) -> str:
    base = slugify(base)[:40]
    existing = {str(s.get("id") or "") for s in slides}
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


def list_slides(slides: list[dict], global_default: int = 300) -> None:
    if not slides:
        print("\n(Karusellen är tom)")
        return
    print("\nNuvarande karusell:")
    print(f"Global refresh-default: {global_default}s (KIOSK.reloadIntervalSeconds)")
    print(f"{'#':>3}  {'VISA':>5}  {'REFRESH':<14}  {'ID':<18}  TITEL / URL")
    print("-" * 86)
    for i, slide in enumerate(slides, 1):
        title = slide.get("title") or slide.get("id") or "(utan titel)"
        url = slide.get("url") or ""
        sid = str(slide.get("id") or "")[:18]
        refresh = slide_reload_label(slide, global_default)
        print(
            f"{i:>3}  {slide_duration_seconds(slide):>4}s  {refresh:<14}  {sid:<18}  {title}"
        )
        print(f"{'':>3}  {'':>5}  {'':<14}  {'':<18}  {url}")


def cmd_add(slides: list[dict], global_default: int) -> None:
    print("\n— Lägg till sida —")
    while True:
        try:
            url = normalize_url(prompt("Webbadress (https://...)"))
            break
        except ValueError as exc:
            print(exc)

    default_title = urlparse(url).netloc or "Ny sida"
    title = prompt("Titel (visningsnamn)", default_title)
    duration = prompt_int("Visningstid i sekunder", 30, minimum=1)
    reload_interval = prompt_reload_interval(None, global_default)
    position = prompt_int(
        f"Ordning (1 = först, {len(slides) + 1} = sist)",
        len(slides) + 1,
        minimum=1,
    )
    position = min(position, len(slides) + 1)

    slide = {
        "id": unique_id(slides, title),
        "title": title,
        "url": url,
        "durationSeconds": duration,
    }
    apply_reload_interval(slide, reload_interval)
    slides.insert(position - 1, slide)
    print(f"Tillagd på plats {position}: {title}")


def cmd_remove(slides: list[dict], global_default: int) -> None:
    if not slides:
        print("Inget att ta bort.")
        return
    list_slides(slides, global_default)
    index = prompt_int("Nummer att ta bort", minimum=1)
    if index > len(slides):
        print("Ogiltigt nummer.")
        return
    slide = slides[index - 1]
    label = slide.get("title") or slide.get("url") or slide.get("id")
    if not prompt_yes(f"Ta bort '{label}'?", True):
        print("Avbrutet.")
        return
    slides.pop(index - 1)
    print("Borttagen.")


def cmd_edit(slides: list[dict], global_default: int) -> None:
    if not slides:
        print("Inget att ändra.")
        return
    list_slides(slides, global_default)
    index = prompt_int("Nummer att ändra", minimum=1)
    if index > len(slides):
        print("Ogiltigt nummer.")
        return
    slide = slides[index - 1]
    print("\nLämna tomt / defaultvärde för att behålla nuvarande värde där det anges.")

    try:
        url_in = prompt("Webbadress", slide.get("url") or "")
        slide["url"] = normalize_url(url_in)
    except ValueError as exc:
        print(exc)
        return

    slide["title"] = prompt("Titel", slide.get("title") or "")
    slide["durationSeconds"] = prompt_int(
        "Visningstid i sekunder",
        slide_duration_seconds(slide),
        minimum=1,
    )
    slide.pop("durationMs", None)
    apply_reload_interval(slide, prompt_reload_interval(slide, global_default))

    new_pos = prompt_int("Ordning", index, minimum=1)
    new_pos = min(new_pos, len(slides))
    if new_pos != index:
        slides.pop(index - 1)
        slides.insert(new_pos - 1, slide)
    print("Uppdaterad.")


def cmd_move(slides: list[dict], global_default: int) -> None:
    if len(slides) < 2:
        print("Behöver minst två sidor för att ändra ordning.")
        return
    list_slides(slides, global_default)
    index = prompt_int("Vilken sida ska flyttas?", minimum=1)
    if index > len(slides):
        print("Ogiltigt nummer.")
        return
    new_pos = prompt_int("Ny ordning", index, minimum=1)
    new_pos = min(new_pos, len(slides))
    slide = slides.pop(index - 1)
    slides.insert(new_pos - 1, slide)
    print(f"Flyttade till plats {new_pos}.")


def main() -> int:
    print("=" * 60)
    print(" VKC Kiosk — hantera karusell (slides)")
    print("=" * 60)
    print(f"Config: {CONFIG_PATH}")

    if not CONFIG_PATH.is_file():
        print("config.json saknas.")
        return 1

    cfg = load_config()
    slides = slides_of(cfg)
    global_default = global_reload_default(cfg)
    dirty = False

    actions = {
        "1": ("Lista sidor", lambda: list_slides(slides, global_default)),
        "2": ("Lägg till sida", lambda: cmd_add(slides, global_default)),
        "3": ("Ta bort sida", lambda: cmd_remove(slides, global_default)),
        "4": ("Ändra sida (url/tid/refresh/ordning)", lambda: cmd_edit(slides, global_default)),
        "5": ("Flytta ordning", lambda: cmd_move(slides, global_default)),
        "s": ("Spara till config.json", None),
        "q": ("Avsluta", None),
    }

    list_slides(slides, global_default)

    while True:
        print("\nVälj:")
        for key, (label, _) in actions.items():
            print(f"  {key}) {label}")
        choice = prompt("Val", "1").lower()

        if choice == "q":
            if dirty and prompt_yes("Osparade ändringar finns. Spara innan avslut?", True):
                save_config(cfg)
                print("Tips: vkc-kiosk restart  (så browsern laddar om slides)")
            elif dirty:
                print("Avslutar utan att spara.")
            break

        if choice == "s":
            save_config(cfg)
            dirty = False
            print("Tips: vkc-kiosk restart  (så browsern laddar om slides)")
            continue

        action = actions.get(choice)
        if not action:
            print("Okänt val.")
            continue
        _, fn = action
        before = json.dumps(slides, ensure_ascii=False)
        fn()
        after = json.dumps(slides, ensure_ascii=False)
        if before != after:
            dirty = True

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nAvbrutet.")
        raise SystemExit(130)
