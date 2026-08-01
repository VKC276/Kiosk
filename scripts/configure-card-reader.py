#!/usr/bin/env python3
"""Interaktiv assistent: välj läsare, testa kortkonvertering, skriv config.json.

Exempel:
  ./venv/bin/python scripts/configure-card-reader.py
  vkc-kiosk configure-reader
"""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from card_convert import (  # noqa: E402
    card_processing_from_candidate,
    conversion_candidates,
    convert_card_id,
)

CONFIG_PATH = ROOT / "config.json"
SERVICE_API = "vkc-kiosk.service"


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
    print(f"\nSkrev {CONFIG_PATH}")
    print(f"Backup: {backup}")


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


def run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, capture_output=True)


def service_active(name: str) -> bool:
    return run(["systemctl", "is-active", "--quiet", name]).returncode == 0


def maybe_stop_service() -> bool:
    """Returnerar True om tjänsten stoppades (ska startas igen)."""
    if not service_active(SERVICE_API):
        return False
    print(
        f"\n{SERVICE_API} kör och kan hålla USB-läsaren. "
        "Assistenten behöver ofta exklusiv access."
    )
    if prompt_yes("Stoppa vkc-kiosk tillfälligt?", True):
        subprocess.run(["sudo", "systemctl", "stop", SERVICE_API], check=False)
        time.sleep(1)
        return True
    return False


def maybe_start_service(was_stopped: bool) -> None:
    if not was_stopped:
        return
    if prompt_yes("Starta vkc-kiosk igen?", True):
        subprocess.run(["sudo", "systemctl", "start", SERVICE_API], check=False)
        print("vkc-kiosk startad.")


def list_usb_readers() -> list[dict]:
    readers = []
    try:
        import usb.core
        import usb.util
    except ImportError:
        print("pyusb saknas — USB-backend otillgänglig. pip install pyusb")
        return readers

    for dev in usb.core.find(find_all=True) or []:
        try:
            manuf = usb.util.get_string(dev, dev.iManufacturer) if dev.iManufacturer else ""
        except Exception:
            manuf = ""
        try:
            product = usb.util.get_string(dev, dev.iProduct) if dev.iProduct else ""
        except Exception:
            product = ""
        name = " ".join(p for p in (manuf, product) if p).strip() or "USB-enhet"
        # Filtrera bort root hubs / rena hubbar
        if "hub" in name.lower() and "reader" not in name.lower():
            continue
        if dev.idVendor == 0x1D6B:  # Linux Foundation root hub
            continue
        if dev.idVendor == 0x1A40:  # Terminus hub
            continue
        readers.append(
            {
                "kind": "usb",
                "label": f"USB {dev.idVendor:04x}:{dev.idProduct:04x}  {name}",
                "vendor": int(dev.idVendor),
                "product": int(dev.idProduct),
                "name": name,
            }
        )
    return readers


def list_evdev_readers() -> list[dict]:
    readers = []
    try:
        from evdev import InputDevice, list_devices
    except ImportError:
        print("evdev saknas — input-backend otillgänglig.")
        return readers

    for path in sorted(list_devices()):
        try:
            dev = InputDevice(path)
        except OSError:
            continue
        name = dev.name or path
        # Hoppa över uppenbara icke-läsare
        low = name.lower()
        if any(x in low for x in ("power", "sleep", "hdmi", "vc4", "pwr")):
            continue
        readers.append(
            {
                "kind": "evdev",
                "label": f"evdev {path}  {name}",
                "device": path,
                "name": name,
            }
        )
    return readers


def choose_reader() -> dict:
    usb = list_usb_readers()
    evdev = list_evdev_readers()
    all_readers = usb + evdev
    if not all_readers:
        print("Inga läsare hittades. Koppla in läsaren och kör igen.")
        sys.exit(1)

    print("\nTillgängliga läsare:")
    for i, r in enumerate(all_readers, 1):
        marker = ""
        if r["kind"] == "usb" and r["vendor"] == 0xFFFF and r["product"] == 0x0035:
            marker = "  ← YAROGNTEC/SDZNKJLTD (kräver setup-yarogntec-reader.sh)"
        print(f"  {i}) {r['label']}{marker}")

    while True:
        choice = prompt("Välj läsare (nummer)", "1")
        if choice.isdigit() and 1 <= int(choice) <= len(all_readers):
            return all_readers[int(choice) - 1]
        print("Ogiltigt val.")


