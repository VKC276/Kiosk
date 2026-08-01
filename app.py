import json
import os
import threading
import time
import queue

import requests
from evdev import InputDevice, ecodes, list_devices
from flask import Flask, jsonify, render_template

from card_convert import convert_card_id as convert_card_id_with_options

# --- KONFIGURATION OCH GLOBALA VARIABLER ---

current_card_status = None
LAST_READ_TIME = 0
IS_CLIPPING_ACTIVE = False
STATUS_LOCK = threading.Lock()
sse_queue = queue.Queue()

_THREADS_STARTED = False
_THREADS_START_LOCK = threading.Lock()

CARD_CACHE = []
TENCARD_CACHE = {}
CACHE_LAST_UPDATE = 0
CACHE_BOOTSTRAP_DONE = False  # False tills första GAS-hämtningen försökt klart
SHOULD_RUN = True
ACTIVE_READER_DEVICE = None

CARD_KEY_CODES = {
    ecodes.KEY_0: '0', ecodes.KEY_1: '1', ecodes.KEY_2: '2', ecodes.KEY_3: '3',
    ecodes.KEY_4: '4', ecodes.KEY_5: '5', ecodes.KEY_6: '6', ecodes.KEY_7: '7',
    ecodes.KEY_8: '8', ecodes.KEY_9: '9',
    ecodes.KEY_A: 'A', ecodes.KEY_B: 'B', ecodes.KEY_C: 'C',
    ecodes.KEY_D: 'D', ecodes.KEY_E: 'E', ecodes.KEY_F: 'F',
}


def load_config():
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(
            "FEL: Kunde inte ladda config.json. "
            f"Kontrollera att filen finns och har korrekt JSON-syntax. Fel: {e}"
        )
        return {}


def cfg_section(name, default=None):
    value = config.get(name)
    if isinstance(value, dict):
        return value
    return default if default is not None else {}


config = load_config()

READER_CFG = cfg_section("READER")
SERVER_CFG = cfg_section("SERVER")
CACHE_CFG = cfg_section("CACHE")
TIMEOUTS_CFG = cfg_section("TIMEOUTS")
CARD_CFG = cfg_section("CARD_PROCESSING")

# Bakåtkompatibilitet med äldre config-nycklar
READER_DEVICE = READER_CFG.get("device") or config.get("READER_DEVICE") or "/dev/input/event0"
READER_NAME_CONTAINS = (READER_CFG.get("nameContains") or "").strip()
READER_GRAB = bool(READER_CFG.get("grab", True))
READER_BACKEND = str(READER_CFG.get("backend", "auto")).lower()
READER_USB_VENDOR = int(str(READER_CFG.get("usbVendor", "0xffff")), 0)
READER_USB_PRODUCT = int(str(READER_CFG.get("usbProduct", "0x0035")), 0)

SERVER_HOST = SERVER_CFG.get("host", "0.0.0.0")
SERVER_PORT = int(SERVER_CFG.get("port", 8081))

CACHE_UPDATE_INTERVAL = int(CACHE_CFG.get("updateIntervalSeconds", 1800))
CACHE_FETCH_TIMEOUT = int(CACHE_CFG.get("fetchTimeoutSeconds", 30))
CACHE_USER_AGENT = CACHE_CFG.get("userAgent", "Mifare Reader Backend")

REST_TIMEOUT_SECONDS = int(TIMEOUTS_CFG.get("statusDisplaySeconds", 3))
LOG_REQUEST_TIMEOUT = int(TIMEOUTS_CFG.get("logRequestSeconds", 5))
CLIP_REQUEST_TIMEOUT = int(TIMEOUTS_CFG.get("clipRequestSeconds", 10))
SSE_HEARTBEAT_SECONDS = int(TIMEOUTS_CFG.get("sseHeartbeatSeconds", 20))
# Sista klipp (1→0): fas 1 "Klipp OK!" sedan fas 2 lämna-in-meddelande
LAST_CLIP_OK_SECONDS = int(TIMEOUTS_CFG.get("lastClipOkSeconds", 3))
LAST_CLIP_RETURN_SECONDS = int(TIMEOUTS_CFG.get("lastClipReturnSeconds", 5))

CARD_FORMAT = str(CARD_CFG.get("FORMAT", "DEC10")).upper()
BYTE_ORDER = str(CARD_CFG.get("BYTE_ORDER", "NORMAL")).upper()
# Vissa USB-läsare (t.ex. SDZNKJLTD) skickar hex med omvänd nibble-ordning per byte.
NIBBLE_ORDER = str(CARD_CFG.get("NIBBLE_ORDER", "NORMAL")).upper()
# Antal hex-tecken i själva UID (4-byte MIFARE = 8). Läsaren kan padda med "00" framför.
HEX_UID_CHARS = int(CARD_CFG.get("hexUidChars", 8))
MIN_CARD_ID_LENGTH = int(CARD_CFG.get("minIdLength", 5))
MAX_CARD_ID_LENGTH = int(CARD_CFG.get("maxIdLength", 10))
DECIMAL_PAD_LENGTH = int(CARD_CFG.get("decimalPadLength", 10))

