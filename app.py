import json
import os
import threading
import time
import requests
from flask import Flask, render_template
from evdev import InputDevice, ecodes, categorize
import queue

# --- KONFIGURATION OCH GLOBALA VARIABLER ---

# Globalt tillstånd för webbgränssnittet
current_card_status = None
LAST_READ_TIME = 0
REST_TIMEOUT_SECONDS = 3 # Visningstid för status på skärmen (ändra vid behov)

### KORRIGERAD KOD: GLOBAL FLAGGA FÖR ATT SKYDDA PÅGÅENDE KLIPP ###
IS_CLIPPING_ACTIVE = False

# NY GLOBAL KÖ FÖR SSE-MEDDELANDEN
sse_queue = queue.Queue()

# *** KORT-ID LÄNGD BASERAT PÅ 4 BYTE (32-BIT) ***
MIN_CARD_ID_LENGTH = 5
MAX_CARD_ID_LENGTH = 10
HEX_ID_LENGTH = 10

# --- Caching variabler ---
CARD_CACHE = []
TENCARD_CACHE = {} # Dictionary för snabb uppslagning av 10-kort (Kortnummer: Data)
CACHE_LAST_UPDATE = 0
CACHE_EXPIRY_SECONDS = 3600
CACHE_UPDATE_INTERVAL = 1800 # Exempel: Ändra till 300 för 5 minuters uppdatering
SHOULD_RUN = True
# -------------------------

# Lista över alla tangentkoder för siffrorna 0-9 och A-F (för att stödja Hex-ID)
CARD_KEY_CODES = {
    ecodes.KEY_0: '0', ecodes.KEY_1: '1', ecodes.KEY_2: '2', ecodes.KEY_3: '3',
    ecodes.KEY_4: '4', ecodes.KEY_5: '5', ecodes.KEY_6: '6', ecodes.KEY_7: '7',
    ecodes.KEY_8: '8', ecodes.KEY_9: '9',
    
    # A-F Koder (vanliga tangentbordstangenter)
    ecodes.KEY_A: 'A', ecodes.KEY_B: 'B', ecodes.KEY_C: 'C',
    ecodes.KEY_D: 'D', ecodes.KEY_E: 'E', ecodes.KEY_F: 'F'
}

# Laddar config.json
def load_config():
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"FEL: Kunde inte ladda config.json. Kontrollera att filen finns och har korrekt JSON-syntax. Fel: {e}")
        return {}

config = load_config()

# LÄS IN KONFIGURATIONSVÄRDEN
CARD_FORMAT = config.get('CARD_PROCESSING', {}).get('FORMAT', 'DEC10').upper()
BYTE_ORDER = config.get('CARD_PROCESSING', {}).get('BYTE_ORDER', 'NORMAL').upper()
# 10-KORT URL:er (ANPASSADE TILL DINA NYCKELNAMN)
TENCARD_DATA_URL = config.get("TEN_VISIT_DATA_URL")
TENCARD_CLIP_URL = config.get("GAS_UPDATE_URL_BASE")
# --------------------------------

# FLASK Setup
app = Flask(__name__)

# --- KORTKONVERTERINGSFUNKTION ---
def convert_card_id(raw_card_id: str) -> str:
    """
    Konverterar kort-ID baserat på FORMAT och BYTE_ORDER inställningarna från config.
    """
    card_id = raw_card_id.strip().replace(":", "").replace("-", "").upper()

    if CARD_FORMAT == "DEC10":
        # Nollfyller ID:n som trunkerats av läsaren
        if card_id.isdigit() and len(card_id) < MAX_CARD_ID_LENGTH:
            if len(card_id) < 10:
                card_id = card_id.zfill(10)
        
        return card_id

    if CARD_FORMAT == "HEX10":
        
        hex_id = card_id
        
        # 1. Byteordning
        if BYTE_ORDER == "REVERSED":
            bytes_list = [hex_id[i:i+2] for i in range(0, len(hex_id), 2)]
            bytes_list.reverse()
            hex_id = "".join(bytes_list)

        # 2. Konvertera Hex till Decimal
        try:
            decimal_id = int(hex_id, 16)
            return str(decimal_id)

        except ValueError:
            print(f"FEL: Kort-ID '{raw_card_id}' kunde inte konverteras från HEX10. Kontrollera om inmatningen är ren hex.")
            return raw_card_id
        
    # Standard: Returnera rådata om formatet inte matchar konfigurerat
    return raw_card_id