def capture_raw_usb(vendor: int, product: int, timeout_sec: float = 60.0) -> str:
    from reader_usb import HID_ENTER, HID_KEYMAP, _authorize_device
    import usb.core
    import usb.util

    _authorize_device(vendor, product)
    end = time.time() + timeout_sec
    print(f"\nBlippa ett kort mot USB-läsaren inom {int(timeout_sec)} s…")

    while time.time() < end:
        dev = usb.core.find(idVendor=vendor, idProduct=product)
        if dev is None:
            time.sleep(0.5)
            continue
        try:
            try:
                if dev.is_kernel_driver_active(0):
                    dev.detach_kernel_driver(0)
            except (ValueError, NotImplementedError, usb.core.USBError):
                pass
            try:
                dev.set_configuration()
            except usb.core.USBError:
                pass
            cfg = dev.get_active_configuration()
            intf = cfg[(0, 0)]
            usb.util.claim_interface(dev, intf.bInterfaceNumber)
            ep_in = usb.util.find_descriptor(
                intf,
                custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
                == usb.util.ENDPOINT_IN,
            )
            if ep_in is None:
                raise RuntimeError("Ingen IN-endpoint på interface 0")

            buf: list[str] = []
            prev_keys: set[int] = set()
            while time.time() < end:
                try:
                    data = dev.read(ep_in.bEndpointAddress, ep_in.wMaxPacketSize or 8, timeout=500)
                except usb.core.USBTimeoutError:
                    continue
                except usb.core.USBError as exc:
                    print(f"USB-läsfel: {exc}")
                    break
                if not data or len(data) < 3:
                    continue
                keys = {int(b) for b in data[2:] if b}
                pressed = keys - prev_keys
                prev_keys = keys
                for code in pressed:
                    if code in HID_KEYMAP:
                        buf.append(HID_KEYMAP[code])
                        sys.stdout.write(HID_KEYMAP[code])
                        sys.stdout.flush()
                    elif code in HID_ENTER and buf:
                        print()
                        raw = "".join(buf)
                        usb.util.dispose_resources(dev)
                        return raw
        finally:
            try:
                usb.util.dispose_resources(dev)
            except Exception:
                pass
        time.sleep(0.3)

    raise TimeoutError("Ingen kortblipp mottagen i tid.")


def capture_raw_evdev(device_path: str, timeout_sec: float = 60.0) -> str:
    from evdev import InputDevice, categorize, ecodes

    KEY_MAP = {
        ecodes.KEY_0: "0",
        ecodes.KEY_1: "1",
        ecodes.KEY_2: "2",
        ecodes.KEY_3: "3",
        ecodes.KEY_4: "4",
        ecodes.KEY_5: "5",
        ecodes.KEY_6: "6",
        ecodes.KEY_7: "7",
        ecodes.KEY_8: "8",
        ecodes.KEY_9: "9",
        ecodes.KEY_A: "A",
        ecodes.KEY_B: "B",
        ecodes.KEY_C: "C",
        ecodes.KEY_D: "D",
        ecodes.KEY_E: "E",
        ecodes.KEY_F: "F",
    }

    dev = InputDevice(device_path)
    print(f"\nBlippa ett kort ({device_path}) inom {int(timeout_sec)} s…")
    try:
        dev.grab()
    except OSError as exc:
        print(f"Varning: kunde inte grabba enheten ({exc}). Fortsätter ändå.")

    buf: list[str] = []
    end = time.time() + timeout_sec
    try:
        while time.time() < end:
            r, _, _ = select.select([dev.fd], [], [], 0.5)
            if not r:
                continue
            for event in dev.read():
                if event.type != ecodes.EV_KEY or event.value != 1:
                    continue
                if event.code in KEY_MAP:
                    ch = KEY_MAP[event.code]
                    buf.append(ch)
                    sys.stdout.write(ch)
                    sys.stdout.flush()
                elif event.code in (ecodes.KEY_ENTER, ecodes.KEY_KPENTER) and buf:
                    print()
                    return "".join(buf)
    finally:
        try:
            dev.ungrab()
        except OSError:
            pass
        dev.close()

    raise TimeoutError("Ingen kortblipp mottagen i tid.")


def capture_raw(reader: dict) -> str:
    if reader["kind"] == "usb":
        return capture_raw_usb(reader["vendor"], reader["product"])
    return capture_raw_evdev(reader["device"])


def print_candidates(raw: str, expected: str | None) -> list[dict]:
    combos = conversion_candidates(raw)
    print(f"\nRådata från läsaren: {raw!r} (len={len(raw)})")
    if expected:
        print(f"Förväntat kort-ID:     {expected}")
    print()
    print(f"{'#':>3}  {'FORMAT':<6} {'BYTE':<9} {'NIBBLE':<9} {'UID':>3}  {'RESULTAT':<22} LEN")
    print("-" * 72)
    for i, c in enumerate(combos, 1):
        mark = ""
        if expected and c["converted"] == expected:
            mark = "  ← MATCH"
        elif c["is_digits"] and 5 <= c["length"] <= 10:
            mark = "  (rimlig längd)"
        print(
            f"{i:>3}  {c['FORMAT']:<6} {c['BYTE_ORDER']:<9} {c['NIBBLE_ORDER']:<9} "
            f"{c['hexUidChars']:>3}  {c['converted']:<22} {c['length']}{mark}"
        )
    return combos