TENCARD_DATA_URL = config.get("TEN_VISIT_DATA_URL")
TENCARD_CLIP_URL = config.get("GAS_UPDATE_URL_BASE")

app = Flask(__name__)


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
    """Välj kortläsare via path och/eller namnmatchning från config."""
    if READER_NAME_CONTAINS:
        needle = READER_NAME_CONTAINS.lower()
        matches = [
            d for d in list_input_devices_info()
            if d.get("name") and needle in d["name"].lower()
        ]
        if len(matches) == 1:
            return matches[0]["path"]
        if len(matches) > 1:
            paths = ", ".join(d["path"] for d in matches)
            print(
                f"VARNING: nameContains '{READER_NAME_CONTAINS}' matchade flera enheter "
                f"({paths}). Använder device-path om den finns."
            )
        elif not READER_DEVICE:
            print(
                f"KRITISKT FEL: Ingen input-enhet matchade nameContains "
                f"'{READER_NAME_CONTAINS}'."
            )
            return None

    return READER_DEVICE or None


def _resolve_reader_backend():
    """auto → usb för kända xHCI-kraschande läsare, annars evdev."""
    if READER_BACKEND in {"usb", "pyusb"}:
        return "usb"
    if READER_BACKEND in {"evdev", "input"}:
        return "evdev"
    # auto
    if READER_USB_VENDOR == 0xFFFF and READER_USB_PRODUCT == 0x0035:
        return "usb"
    if READER_CFG.get("usbVendor") or READER_CFG.get("usbProduct"):
        return "usb"
    return "evdev"


def _deferred_usb_reader_start():
    """Vänta kort så /healthz kan svara innan libusb rör USB-bussen."""
    time.sleep(2.0)
    if not SHOULD_RUN:
        return
    try:
        usb_card_reader_thread_entry()
    except Exception as exc:
        print(f"USB-kortläsartråd dog: {exc}")


def start_background_threads():
    """Startar cache- och kortläsartrådar exakt en gång per process."""
    global _THREADS_STARTED
    with _THREADS_START_LOCK:
        if _THREADS_STARTED:
            return
        _THREADS_STARTED = True
        threading.Thread(target=cache_updater_thread, daemon=True).start()
        backend = _resolve_reader_backend()
        if backend == "usb":
            threading.Thread(target=_deferred_usb_reader_start, daemon=True).start()
            print("Bakgrundstrådar startade (cache + USB/pyusb-kortläsare, deferred).")
        else:
            threading.Thread(target=card_reader_thread, daemon=True).start()
            print("Bakgrundstrådar startade (cache + evdev-kortläsare).")

# --- KORTKONVERTERINGSFUNKTION ---
def convert_card_id(raw_card_id: str) -> str:
    """Konvertera rått kort-ID enligt CARD_PROCESSING i config."""
    return convert_card_id_with_options(
        raw_card_id,
        card_format=CARD_FORMAT,
        byte_order=BYTE_ORDER,
        nibble_order=NIBBLE_ORDER,
        hex_uid_chars=HEX_UID_CHARS,
        decimal_pad_length=DECIMAL_PAD_LENGTH,
    )

# --- LOGGNING (SEPARAT TRÅD) ---
def log_card_read_task(card_id, log_url):
    """Körs i bakgrunden för att skicka loggdata till det separata loggarket."""
    if not isinstance(card_id, str) or not card_id:
        print(f"[BAKGRUND] FEL: Ogiltigt eller tomt kort-ID för loggning: {card_id}")
        return

    try:
        response = requests.post(log_url, data={'card_id': card_id}, timeout=LOG_REQUEST_TIMEOUT)
        
        if response.status_code == 200:
            try:
                response_json = response.json()
                if response_json.get("status") == "success":
                    print(f"[BAKGRUND] Loggning av kort {card_id} lyckades.")
                else:
                    print(f"[BAKGRUND] Loggning misslyckades. Svar: {response.text[:100]}")
            except json.JSONDecodeError:
                print(f"[BAKGRUND] Loggning lyckades men icke-JSON svar. Status: {response.text[:50]}")
            
        else:
            print(f"[BAKGRUND] Loggning misslyckades. HTTP-status: {response.status_code}. Svar: {response.text[:100]}")
            
    except requests.exceptions.RequestException as e:
        print(f"[BAKGRUND] FEL vid loggningsanrop: {e}")

def start_background_logging(card_id):
    """Startar loggningen i en ny, icke-blockerande tråd."""
    log_url = config.get("LOG_URL")
    if not log_url:
        print("FEL: LOG_URL saknas i konfigurationen.")
        return
    logging_thread = threading.Thread(
        target=log_card_read_task,
        args=(str(card_id), log_url),
        daemon=True
    )
    logging_thread.start()
    print(f"Loggning för kort {card_id} startad i bakgrunden.")


