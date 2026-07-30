# VKC Kiosk

Lokal kiosk + MIFARE-incheckning för Västerviks klättercenter (Raspberry Pi).

## Vad den gör

- **`/`** – hel kioskskärm (roterande statistik + incheckning)
- **`/checkin`** – bara incheckningsytan
- **`/stream`** – SSE för snabb UI-uppdatering vid kortblipp
- **`/healthz`** – enkel hälsokoll (cachestorlek m.m.)

Kortläsaren körs i bakgrunden via `evdev`, medlems- och 10-kort cacheas från Google Apps Script, och 10-kort klipps vid godkänd blipp.

## Struktur

```
app.py                 # Flask + kortlogik
wsgi.py                # Gunicorn-entry (startar bakgrundstrådar)
config.json            # Enhetsväg, GAS-URL:er, kiosk-slides
templates/kiosk.html   # Huvudskärm
templates/checkin.html # Incheckning
static/                # diagram_rotator.html + ljud (success/failure/warning.mp3)
mifare-reader.service  # systemd
```

## Config

`config.json` styr både kortläsning och kioskslides:

```json
"KIOSK": {
  "checkinPath": "/checkin",
  "slides": [
    { "id": "top-sends", "title": "...", "url": "https://...", "durationMs": 100000 },
    { "id": "charts", "title": "...", "url": "/static/diagram_rotator.html", "durationMs": 30000 }
  ]
}
```

Lägg till/ta bort slides där — ingen HTML-ändring behövs.

## Installera / uppdatera på Pi

```bash
cd /home/vkc/mifare-reader
git pull
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
# Lägg ljudfiler i static/ om de saknas: success.mp3 failure.mp3 warning.mp3
sudo cp mifare-reader.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mifare-reader.service
```

Öppna Chromium i kiosk-läge mot **en** URL:

```bash
chromium-browser --kiosk --app=http://localhost:8081/
```

Tidigare behövdes ofta separat statisk server för `Kiosk.html` + Flask på `:8081`. Nu räcker Flask.

## Utveckling lokalt (utan kortläsare)

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
# Sätt READER_DEVICE till en befintlig input eller låt tråden faila mjukt
./venv/bin/python wsgi.py
```

## Drift

```bash
sudo systemctl status mifare-reader
journalctl -u mifare-reader -f
curl -s http://localhost:8081/healthz
```
