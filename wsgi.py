import threading
from app import app, cache_updater_thread, card_reader_thread, SHOULD_RUN
import sys

# --- STARTA BAKGRUNDSTRÅDARNA DIREKT VID IMPORT ---

print("GUNICORN START: Initierar bakgrundstrådar...")
sys.stdout.flush()

# Starta Cache Updater
updater_thread = threading.Thread(target=cache_updater_thread, daemon=True)
updater_thread.start()

# Starta Kortläsare
reader_thread = threading.Thread(target=card_reader_thread, daemon=True)
reader_thread.start()

# --- DENNA DEL IGNORERAS AV GUNICORN MEN KÖR NÄR DU KÖR python wsgi.py ---
if __name__ == '__main__':
    print("DEBUG: Kör som huvudskript (ej Gunicorn). Flask startar...")
    try:
        app.run(host='0.0.0.0', port=8081, debug=False)
    finally:
        SHOULD_RUN = False

