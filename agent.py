"""Kiosk-agent: lyssnar på kortläsaren och checkar in mot Cloudflare Worker.

Ingen lokal Flask-server. Chromium visar Worker-UI; den här processen
skickar bara blippade kort-ID:n till POST /api/checkin.
"""

from __future__ import annotations

import json
import os
import signal
import threading
import time

import requests
from evdev import InputDevice, ecodes, list_devices

from card_convert import convert_card_id as convert_card_id_with_options

SHOULD_RUN = True
ACTIVE_READER_DEVICE = None
LAST_ERROR = None
CHECKS_OK = 0
CHECKS_FAIL = 0

CARD_KEY_CODES = {
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


def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def cfg_section(config, name, default=None):
    value = config.get(name)
    if isinstance(value, dict):
        return value
    return default if default is not None else {}


config = load_config()
READER_CFG = cfg_section(config, "READER")
CARD_CFG = cfg_section(config, "CARD_PROCESSING")
CF_CFG = cfg_section(config, "CLOUDFLARE")
TIMEOUTS_CFG = cfg_section(config, "TIMEOUTS")

READER_DEVICE = READER_CFG.get("device") or config.get("READER_DEVICE") or "/dev/input/event0"
READER_NAME_CONTAINS = (READER_CFG.get("nameContains") or "").strip()
READER_GRAB = bool(READER_CFG.get("grab", True))
READER_BACKEND = str(READER_CFG.get("backend", "auto")).lower()
READER_USB_VENDOR = int(str(READER_CFG.get("usbVendor", "0xffff")), 0)
READER_USB_PRODUCT = int(str(READER_CFG.get("usbProduct", "0x0035")), 0)

CARD_FORMAT = str(CARD_CFG.get("FORMAT", "DEC10")).upper()
BYTE_ORDER = str(CARD_CFG.get("BYTE_ORDER", "NORMAL")).upper()
NIBBLE_ORDER = str(CARD_CFG.get("NIBBLE_ORDER", "NORMAL")).upper()
HEX_UID_CHARS = int(CARD_CFG.get("hexUidChars", 8))
MIN_CARD_ID_LENGTH = int(CARD_CFG.get("minIdLength", 5))
MAX_CARD_ID_LENGTH = int(CARD_CFG.get("maxIdLength", 10))
DECIMAL_PAD_LENGTH = int(CARD_CFG.get("decimalPadLength", 10))

CF_API_URL = str(CF_CFG.get("apiUrl") or "").rstrip("/")
CF_KIOSK_ID = str(CF_CFG.get("kioskId") or "reception")
CF_TOKEN = str(CF_CFG.get("token") or "")
CF_TIMEOUT = float(CF_CFG.get("timeoutSeconds") or TIMEOUTS_CFG.get("clipRequestSeconds") or 5)

session = requests.Session()
session.headers.update(
    {
        "Authorization": f"Bearer {CF_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "vkc-kiosk-agent",
    }
)


def convert_card_id(raw_card_id: str) -> str:
    return convert_card_id_with_options(
        raw_card_id,
        card_format=CARD_FORMAT,
        byte_order=BYTE_ORDER,
        nibble_order=NIBBLE_ORDER,
        hex_uid_chars=HEX_UID_CHARS,
        decimal_pad_length=DECIMAL_PAD_LENGTH,
    )


def list_input_devices_info():
    devices = []
    for path in sorted(list_devices()):
        try:
            dev = InputDevice(path)
            devices.append({"path": path, "name": dev.name})
        except OSError as exc:
            devices.append({"path": path, "name": None, "error": str(exc)})
    return devices


def resolve_reader_device():
    if READER_NAME_CONTAINS:
        needle = READER_NAME_CONTAINS.lower()
        matches = [
            d
            for d in list_input_devices_info()
            if d.get("name") and needle in d["name"].lower()
        ]
        if len(matches) == 1:
            return matches[0]["path"]
        if len(matches) > 1:
            print(
                f"VARNING: nameContains '{READER_NAME_CONTAINS}' matchade flera enheter. "
                "Använder device-path om den finns."
            )
        elif not READER_DEVICE:
            print(f"KRITISKT FEL: Ingen input-enhet matchade '{READER_NAME_CONTAINS}'.")
            return None
    return READER_DEVICE or None


def resolve_reader_backend():
    if READER_BACKEND in {"usb", "pyusb"}:
        return "usb"
    if READER_BACKEND in {"evdev", "input"}:
        return "evdev"
    if READER_USB_VENDOR == 0xFFFF and READER_USB_PRODUCT == 0x0035:
        return "usb"
    if READER_CFG.get("usbVendor") or READER_CFG.get("usbProduct"):
        return "usb"
    return "evdev"


def post_json(path: str, payload: dict) -> dict | None:
    global LAST_ERROR, CHECKS_OK, CHECKS_FAIL
    if not CF_API_URL or not CF_TOKEN:
        LAST_ERROR = "CLOUDFLARE.apiUrl eller token saknas i config.json"
        print(f"FEL: {LAST_ERROR}")
        CHECKS_FAIL += 1
        return None
    url = f"{CF_API_URL}{path}"
    try:
        response = session.post(url, json=payload, timeout=CF_TIMEOUT)
        if response.status_code >= 400:
            LAST_ERROR = f"HTTP {response.status_code}: {response.text[:200]}"
            print(f"CF FEL: {LAST_ERROR}")
            CHECKS_FAIL += 1
            return None
        LAST_ERROR = None
        CHECKS_OK += 1
        try:
            return response.json()
        except json.JSONDecodeError:
            return {"ok": True}
    except requests.RequestException as exc:
        LAST_ERROR = str(exc)
        CHECKS_FAIL += 1
        print(f"CF NÄTVERKSFEL: {exc}")
        return None


def notify_reading():
    threading.Thread(
        target=post_json,
        args=("/api/checkin/reading", {"kiosk_id": CF_KIOSK_ID}),
        daemon=True,
    ).start()


def process_raw_card_id(raw_id: str) -> None:
    print(
        f"KORT RÅDATA: {raw_id!r} (len={len(raw_id)}) "
        f"format={CARD_FORMAT}/{BYTE_ORDER}/nibble={NIBBLE_ORDER}"
    )
    processed_id = convert_card_id(raw_id)
    processed_id_len = len(processed_id)
    print(f"KORT EFTER KONVERT: {processed_id!r} (len={processed_id_len})")
    is_valid = (
        processed_id.isdigit()
        and MIN_CARD_ID_LENGTH <= processed_id_len <= MAX_CARD_ID_LENGTH
    )
    if not is_valid:
        print(f"VARNING: Ogiltigt kort-ID efter konvertering: {processed_id!r}")
        return

    result = post_json(
        "/api/checkin",
        {"card_id": processed_id, "kiosk_id": CF_KIOSK_ID},
    )
    if result and result.get("status"):
        status = result["status"]
        print(
            f"CF OK: {status.get('status')} — {status.get('message')} "
            f"({status.get('card_number_dec')})"
        )


def parse_card_id(key_events):
    return "".join(CARD_KEY_CODES[event.code] for event in key_events if event.code in CARD_KEY_CODES)


def usb_card_reader_thread_entry():
    global ACTIVE_READER_DEVICE
    from reader_usb import usb_card_reader_thread

    ACTIVE_READER_DEVICE = f"usb:{READER_USB_VENDOR:#06x}:{READER_USB_PRODUCT:#06x}"
    usb_card_reader_thread(
        vendor_id=READER_USB_VENDOR,
        product_id=READER_USB_PRODUCT,
        on_raw_id=process_raw_card_id,
        should_run=lambda: SHOULD_RUN,
        on_start_read=notify_reading,
    )


def card_reader_thread():
    global ACTIVE_READER_DEVICE
    device_path = resolve_reader_device()
    if not device_path:
        print("KRITISKT FEL: Ingen kortläsare angiven.")
        return
    ACTIVE_READER_DEVICE = device_path
    try:
        dev = InputDevice(device_path)
        print(f"Kortläsartråd startad. Lyssnar på: {dev.name} ({device_path})")
        if READER_GRAB:
            dev.grab()
    except Exception as exc:
        print(f"KRITISKT FEL: Kunde inte öppna läsare: {exc}")
        return

    key_events = []
    try:
        for event in dev.read_loop():
            if not SHOULD_RUN:
                break
            if event.type == ecodes.EV_KEY and event.value == 1:
                if event.code in CARD_KEY_CODES:
                    if not key_events:
                        notify_reading()
                    key_events.append(event)
                elif event.code in (ecodes.KEY_ENTER, ecodes.KEY_KPENTER):
                    if key_events:
                        raw_id = parse_card_id(key_events)
                        key_events = []
                        process_raw_card_id(raw_id)
    except Exception as exc:
        print(f"KRITISKT FEL i lästråd: {exc}")
    finally:
        if READER_GRAB:
            try:
                dev.ungrab()
            except Exception:
                pass


def start_reader():
    backend = resolve_reader_backend()
    if backend == "usb":
        time.sleep(2.0)
        usb_card_reader_thread_entry()
    else:
        card_reader_thread()


def handle_stop(signum, _frame):
    global SHOULD_RUN
    print(f"Stoppsignal {signum} — avslutar.")
    SHOULD_RUN = False


def main():
    if not CF_API_URL:
        print("FEL: Sätt CLOUDFLARE.apiUrl i config.json")
        return 1
    if not CF_TOKEN:
        print("FEL: Sätt CLOUDFLARE.token i config.json")
        return 1

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)
    print(f"VKC kiosk-agent mot {CF_API_URL} (kiosk={CF_KIOSK_ID})")
    start_reader()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