# --- 10-KORT KLIPPLOGIK ---
def start_background_clip(card_id, callback):
    """
    Startar ett klipp (API-anrop) i en ny tråd.
    Anropar en callback-funktion med resultatet.
    """
    if not TENCARD_CLIP_URL:
        print("FEL: TENCARD_CLIP_URL (GAS_UPDATE_URL_BASE) saknas. Kan inte klippa.")
        callback("error", "Konfigurationsfel", "TENCARD_CLIP_URL saknas.")
        return

    def clip_task():
        try:
            response = requests.post(
                TENCARD_CLIP_URL,
                data={'card_id': card_id},
                timeout=CLIP_REQUEST_TIMEOUT,
            )
            
            if response.status_code == 200:
                try:
                    response_json = response.json()
                    # Förväntat svar: {"status": "success", "klipp_kvar": 9} eller {"status": "fail", "reason": "slut"}
                    callback("success", response_json.get("status"), response_json)
                except json.JSONDecodeError:
                    print(f"[BAKGRUND] Klipp-API svarade icke-JSON: {response.text[:50]}")
                    callback("error", "API-fel", f"Ogiltigt API-svar: {response.status_code}")
            else:
                print(f"[BAKGRUND] Klipp-API HTTP-fel: {response.status_code}. Svar: {response.text[:100]}")
                callback("error", "API-fel", f"HTTP-fel: {response.status_code}")
            
        except requests.exceptions.RequestException as e:
            print(f"[BAKGRUND] FEL vid klipp-anrop: {e}")
            callback("error", "Nätverksfel", str(e))

    threading.Thread(target=clip_task, daemon=True).start()
    print(f"Klipp-process för kort {card_id} startad i bakgrunden.")


def _schedule_last_clip_return_message(card_id: str) -> None:
    """Efter sista klippet: visa 'Klipp OK!' först, sedan lämna-in-meddelande."""

    def _phase_two():
        global current_card_status, LAST_READ_TIME
        time.sleep(max(0, LAST_CLIP_OK_SECONDS))
        with STATUS_LOCK:
            if not current_card_status:
                return
            if current_card_status.get("card_number_dec") != card_id:
                return
            if current_card_status.get("status") != "TENCARD_CLIPPED_LAST":
                return
            current_card_status["status"] = "TENCARD_CLIPPED_LAST_RETURN"
            current_card_status["message"] = "Lämna in kortet i reception"
            current_card_status["secondary_message"] = ""
            current_card_status["status_color"] = "orange"
            current_card_status["color_code"] = "#FF9800"
            current_card_status["status_expires_at"] = time.time() + LAST_CLIP_RETURN_SECONDS
            LAST_READ_TIME = time.time()
        sse_queue.put("read_complete")
        print(f"[KLIPP] Sista klipp fas 2 för {card_id}: lämna in kortet.")

    threading.Thread(target=_phase_two, daemon=True).start()