def choose_candidate(combos: list[dict], expected: str | None) -> dict:
    matches = [c for c in combos if expected and c["converted"] == expected]
    if matches:
        print(f"\n{len(matches)} kombination(er) matchar förväntat ID.")
        if len(matches) == 1 and prompt_yes("Använd den matchande konfigurationen?", True):
            return matches[0]
        if len(matches) > 1:
            print("Flera matcher — välj nummer i listan ovan.")

    while True:
        choice = prompt("Välj kombination att spara (nummer), eller q för avbryt")
        if choice.lower() in {"q", "quit", "avbryt"}:
            raise SystemExit(0)
        if choice.isdigit() and 1 <= int(choice) <= len(combos):
            return combos[int(choice) - 1]
        print("Ogiltigt val.")


def apply_reader_to_config(cfg: dict, reader: dict) -> None:
    reader_cfg = cfg.setdefault("READER", {})
    if reader["kind"] == "usb":
        reader_cfg["backend"] = "usb"
        reader_cfg["usbVendor"] = f"0x{reader['vendor']:04x}"
        reader_cfg["usbProduct"] = f"0x{reader['product']:04x}"
        reader_cfg["nameContains"] = reader.get("name") or reader_cfg.get("nameContains") or ""
    else:
        reader_cfg["backend"] = "evdev"
        reader_cfg["device"] = reader["device"]
        reader_cfg["nameContains"] = reader.get("name") or ""
        reader_cfg.setdefault("grab", True)


def main() -> int:
    print("=" * 60)
    print(" VKC Kiosk — konfigurera kortläsare & kortformat")
    print("=" * 60)
    print(f"Config: {CONFIG_PATH}")

    if not CONFIG_PATH.is_file():
        print("config.json saknas.")
        return 1

    cfg = load_config()
    stopped = maybe_stop_service()

    try:
        reader = choose_reader()
        print(f"\nVald: {reader['label']}")

        if (
            reader["kind"] == "usb"
            and reader["vendor"] == 0xFFFF
            and reader["product"] == 0x0035
        ):
            print(
                "\nDetta är YAROGNTEC/SDZNKJLTD. Om läsaren inte fungerar stabilt, kör först:\n"
                "  sudo ./scripts/setup-yarogntec-reader.sh && sudo reboot\n"
            )

        expected = prompt(
            "Vad ska kortets ID vara i medlemslistan? (Enter = visa alla förslag)",
            "",
        ) or None

        # Manuell rådata som fallback
        mode = prompt("Läs från läsare (l) eller klistra in rådata (k)?", "l").lower()
        if mode.startswith("k"):
            raw = prompt("Klistra in rådata från läsaren")
        else:
            try:
                raw = capture_raw(reader)
            except Exception as exc:
                print(f"\nKunde inte läsa från läsaren: {exc}")
                raw = prompt("Klistra in rådata manuellt i stället")

        if not raw:
            print("Tom rådata — avbryter.")
            return 1

        combos = print_candidates(raw, expected)
        chosen = choose_candidate(combos, expected)

        print("\nVald konfiguration:")
        print(f"  FORMAT:       {chosen['FORMAT']}")
        print(f"  BYTE_ORDER:   {chosen['BYTE_ORDER']}")
        print(f"  NIBBLE_ORDER: {chosen['NIBBLE_ORDER']}")
        print(f"  hexUidChars:  {chosen['hexUidChars']}")
        print(f"  Resultat:     {chosen['converted']}")

        # Snabb verifiering
        verify = convert_card_id(
            raw,
            card_format=chosen["FORMAT"],
            byte_order=chosen["BYTE_ORDER"],
            nibble_order=chosen["NIBBLE_ORDER"],
            hex_uid_chars=chosen["hexUidChars"],
        )
        assert verify == chosen["converted"]

        if not prompt_yes("Spara till config.json?", True):
            print("Inget sparat.")
            return 0

        apply_reader_to_config(cfg, reader)
        cfg["CARD_PROCESSING"] = card_processing_from_candidate(
            chosen, cfg.get("CARD_PROCESSING")
        )
        save_config(cfg)

        print("\nKlart. Tips:")
        print("  curl -s http://127.0.0.1:8081/api/cache/refresh")
        print("  vkc-kiosk restart")
        return 0
    finally:
        maybe_start_service(stopped)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nAvbrutet.")
        raise SystemExit(130)
