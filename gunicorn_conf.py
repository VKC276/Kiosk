# gunicorn_conf.py

# Denna hook körs i varje workerprocess efter att den har forkat
# och före att den börjar hantera förfrågningar.
def post_worker_init(worker):
    import threading
    import sys

    # Importera trådstartfunktionerna från app.py
    from app import cache_updater_thread, card_reader_thread, log_to_journal

    log_to_journal("GUNICORN HOOK: Startar bakgrundstrådar i worker.")

    # Starta Cache Updater
    updater_thread = threading.Thread(target=cache_updater_thread, daemon=True)
    updater_thread.start()

    # Starta Kortläsare
    reader_thread = threading.Thread(target=card_reader_thread, daemon=True)
    reader_thread.start()