def handle_ten_card_clip_callback(thread_type, api_status, api_data):
    global current_card_status, LAST_READ_TIME, TENCARD_CACHE
    global IS_CLIPPING_ACTIVE

    schedule_last_clip_phase = False
    with STATUS_LOCK:
        if current_card_status is None:
            print(
                "[KLIPP] KRITISKT FEL: current_card_status var None i callback. "
                "Kortet klipptes (troligen), men GUI-status missades."
            )
            IS_CLIPPING_ACTIVE = False
            return

        card_id = current_card_status.get("card_number_dec", "Okänt ID")

        if thread_type == "success":
            clip_status = api_data.get("status", "fail")

            if clip_status == "success":
                try:
                    klipp_kvar_server = int(api_data.get("klipp_kvar") or 0)
                except (TypeError, ValueError):
                    klipp_kvar_server = api_data.get("klipp_kvar")
                print(f"[KLIPP] Klipp OK för kort {card_id}. {klipp_kvar_server} klipp kvar.")

                if card_id in TENCARD_CACHE:
                    TENCARD_CACHE[card_id]["Antal kvarvarande besök"] = klipp_kvar_server

                member_name = str(current_card_status.get("member_name") or "").strip()
                if klipp_kvar_server == 0:
                    # Fas 1: Klipp OK (orange). Fas 2 schemaläggs separat.
                    current_card_status["status"] = "TENCARD_CLIPPED_LAST"
                    current_card_status["message"] = "Klipp OK!"
                    current_card_status["secondary_message"] = ""
                    current_card_status["status_color"] = "orange"
                    current_card_status["color_code"] = "#FF9800"
                    current_card_status["status_expires_at"] = (
                        time.time() + LAST_CLIP_OK_SECONDS + LAST_CLIP_RETURN_SECONDS
                    )
                    schedule_last_clip_phase = True
                else:
                    current_card_status["status"] = "TENCARD_CLIPPED_OK"
                    current_card_status["message"] = f"Klipp OK! {klipp_kvar_server} klipp kvar."
                    current_card_status["secondary_message"] = member_name
                    current_card_status["status_color"] = "green"
                    current_card_status["color_code"] = "#4CAF50"
                    current_card_status.pop("status_expires_at", None)

            elif clip_status == "fail" and api_data.get("reason") == "slut":
                print(f"[KLIPP] Klipp misslyckades: Slut på klipp för kort {card_id}.")
                current_card_status["status"] = "TENCARD_CLIP_FAIL_EXHAUSTED"
                current_card_status["message"] = "Klipp misslyckades: 0 klipp kvar!"
                current_card_status["secondary_message"] = "Vänligen lämna in kortet i receptionen"
                current_card_status["status_color"] = "red"
                current_card_status["color_code"] = "#F44336"
                current_card_status.pop("status_expires_at", None)

            else:
                print(f"[KLIPP] Klipp-API svarade fail/okänd anledning: {api_data}")
                current_card_status["status"] = "TENCARD_CLIP_FAIL_UNKNOWN"
                current_card_status["message"] = "Klipp misslyckades (okänt fel i API)."
                current_card_status["secondary_message"] = f"Status: {api_status}"
                current_card_status["status_color"] = "orange"
                current_card_status["color_code"] = "#FF9800"
                current_card_status.pop("status_expires_at", None)

        else:
            print(f"[KLIPP] KRITISKT FEL vid klipp: {api_data}")
            current_card_status["status"] = "TENCARD_CLIP_ERROR"
            current_card_status["message"] = "KRITISKT FEL: Kunde inte klippa kortet."
            current_card_status["secondary_message"] = (
                "Klippning kan ha fullföljts på servern. Kontrollera saldo i kassan!"
            )
            current_card_status["status_color"] = "red"
            current_card_status["color_code"] = "#D32F2F"
            current_card_status.pop("status_expires_at", None)

        LAST_READ_TIME = time.time()
        IS_CLIPPING_ACTIVE = False

    sse_queue.put("read_complete")
    print("[KLIPP] IS_CLIPPING_ACTIVE satt till False. Timeout startar nu.")
    if schedule_last_clip_phase:
        _schedule_last_clip_return_message(str(card_id))


# --- CACHING FUNKTIONER (Oändrade) ---
def fetch_latest_card_data(data_url):
    print(f"CACHE: Försöker hämta ny data från {data_url}...")
    
    headers = {
        'User-Agent': CACHE_USER_AGENT,
        'Accept': 'application/json',
    }

    try:
        response = requests.get(data_url, headers=headers, timeout=CACHE_FETCH_TIMEOUT)
        
        if response.status_code == 200:
            
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                print(f"CACHE KRITISKT FEL: Kunde inte avkoda JSON-svaret. Fel: {e}")
                return None
            
            if isinstance(data, list) or isinstance(data, dict):
                print(f"CACHE: Hämtade {len(data)} objekt. Uppdatering lyckades.")
                return data
            else:
                print(f"CACHE FEL: Svaret var en {type(data)} men förväntade sig JSON.")
                return None
            
        else:
            print(f"CACHE FEL: HTTP-fel vid hämtning: {response.status_code}.")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"CACHE FEL: Nätverksfel: {e}")
        return None