# --- LOGGNING (SEPARAT TRÅD) ---
def log_card_read_task(card_id, log_url):
    """Körs i bakgrunden för att skicka loggdata till det separata loggarket."""
    LOG_REQUEST_TIMEOUT = 5
    
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
    CLIP_REQUEST_TIMEOUT = 10
    if not TENCARD_CLIP_URL:
        print("FEL: TENCARD_CLIP_URL (GAS_UPDATE_URL_BASE) saknas. Kan inte klippa.")
        callback("error", "Konfigurationsfel", "TENCARD_CLIP_URL saknas.")
        return

    def clip_task():
        try:
            response = requests.post(
                TENCARD_CLIP_URL,
                data={'card_id': card_id},
                timeout=CLIP_REQUEST_TIMEOUT
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


def handle_ten_card_clip_callback(thread_type, api_status, api_data):
    global current_card_status, LAST_READ_TIME, TENCARD_CACHE
    global IS_CLIPPING_ACTIVE

    # Felet uppstår här om current_card_status är None. Vi gör nu en säkerhetskoll.
    if current_card_status is None:
        print("[KLIPP] KRITISKT FEL: current_card_status var None i callback. Kortet klipptes (troligen), men GUI-status missades.")
        # Vi måste ändå släppa låset, men kan inte uppdatera GUI:et korrekt.
        IS_CLIPPING_ACTIVE = False
        return

    # Hantera resultatet från klipp-API:et
    card_id = current_card_status.get("card_number_dec", "Okänt ID")
    
    if thread_type == "success":
        clip_status = api_data.get("status", "fail")
        
        if clip_status == "success":
            klipp_kvar_server = api_data.get("klipp_kvar")
            print(f"[KLIPP] Klipp OK för kort {card_id}. {klipp_kvar_server} klipp kvar.")
            
            if card_id in TENCARD_CACHE:
                TENCARD_CACHE[card_id]["Antal kvarvarande besök"] = klipp_kvar_server
            
            # Uppdatera aktuellt statusobjekt (gränssnittet)
            current_card_status["status"] = "TENCARD_CLIPPED_OK"
            current_card_status["message"] = f"Klipp OK! {klipp_kvar_server} klipp kvar."
            current_card_status["secondary_message"] = current_card_status.get("member_name", "")
            current_card_status["status_color"] = "green"
            current_card_status["color_code"] = "#4CAF50"
        
        elif clip_status == "fail" and api_data.get("reason") == "slut":
            print(f"[KLIPP] Klipp misslyckades: Slut på klipp för kort {card_id}.")
            current_card_status["status"] = "TENCARD_CLIP_FAIL_EXHAUSTED"
            current_card_status["message"] = "Klipp misslyckades: 0 klipp kvar!"
            current_card_status["secondary_message"] = "Vänligen köp nytt kort."
            current_card_status["status_color"] = "red"
            current_card_status["color_code"] = "#F44336"
            
        else:
            print(f"[KLIPP] Klipp-API svarade fail/okänd anledning: {api_data}")
            current_card_status["status"] = "TENCARD_CLIP_FAIL_UNKNOWN"
            current_card_status["message"] = "Klipp misslyckades (okänt fel i API)."
            current_card_status["secondary_message"] = f"Status: {api_status}"
            current_card_status["status_color"] = "orange"
            current_card_status["color_code"] = "#FF9800"
        
    else: # Nätverksfel eller annat fel i tråden
        print(f"[KLIPP] KRITISKT FEL vid klipp: {api_data}")
        current_card_status["status"] = "TENCARD_CLIP_ERROR"
        current_card_status["message"] = "KRITISKT FEL: Kunde inte klippa kortet."
        current_card_status["secondary_message"] = "Klippning kan ha fullföljts på servern. Kontrollera saldo i kassan!"
        current_card_status["status_color"] = "red"
        current_card_status["color_code"] = "#D32F2F"
        
    
    # ----------------------------------------------------------------
    # --- KRITISK SYNKKRONISERING (Starta timern och släpp låset) ---
    # ----------------------------------------------------------------
    
    # 1. Starta timern (nu startar nedräkningen för den slutgiltiga statusen)
    LAST_READ_TIME = time.time()
    
    # 2. Skicka SSE-signal
    sse_queue.put("read_complete")
    
    # 3. Släpp låset (Gör att index() kan timeouta efter 3 sekunder)
    IS_CLIPPING_ACTIVE = False
    print("[KLIPP] IS_CLIPPING_ACTIVE satt till False. Timeout startar nu.")


# --- CACHING FUNKTIONER (Oändrade) ---
def fetch_latest_card_data(data_url):
    print(f"CACHE: Försöker hämta ny data från {data_url}...")
    
    headers = {
        'User-Agent': 'Mifare Reader Backend',
        'Accept': 'application/json'
    }
    
    try:
        response = requests.get(data_url, headers=headers, timeout=30)
        
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

def search_local_cache(card_id, card_cache, tencard_cache):
    """Söker i den lokala cachelistan (medlemskort) OCH 10-kortscachen."""
    
    card_id_str = str(card_id)
    
    # 1. Sök i 10-kortscachen (prioritet 1)
    ten_card = tencard_cache.get(card_id_str)
    if ten_card:
        klipp_kvar = int(ten_card.get("Antal kvarvarande besök") or 0)
        member_name = ten_card.get("Namn", "Klippkorts-användare")
        
        if klipp_kvar > 0:
            translated_status = 'TENCARD_READY'
            color = 'purple'
            code = '#9C27B0'
            main_message = f"10-kort OK: {klipp_kvar} klipp kvar."
            secondary_status_text = f"Välkommen {member_name}!"
        else:
            translated_status = 'TENCARD_EXHAUSTED'
            color = 'red'
            code = '#F44336'
            main_message = f"10-kort slut (0 klipp kvar)."
            secondary_status_text = f"Vänligen köp nytt kort, {member_name}."
            
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
        if str(card.get("Kortnummer")) == card_id_str:
            
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
    global CARD_CACHE, TENCARD_CACHE, CACHE_LAST_UPDATE, SHOULD_RUN

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
            TENCARD_CACHE = {str(card.get("Kortnummer")): card for card in ten_card_list if card.get("Kortnummer") is not None}
            print(f"CACHE UPDATER: Laddade {len(TENCARD_CACHE)} 10-kort.")
        else:
            print("CACHE UPDATER: Varning: Kunde inte ladda 10-kort. Fortsätter i offline-läge.")
    else:
        print("CACHE UPDATER: Varning: TENCARD_DATA_URL saknas. 10-kort inaktiverade.")
        
    CACHE_LAST_UPDATE = time.time()
    
    while SHOULD_RUN:
        time.sleep(CACHE_UPDATE_INTERVAL)
        
        if (time.time() - CACHE_LAST_UPDATE) >= CACHE_UPDATE_INTERVAL:
            print("CACHE UPDATER: Tiden har löpt ut, startar bakgrundsuppdatering.")
            
            # Uppdatera vanliga kort
            new_member_cache = fetch_latest_card_data(config.get("DATA_URL"))
            if new_member_cache and isinstance(new_member_cache, list):
                CARD_CACHE = new_member_cache
                print("CACHE UPDATER: Uppdatering av medlemskort lyckades.")
            else:
                print("CACHE UPDATER: Misslyckades uppdatera medlemskort. Behåller gammal data.")
            
            # Uppdatera 10-kort
            if TENCARD_DATA_URL:
                new_ten_card_list = fetch_latest_card_data(TENCARD_DATA_URL)
                if new_ten_card_list and isinstance(new_ten_card_list, list):
                    TENCARD_CACHE = {str(card.get("Kortnummer")): card for card in new_ten_card_list if card.get("Kortnummer") is not None}
                    print("CACHE UPDATER: Uppdatering av 10-kort lyckades.")
                else:
                    print("CACHE UPDATER: Misslyckades uppdatera 10-kort. Behåller gammal data.")

            CACHE_LAST_UPDATE = time.time()


# --- KORTLÄSNING OCH HUVUDLOGIK ---

def parse_card_id(key_events):
    """Omvandlar en sekvens av event-objekt till en rå sträng av siffror/bokstäver."""
    card_id_str = ""
    for event in key_events:
        if event.code in CARD_KEY_CODES:
            card_id_str += CARD_KEY_CODES[event.code]
            
    return card_id_str

def handle_card_read(card_id):
    """Huvudfunktion som hanterar sökning och validering med LOKAL CACHE."""
    global current_card_status, LAST_READ_TIME, CARD_CACHE, TENCARD_CACHE
    global IS_CLIPPING_ACTIVE

    card_id_str = str(card_id)

    # 1. Sök i den lokala cachen (medlemskort eller 10-kort)
    status_data = search_local_cache(card_id_str, CARD_CACHE, TENCARD_CACHE)

    # 2. Status om kortet INTE hittades
    if not status_data:
        msg = "Kortet hittades inte i systemet."

        status_data = {
            "type": "UNKNOWN",
            "status": "NOT_FOUND",
            "message": msg,
            "secondary_message": "Vänligen kontakta personal för registrering.",
            "status_color": "red",
            "color_code": "#F44336",
            "card_number_dec": card_id_str,
            "member_name": "Okänd/Ej registrerad",
            "expiry_date": ""
        }
        
    # 3. Hantera 10-kort (KRITISK ÄNDRING HÄR)
    elif status_data.get("type") == "TENCARD":
        
        if status_data.get("status") == "TENCARD_READY":
            
            # 1. Sätt låset FÖRST: Hindrar index() från att rensa current_card_status under klippningen
            global IS_CLIPPING_ACTIVE
            IS_CLIPPING_ACTIVE = True
            print("[KLIPP] IS_CLIPPING_ACTIVE satt till True (Början av klipp).")
            
            # 2. Sätt preliminär status
            current_card_status = status_data.copy()
            current_card_status["message"] = f"Behandlar klipp ({current_card_status['klipp_kvar_local']} kvar)..."
            current_card_status["status_color"] = "blue"
            current_card_status["color_code"] = "#2196F3"
            
            # OBS! Vi UPPDATERAR INTE LAST_READ_TIME OCH SKICKAR INTE SSE-SIGNAL HÄR!
            # Detta säkerställer att timeout-timern inte startar förrän SLUTLIG status är känd.
            
            # Starta klipp-processen i bakgrunden. Resultatet hanteras i callback:en.
            return start_background_clip(card_id_str, handle_ten_card_clip_callback)
            
        # Om kortet hittades men är slut (TENCARD_EXHAUSTED), faller den igenom till steg 5 (visning)
        
    # 4. Hantera vanliga medlemskort
    elif status_data.get("type") == "MEMBER":
        
        # Om statusen är godkänd (ACTIVE eller EXPIRING_SOON), starta loggning
        if status_data.get("status") in ["ACTIVE", "EXPIRING_SOON"]:
            start_background_logging(card_id_str)
        
    # 5. Uppdatera gränssnittet (Gäller för alla icke-klipp-kort eller fel)
    current_card_status = status_data
    LAST_READ_TIME = time.time()
    # Tvinga fram en uppdatering av gränssnittet
    sse_queue.put("read_complete") 
    
    print(f"Gränssnittet uppdateras till status: {status_data.get('message', 'Okänd status')}. ID: {card_id_str}")


def card_reader_thread():
    """Huvudtråd som konstant lyssnar på MIFARE-läsaren via evdev."""
    global current_card_status, LAST_READ_TIME, sse_queue

    device_path = config.get("READER_DEVICE")
    if not device_path:
        print("KRITISKT FEL: READER_DEVICE saknas i config.json. Kan inte starta läsartråd.")
        return

    dev = None
    
    try:
        dev = InputDevice(device_path)
        print(f"Kortläsartråd startad. Lyssnar på: {dev.name} ({device_path})")
        dev.grab()
        
    except FileNotFoundError:
        print(f"KRITISKT FEL: Hittade inte enheten vid {device_path}.")
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
                
                event_code = event.code
                
                if event_code in CARD_KEY_CODES:
                    
                    # NY SSE LOGIK: Signalera till webben att läsningen har börjat
                    if not key_events:
                        sse_queue.put("start_read")

                    key_events.append(event)
                    
                elif event_code == ecodes.KEY_ENTER or event_code == ecodes.KEY_KPENTER:
                    if key_events:
                        
                        raw_id = parse_card_id(key_events)
                        key_events = []
                        
                        # 1. Konvertera/bearbeta rådata
                        processed_id = convert_card_id(raw_id)
                        
                        processed_id_len = len(processed_id)
                        
                        # 2. Huvudvalidering: Måste vara siffror OCH inom längdgränserna
                        is_valid_decimal = processed_id.isdigit() and MIN_CARD_ID_LENGTH <= processed_id_len <= MAX_CARD_ID_LENGTH
                        
                        if is_valid_decimal:
                            
                            # Starta valideringstråden
                            threading.Thread(target=handle_card_read, args=(processed_id,), daemon=True).start()
                            
                        else:
                            
                            # --- FELHANTERING ---
                            if not processed_id.isdigit():
                                msg = "Fel: Konvertering misslyckades (icke-numeriska tecken kvar)."
                                secondary = f"Kontrollera {CARD_FORMAT} inställning eller kortdata."
                            elif processed_id_len < MIN_CARD_ID_LENGTH or processed_id_len > MAX_CARD_ID_LENGTH:
                                msg = f"Fel: Ogiltig längd ({processed_id_len} siffror)."
                                secondary = f"Kortet ska ha {MIN_CARD_ID_LENGTH}-{MAX_CARD_ID_LENGTH} siffror."
                            else:
                                msg = "Fel: Okänt ID-format efter bearbetning."
                                secondary = f"Rådata: {raw_id}. Konfig: {CARD_FORMAT}/{BYTE_ORDER}."
                            
                            print(f"VARNING: Kort-ID ogiltigt. ID: {processed_id}. Ursprung: {raw_id}. Ignoreras.")

                            current_card_status = {
                                "status": "INVALID_FORMAT",
                                "message": msg,
                                "secondary_message": secondary,
                                "status_color": "orange",
                                "color_code": "#FF9800",
                                "card_number_dec": processed_id,
                                "member_name": "N/A",
                                "expiry_date": "N/A"
                            }
                            
                            # SSE LOGIK: Signalera till webben att läsningen är klar (även om den misslyckades)
                            LAST_READ_TIME = time.time()
                            sse_queue.put("read_complete")

                            
    except Exception as e:
        print(f"KRITISKT FEL: Ett oväntat fel uppstod i lästråden: {e}")

    finally:
        if dev:
            try:
                dev.ungrab()
                print("DEBUG UNGRAB: Släppte exklusiv kontroll över enheten.")
            except Exception:
                pass
    return


# --- FLASK WEBSERVER ROUTES ---

# NY SSE-RUTT
@app.route('/stream')
def stream():
    def event_stream():
        global sse_queue
        while True:
            # Väntar på att ett meddelande ska dyka upp i kön (blockerande)
            try:
                # 20s timeout som heartbeat
                message = sse_queue.get(timeout=20)
                
                # Skicka händelsen till klienten
                if message == "start_read":
                    yield 'data: start\n\n'
                elif message == "read_complete":
                    yield 'data: complete\n\n'
                
            except queue.Empty:
                # Skicka en kommentar för att hålla anslutningen vid liv
                yield ':\n\n'
            except GeneratorExit:
                break
            except Exception as e:
                print(f"SSE FEL: {e}")
                break

    # Konfigurera HTTP-huvuden för Server-Sent Events
    return app.response_class(event_stream(), mimetype='text/event-stream')


@app.route('/')
def index():
    """
    Huvudsidan för kortläsaren. Rendrerar index.html.
    Hantera återställning av statusen till viloläge (None) efter timeout.
    """
    global current_card_status, LAST_READ_TIME, REST_TIMEOUT_SECONDS
    global IS_CLIPPING_ACTIVE
    
    # KORRIGERING: Timeouta ENDAST om klippning INTE pågår OCH tiden har löpt ut
    if current_card_status and (time.time() - LAST_READ_TIME) >= REST_TIMEOUT_SECONDS and not IS_CLIPPING_ACTIVE:
        print("Gränssnitt: Status timeout uppnådd. Återgår till viloläge.")
        current_card_status = None
    
    return render_template('index.html',
        status_data=current_card_status,
        REST_TIMEOUT_SECONDS=REST_TIMEOUT_SECONDS)

@app.route('/statistik')
def statistik():
    """Rutt för statistik (förutsätter att templates/statistik.html finns)"""
    try:
        return render_template('statistik.html')
    except Exception as e:
        return f"FEL: Kunde inte hitta 'templates/statistik.html' eller fel vid rendering: {e}", 500
    
# --- START ---

if __name__ == '__main__':
    # Starta bakgrundstrådar
    updater_thread = threading.Thread(target=cache_updater_thread, daemon=True)
    updater_thread.start()
    
    reader_thread = threading.Thread(target=card_reader_thread, daemon=True)
    reader_thread.start()
    
    # Starta Flask-webbservern
    try:
        app.run(host='0.0.0.0', port=8081, debug=False)
    except KeyboardInterrupt:
        print("\nApplikationen stängs av...")
    finally:
        SHOULD_RUN = False
