# VKC Kiosk

Lokal kiosk + MIFARE-incheckning för Västerviks klättercenter (Raspberry Pi).

## Vad den gör

- **`/`** – hel kioskskärm (roterande statistik + incheckning)
- **`/checkin`** – bara incheckningsytan
- **`/diagrams`** – roterande Google Charts (styrs i config)
- **`/stream`** – SSE för snabb UI-uppdatering vid kortblipp
- **`/healthz`** – hälsokoll
- **`/api/input-devices`** – lista tangentbord/input-enheter

## Config (`config.json`)

Allt som tidigare låg hårdkodat i koden styrs här.

### Kortläsare (tangentbordsingång)

```json
"READER": {
  "device": "/dev/input/event0",
  "nameContains": "",
  "grab": true
}
```

- **`device`** – exakt event-nod, t.ex. `/dev/input/event3`
- **`nameContains`** – valfritt: matcha på enhetsnamn (stabilare om `event*`-numret ändras vid omstart). Om den matchar exakt en enhet används den.
- **`grab`** – ta exklusiv kontroll så korttryck inte “läcker” till skrivbordet

Lista enheter på Pi:n:

```bash
./venv/bin/python scripts/list_input_devices.py
# eller
curl -s http://localhost:8081/api/input-devices | jq
```

### Cache

```json
"CACHE": {
  "updateIntervalSeconds": 1800,
  "fetchTimeoutSeconds": 30,
  "userAgent": "Mifare Reader Backend"
}
```

`1800` = 30 minuter. Sätt t.ex. `300` för uppdatering var 5:e minut.

### Timeouts / UI

```json
"TIMEOUTS": {
  "statusDisplaySeconds": 3,
  "logRequestSeconds": 5,
  "clipRequestSeconds": 10,
  "sseHeartbeatSeconds": 20
}
```

### Kortformat

```json
"CARD_PROCESSING": {
  "FORMAT": "HEX10",
  "BYTE_ORDER": "REVERSED",
  "minIdLength": 5,
  "maxIdLength": 10,
  "decimalPadLength": 10
}
```

### Server

```json
"SERVER": {
  "host": "0.0.0.0",
  "port": 8081
}
```

Om du byter port: uppdatera även `mifare-reader.service` (`-b 0.0.0.0:PORT`).

### Diagram + kioskslides

`DIAGRAM_ROTATOR` styr `/diagrams`.  
`KIOSK.slides` styr vilka ytor som roterar på huvudskärmen och hur länge.

## Struktur

```
app.py
wsgi.py
config.json
scripts/list_input_devices.py
templates/kiosk.html
templates/checkin.html
templates/diagram_rotator.html
static/                  # success.mp3 failure.mp3 warning.mp3
mifare-reader.service
```

## Installera / uppdatera på Pi

```bash
cd /home/vkc/mifare-reader
git pull
./venv/bin/pip install -r requirements.txt
# Justera config.json (READER.device, CACHE.updateIntervalSeconds, …)
sudo cp mifare-reader.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart mifare-reader
```

Chromium:

```bash
chromium-browser --kiosk --app=http://localhost:8081/
```

## Drift

```bash
sudo systemctl status mifare-reader
journalctl -u mifare-reader -f
curl -s http://localhost:8081/healthz
curl -s http://localhost:8081/api/input-devices
```