def normalize_card_number(value) -> str:
    """Normalisera Kortnummer från GAS/Sheets (int/float/str) till ren siffersträng."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value).strip()
    text = str(value).strip().replace(" ", "")
    if not text:
        return ""
    # Sheets/JSON kan ge "1443137877.0"
    try:
        as_float = float(text)
        if as_float.is_integer():
            return str(int(as_float))
    except ValueError:
        pass
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def search_local_cache(card_id, card_cache, tencard_cache):
    """Söker i den lokala cachelistan (medlemskort) OCH 10-kortscachen."""
    
    card_id_str = normalize_card_number(card_id)
    if not card_id_str:
        return None
    
    # 1. Sök i 10-kortscachen (prioritet 1)
    ten_card = tencard_cache.get(card_id_str)
    if ten_card:
        klipp_kvar = int(ten_card.get("Antal kvarvarande besök") or 0)
        member_name = str(ten_card.get("Namn") or "").strip()
        
        if klipp_kvar > 0:
            translated_status = 'TENCARD_READY'
            color = 'purple'
            code = '#9C27B0'
            main_message = f"10-kort OK: {klipp_kvar} klipp kvar."
            secondary_status_text = f"Välkommen {member_name}!" if member_name else ""
        else:
            translated_status = 'TENCARD_EXHAUSTED'
            color = 'red'
            code = '#F44336'
            main_message = f"10-kort slut (0 klipp kvar)."
            secondary_status_text = "Vänligen lämna in kortet i receptionen"
            
        return {
            "type": "TENCARD",
            "status": translated_status,
            "message": main_message,
            "secondary_message": secondary_status_text,
            "status_color": color,
            "color_code": code,
            "card_number_dec": card_id_str,
            "member_name": member_name,
            "klipp_kvar_local": klipp_kvar
        }
        
    # 2. Sök i vanliga medlemskortscachen (prioritet 2)
    for card in card_cache:
        if normalize_card_number(card.get("Kortnummer")) == card_id_str:
            
            raw_status = card.get("Status", "Okänd Status").upper()
            member_name = card.get("Namn", "Okänt namn")
            
            # Mappa statusar
            if 'AKTIVT' in raw_status:
                translated_status = 'ACTIVE'
                color = 'green'
                code = '#4CAF50'
            elif 'GÅR SNART UT' in raw_status:
                translated_status = 'EXPIRING_SOON'
                color = 'yellow'
                code = '#FFC107'
            elif 'INAKTIVT' in raw_status or 'UTGÅNGET' in raw_status:
                translated_status = 'EXPIRED'
                color = 'red'
                code = '#F44336'
            else:
                translated_status = 'EXPIRED'
                color = 'gray'
                code = '#9E9E9E'
            
            main_message = f"Välkommen {member_name}!"
            secondary_status_text = f"Kortstatus: {raw_status.title()}"
            
            return {
                "type": "MEMBER",
                "status": translated_status,
                "message": main_message,
                "secondary_message": secondary_status_text,
                "status_color": color,
                "color_code": code,
                "card_number_dec": card_id_str,
                "member_name": member_name,
                "expiry_date": card.get("Giltigt till och med", "Saknas")
            }
            
    return None

def cache_updater_thread():
    global CARD_CACHE, TENCARD_CACHE, CACHE_LAST_UPDATE, CACHE_BOOTSTRAP_DONE, SHOULD_RUN

    print("CACHE UPDATER: Försöker initiera cache vid start...")
    
    # 1. Hämta vanlig medlemsdata
    initial_cache = fetch_latest_card_data(config.get("DATA_URL"))
    if initial_cache and isinstance(initial_cache, list):
        CARD_CACHE = initial_cache
        print(f"CACHE UPDATER: Laddade {len(CARD_CACHE)} medlemskort.")
    else:
        print("CACHE UPDATER: Varning: Kunde inte ladda medlemskort. Fortsätter i offline-läge.")

    # 2. Hämta 10-kortsdata
    if TENCARD_DATA_URL:
        ten_card_list = fetch_latest_card_data(TENCARD_DATA_URL)
        if ten_card_list and isinstance(ten_card_list, list):
            # Konvertera listan till en dictionary för snabbare uppslagning
            TENCARD_CACHE = _index_tencards(ten_card_list)
            print(f"CACHE UPDATER: Laddade {len(TENCARD_CACHE)} 10-kort.")
        else:
            print("CACHE UPDATER: Varning: Kunde inte ladda 10-kort. Fortsätter i offline-läge.")
    else:
        print("CACHE UPDATER: Varning: TENCARD_DATA_URL saknas. 10-kort inaktiverade.")
        
    CACHE_LAST_UPDATE = time.time()
    CACHE_BOOTSTRAP_DONE = True
    print("CACHE UPDATER: Bootstrap klar — kortuppslag tillåtna.")
    
    while SHOULD_RUN:
        time.sleep(min(5, CACHE_UPDATE_INTERVAL))
        if (time.time() - CACHE_LAST_UPDATE) < CACHE_UPDATE_INTERVAL:
            continue

        print("CACHE UPDATER: Tiden har löpt ut, startar bakgrundsuppdatering.")
        refresh_caches()


# --- KORTLÄSNING OCH HUVUDLOGIK ---

def parse_card_id(key_events):
    """Omvandlar en sekvens av event-objekt till en rå sträng av siffror/bokstäver."""
    card_id_str = ""
    for event in key_events:
        if event.code in CARD_KEY_CODES:
            card_id_str += CARD_KEY_CODES[event.code]
            
    return card_id_str

def _index_tencards(ten_card_list):
    indexed = {}
    for card in ten_card_list or []:
        key = normalize_card_number(card.get("Kortnummer"))
        if key:
            indexed[key] = card
    return indexed


def refresh_caches() -> dict:
    """Hämta medlems- och 10-kortscache från GAS på nytt."""
    global CARD_CACHE, TENCARD_CACHE, CACHE_LAST_UPDATE

    result = {
        "members_ok": False,
        "tencards_ok": False,
        "members_cached": len(CARD_CACHE),
        "tencards_cached": len(TENCARD_CACHE),
    }

    new_member_cache = fetch_latest_card_data(config.get("DATA_URL"))
    if new_member_cache and isinstance(new_member_cache, list):
        CARD_CACHE = new_member_cache
        result["members_ok"] = True
        print(f"CACHE: Uppdaterade {len(CARD_CACHE)} medlemskort.")
    else:
        print("CACHE: Misslyckades uppdatera medlemskort. Behåller gammal data.")

    if TENCARD_DATA_URL:
        new_ten_card_list = fetch_latest_card_data(TENCARD_DATA_URL)
        if new_ten_card_list and isinstance(new_ten_card_list, list):
            TENCARD_CACHE = _index_tencards(new_ten_card_list)
            result["tencards_ok"] = True
            print(f"CACHE: Uppdaterade {len(TENCARD_CACHE)} 10-kort.")
        else:
            print("CACHE: Misslyckades uppdatera 10-kort. Behåller gammal data.")

    CACHE_LAST_UPDATE = time.time()
    result["members_cached"] = len(CARD_CACHE)
    result["tencards_cached"] = len(TENCARD_CACHE)
    result["cache_age_seconds"] = 0
    return result


def handle_card_read(card_id):
    """Huvudfunktion som hanterar sökning och validering med LOKAL CACHE."""
    global current_card_status, LAST_READ_TIME, CARD_CACHE, TENCARD_CACHE
    global IS_CLIPPING_ACTIVE

    card_id_str = normalize_card_number(card_id)

    # 1. Sök i den lokala cachen (medlemskort eller 10-kort)
    status_data = search_local_cache(card_id_str, CARD_CACHE, TENCARD_CACHE)

    # 2. Status om kortet INTE hittades
    if not status_data:
        if not CACHE_BOOTSTRAP_DONE:
            print(
                f"KORT FÖRE CACHE: {card_id_str!r} — bootstrap pågår "
                f"(medlemmar={len(CARD_CACHE)}, 10-kort={len(TENCARD_CACHE)})"
            )
            status_data = {
                "type": "UNKNOWN",
                "status": "CACHE_LOADING",
                "message": (
                    "Vänligen vänta, systemet väntar på att ta hem kortinformation"
                ),
                "secondary_message": "",
                "status_color": "blue",
                "color_code": "#2196F3",
                "card_number_dec": card_id_str,
                "member_name": "",
                "expiry_date": "",
            }
        else:
            msg = "Kortet hittades inte i systemet."
            print(
                f"KORT EJ HITTAT: {card_id_str!r} "
                f"(medlemmar={len(CARD_CACHE)}, 10-kort={len(TENCARD_CACHE)})"
            )

            status_data = {
                "type": "UNKNOWN",
                "status": "NOT_FOUND",
                "message": msg,
                "secondary_message": "Vänligen kontakta personal för registrering.",
                "status_color": "red",
                "color_code": "#F44336",
                "card_number_dec": card_id_str,
                "member_name": "Okänd/Ej registrerad",
                "expiry_date": "",
            }

    # 3. Hantera 10-kort (KRITISK ÄNDRING HÄR)
    elif status_data.get("type") == "TENCARD":
        
        if status_data.get("status") == "TENCARD_READY":
            # Sätt låset först så timeout inte rensar status under klippning.
            IS_CLIPPING_ACTIVE = True
            print("[KLIPP] IS_CLIPPING_ACTIVE satt till True (Början av klipp).")

            with STATUS_LOCK:
                current_card_status = status_data.copy()
                current_card_status["message"] = (
                    f"Behandlar klipp ({current_card_status['klipp_kvar_local']} kvar)..."
                )
                current_card_status["status_color"] = "blue"
                current_card_status["color_code"] = "#2196F3"

            # Timeout/SSE startar först när slutstatus finns (i callback).
            return start_background_clip(card_id_str, handle_ten_card_clip_callback)
            
        # Om kortet hittades men är slut (TENCARD_EXHAUSTED), faller den igenom till steg 5 (visning)
        
    # 4. Hantera vanliga medlemskort
    elif status_data.get("type") == "MEMBER":
        
        # Om statusen är godkänd (ACTIVE eller EXPIRING_SOON), starta loggning
        if status_data.get("status") in ["ACTIVE", "EXPIRING_SOON"]:
            start_background_logging(card_id_str)
        
    # 5. Uppdatera gränssnittet (gäller icke-klipp-kort eller fel)
    with STATUS_LOCK:
        current_card_status = status_data
        LAST_READ_TIME = time.time()
    sse_queue.put("read_complete")

    print(
        f"Gränssnittet uppdateras till status: "
        f"{status_data.get('message', 'Okänd status')}. ID: {card_id_str}"
    )


def process_raw_card_id(raw_id: str) -> None:
    """Gemensam hantering av rått kort-ID från evdev eller USB."""
    global current_card_status, LAST_READ_TIME

    print(
        f"KORT RÅDATA: {raw_id!r} (len={len(raw_id)}) "
        f"format={CARD_FORMAT}/{BYTE_ORDER}/nibble={NIBBLE_ORDER} "
        f"godkänd_längd={MIN_CARD_ID_LENGTH}-{MAX_CARD_ID_LENGTH}"
    )
    processed_id = convert_card_id(raw_id)
    processed_id_len = len(processed_id)
    print(f"KORT EFTER KONVERT: {processed_id!r} (len={processed_id_len})")
    is_valid_decimal = (
        processed_id.isdigit()
        and MIN_CARD_ID_LENGTH <= processed_id_len <= MAX_CARD_ID_LENGTH
    )

    if is_valid_decimal:
        threading.Thread(target=handle_card_read, args=(processed_id,), daemon=True).start()
        return

    if not processed_id.isdigit():
        msg = "Fel: Konvertering misslyckades (icke-numeriska tecken kvar)."
        secondary = (
            f"Rå: {raw_id!r} → {processed_id!r}. "
            f"Kontrollera {CARD_FORMAT}/{BYTE_ORDER}."
        )
    elif processed_id_len < MIN_CARD_ID_LENGTH or processed_id_len > MAX_CARD_ID_LENGTH:
        msg = f"Fel: Ogiltig längd ({processed_id_len} siffror)."
        secondary = (
            f"Rå: {raw_id!r} → {processed_id!r}. "
            f"Krävs {MIN_CARD_ID_LENGTH}-{MAX_CARD_ID_LENGTH} siffror "
            f"({CARD_FORMAT}/{BYTE_ORDER})."
        )
    else:
        msg = "Fel: Okänt ID-format efter bearbetning."
        secondary = f"Rådata: {raw_id!r} → {processed_id!r}. Konfig: {CARD_FORMAT}/{BYTE_ORDER}."

    print(f"VARNING: Kort-ID ogiltigt. ID: {processed_id}. Ursprung: {raw_id}. Ignoreras.")
    with STATUS_LOCK:
        current_card_status = {
            "status": "INVALID_FORMAT",
            "message": msg,
            "secondary_message": secondary,
            "status_color": "orange",
            "color_code": "#FF9800",
            "card_number_dec": processed_id,
            "member_name": "N/A",
            "expiry_date": "N/A",
        }
        LAST_READ_TIME = time.time()
    sse_queue.put("read_complete")


def usb_card_reader_thread_entry():
    """PyUSB-backend — undviker usbhid/iface1 som dödar xHCI."""
    global ACTIVE_READER_DEVICE
    from reader_usb import usb_card_reader_thread

    ACTIVE_READER_DEVICE = f"usb:{READER_USB_VENDOR:#06x}:{READER_USB_PRODUCT:#06x}"
    usb_card_reader_thread(
        vendor_id=READER_USB_VENDOR,
        product_id=READER_USB_PRODUCT,
        on_raw_id=process_raw_card_id,
        should_run=lambda: SHOULD_RUN,
    )


def card_reader_thread():
    """Huvudtråd som konstant lyssnar på MIFARE-läsaren via evdev."""
    global ACTIVE_READER_DEVICE

    device_path = resolve_reader_device()
    if not device_path:
        print(
            "KRITISKT FEL: Ingen kortläsare angiven. "
            "Sätt READER.device eller READER.nameContains i config.json."
        )
        print("Tips: python scripts/list_input_devices.py")
        return

    ACTIVE_READER_DEVICE = device_path
    dev = None

    try:
        dev = InputDevice(device_path)
        print(f"Kortläsartråd startad. Lyssnar på: {dev.name} ({device_path})")
        if READER_GRAB:
            dev.grab()

    except FileNotFoundError:
        print(f"KRITISKT FEL: Hittade inte enheten vid {device_path}.")
        print("Tips: python scripts/list_input_devices.py")
        return
    except PermissionError as e:
        print(f"KRITISKT FEL: Behörighetsfel vid öppning/grab av {device_path}. FEL: {e}")
        return
    except Exception as e:
        print(f"KRITISKT FEL: Ett oväntat fel uppstod vid initiering av InputDevice: {e}")
        return

    print("DEBUG LOOP: Går in i read_loop().")
    key_events = []

    try:
        for event in dev.read_loop():
            if event.type == ecodes.EV_KEY and event.value == 1:
                if event.code in CARD_KEY_CODES:
                    if not key_events:
                        sse_queue.put("start_read")
                    key_events.append(event)
                elif event.code in (ecodes.KEY_ENTER, ecodes.KEY_KPENTER):
                    if key_events:
                        raw_id = parse_card_id(key_events)
                        key_events = []
                        process_raw_card_id(raw_id)

    except Exception as e:
        print(f"KRITISKT FEL: Ett oväntat fel uppstod i lästråden: {e}")

    finally:
        if dev and READER_GRAB:
            try:
                dev.ungrab()
                print("DEBUG UNGRAB: Släppte exklusiv kontroll över enheten.")
            except Exception:
                pass
    return


# --- FLASK WEBSERVER ROUTES ---

@app.route('/stream')
def stream():
    def event_stream():
        while True:
            try:
                message = sse_queue.get(timeout=SSE_HEARTBEAT_SECONDS)
                if message == "start_read":
                    yield 'data: start\n\n'
                elif message == "read_complete":
                    yield 'data: complete\n\n'
            except queue.Empty:
                yield ':\n\n'
            except GeneratorExit:
                break
            except Exception as e:
                print(f"SSE FEL: {e}")
                break

    return app.response_class(event_stream(), mimetype='text/event-stream')


@app.route('/healthz')
def healthz():
    age = (time.time() - CACHE_LAST_UPDATE) if CACHE_LAST_UPDATE else None
    return jsonify({
        "ok": True,
        "reader_device": ACTIVE_READER_DEVICE,
        "cache_update_interval_seconds": CACHE_UPDATE_INTERVAL,
        "cache_age_seconds": int(age) if age is not None else None,
        "members_cached": len(CARD_CACHE),
        "tencards_cached": len(TENCARD_CACHE),
        "clipping": IS_CLIPPING_ACTIVE,
    })


@app.route('/api/cache/refresh', methods=['POST', 'GET'])
def api_cache_refresh():
    """Tvinga omhämtning av medlems-/10-kortscache från GAS."""
    result = refresh_caches()
    return jsonify({"ok": True, **result})


@app.route('/api/cache/lookup/<card_id>')
def api_cache_lookup(card_id):
    """Felsök om ett kort-ID finns i cachen (exakt samma matchning som läsaren)."""
    needle = normalize_card_number(card_id)
    hit = search_local_cache(needle, CARD_CACHE, TENCARD_CACHE)
    sample_members = [
        normalize_card_number(c.get("Kortnummer"))
        for c in CARD_CACHE[:5]
    ]
    return jsonify({
        "query": needle,
        "found": bool(hit),
        "result": hit,
        "members_cached": len(CARD_CACHE),
        "tencards_cached": len(TENCARD_CACHE),
        "sample_member_ids": sample_members,
    })


@app.route('/api/input-devices')
def api_input_devices():
    """Lista tangentbords-/input-enheter för att välja rätt READER.device."""
    return jsonify({
        "devices": list_input_devices_info(),
        "configured": {
            "device": READER_DEVICE,
            "nameContains": READER_NAME_CONTAINS,
            "active": ACTIVE_READER_DEVICE,
        },
    })


def normalize_kiosk_slides(raw_slides):
    """Normalisera slides från config (durationSeconds eller durationMs)."""
    slides = []
    for index, slide in enumerate(raw_slides or []):
        if not isinstance(slide, dict) or not slide.get("url"):
            continue
        duration_ms = slide.get("durationMs")
        if duration_ms is None and slide.get("durationSeconds") is not None:
            duration_ms = int(float(slide["durationSeconds"]) * 1000)
        if duration_ms is None:
            duration_ms = 30000
        slides.append({
            "id": slide.get("id") or f"slide-{index + 1}",
            "title": slide.get("title") or slide.get("id") or f"Slide {index + 1}",
            "url": slide["url"],
            "durationMs": max(1000, int(duration_ms)),
        })
    return slides


@app.route('/')
def kiosk():
    """Hela kioskskärmen: timer-styrd rotator + alltid synlig incheckning."""
    kiosk_cfg = config.get("KIOSK") or {}
    checkin_cfg = kiosk_cfg.get("checkin") if isinstance(kiosk_cfg.get("checkin"), dict) else {}

    # Bakåtkompatibilitet: checkinPath / saknad checkin-sektion
    checkin_enabled = bool(checkin_cfg.get("enabled", True))
    checkin_path = (
        checkin_cfg.get("path")
        or kiosk_cfg.get("checkinPath")
        or "/checkin"
    )
    checkin_height = int(checkin_cfg.get("heightPercent", 20))
    checkin_height = min(80, max(0, checkin_height))
    if not checkin_enabled:
        checkin_height = 0
    content_height = 100 - checkin_height

    return render_template(
        'kiosk.html',
        slides=normalize_kiosk_slides(kiosk_cfg.get("slides")),
        checkin_enabled=checkin_enabled,
        checkin_path=checkin_path,
        checkin_height=checkin_height,
        content_height=content_height,
        reload_on_show=bool(kiosk_cfg.get("reloadOnShow", True)),
    )


@app.route('/checkin')
def checkin():
    """Incheckningsytan (används fristående eller som iframe i kiosken)."""
    global current_card_status

    with STATUS_LOCK:
        if current_card_status and not IS_CLIPPING_ACTIVE:
            expires_at = current_card_status.get("status_expires_at")
            timed_out = (
                time.time() >= float(expires_at)
                if expires_at is not None
                else (time.time() - LAST_READ_TIME) >= REST_TIMEOUT_SECONDS
            )
            if timed_out:
                print("Gränssnitt: Status timeout uppnådd. Återgår till viloläge.")
                current_card_status = None
        status_snapshot = current_card_status

    return render_template(
        'checkin.html',
        status_data=status_snapshot,
        REST_TIMEOUT_SECONDS=REST_TIMEOUT_SECONDS,
    )


# --- START ---

if __name__ == '__main__':
    start_background_threads()
    try:
        app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False)
    except KeyboardInterrupt:
        print("\nApplikationen stängs av...")
    finally:
        SHOULD_RUN = False
