# Installationsanvisningar — VKC Kiosk

Guide för att sätta upp kiosken på en Raspberry Pi med Pi OS.

## Förutsättningar

- Raspberry Pi med **Pi OS** (skrivbordsversion) — Pi 4/5 rekommenderas för full kiosk med Chromium
- Internetuppkoppling
- **Autologin** till skrivbordet (så Chromium startar vid boot)
- USB-kortläsare

Valfritt:
- [Raspberry Pi Connect](https://www.raspberrypi.com/documentation/services/connect.html) för fjärrstyrning (fungerar — skärmen är fullskärm, inte hårdlåst kiosk)

---

## 1. Installera

```bash
curl -fsSL https://raw.githubusercontent.com/VKC276/Kiosk/main/install.sh | sudo bash
```

Installern sätter upp:

- apt-paket (Python, Chromium, …)
- kod under `~/vkc-kiosk`
- Python-venv och beroenden
- behörighet till kortläsare (`input` / `plugdev`)
- systemd: `vkc-kiosk` (API) + `vkc-kiosk-browser` (Chromium)
- kommandot `vkc-kiosk`

### Alternativ: klona själv

```bash
git clone https://github.com/VKC276/Kiosk.git ~/vkc-kiosk
cd ~/vkc-kiosk
sudo ./install.sh
```

### Valfria miljövariabler

```bash
sudo KIOSK_USER=vkc KIOSK_DIR=/home/vkc/vkc-kiosk ./install.sh
sudo SKIP_BROWSER=1 ./install.sh    # bara API, ingen Chromium
sudo SKIP_APT=1 ./install.sh        # hoppa över apt (vid uppdatering)
```

---

## 2. Kortläsare

### A) YAROGNTEC / SDZNKJLTD (`ffff:0035`) — kräver systemfix

Den här läsaren kan krascha Pi:ns USB (`HC died`) om kernel-`usbhid` binder interface 1. Kör **alltid** detta script först:

```bash
sudo vkc-kiosk setup-reader
# samma sak:
# sudo ./scripts/setup-yarogntec-reader.sh
sudo reboot
```

Scriptet applicerar:

| Ändring | Syfte |
|--------|--------|
| `usbcore.authorized_default=0` i cmdline | Enheter startar unauthorized |
| `usbhid.quirks=0xffff:0x0035:0x4` | Extra ignore-skydd |
| udev + `prepare-sdznkj-reader.sh` | Authorize säkert, `driver_override`, undvik iface 1 |
| modprobe-quirk | Persistens över reboot |
| `pyusb` i venv | Appen läser iface 0 direkt |
| `config.json` → `READER.backend=usb` | PyUSB-backend |

**Övriga läsare** (vanlig HID keyboard-wedge) behöver **inte** `setup-reader`.

**USB-tangentbord** (t.ex. ActiveJet): blacklista **inte** `usbhid` — då dör tangentbordet. Setup-scriptet är skrivet för att behålla andra HID-enheter.

### B) Konfigurera läsare + kortformat (alla läsare)

Efter reboot (och för alla läsartyper):

```bash
vkc-kiosk configure-reader
# samma sak:
# ./venv/bin/python scripts/configure-card-reader.py
```

Assistenten:

1. Listar USB- och evdev-läsare  
2. Stoppar tillfälligt `vkc-kiosk` om den håller läsaren  
3. Låter dig blippa ett kort (eller klistra in rådata)  
4. Visar alla kombinationer av `FORMAT` / `BYTE_ORDER` / `NIBBLE_ORDER` / `hexUidChars`  
5. Sparar vald kombination + läsare till `config.json` (backup som `config.json.bak`)

Ange gärna det förväntade medlems-ID:t (t.ex. `1443137877`) så markeras matchande rader automatiskt.

### Manuell config (valfritt)

```bash
vkc-kiosk config
# eller: nano ~/vkc-kiosk/config.json
```

YAROGNTEC — typisk `CARD_PROCESSING` som ger t.ex. rå `00000055984065` → `1443137877`:

```json
"READER": {
  "backend": "usb",
  "usbVendor": "0xffff",
  "usbProduct": "0x0035",
  "nameContains": "USB Reader",
  "grab": true
},
"CARD_PROCESSING": {
  "FORMAT": "HEX10",
  "BYTE_ORDER": "REVERSED",
  "NIBBLE_ORDER": "REVERSED",
  "hexUidChars": 8,
  "minIdLength": 5,
  "maxIdLength": 10,
  "decimalPadLength": 10
}
```

`hexUidChars` är UID-längden i hex-tecken (4-byte MIFARE = 8). Ledande `00` från läsarpadding tas bort bara så länge strängen är längre än så — äkta nollor i UID (`00000001`) behålls.

---

## 3. Övrig config

### Google Apps Script-URL:er

I `config.json`:

| Nyckel | Innehåll |
|--------|----------|
| `DATA_URL` | Medlemslista (söks på `Kortnummer`) |
| `TEN_VISIT_DATA_URL` | 10-kort / klippkort |
| `LOG_URL` | Incheckningslogg |
| `GAS_UPDATE_URL_BASE` | Klippning av 10-kort |

Kiosken cachear listorna lokalt (standard ca 30 min). Efter att du lagt till ett kort i huvudsystemet:

```bash
curl -s http://127.0.0.1:8081/api/cache/refresh
curl -s http://127.0.0.1:8081/api/cache/lookup/1443137877
# eller: sudo systemctl restart vkc-kiosk
```

### Slides / karusell (övre skärmytan)

Enklast: `vkc-kiosk slides` (webbadress, ordning, visningstid, **refresh-intervall**).

```json
"KIOSK": {
  "checkin": { "enabled": true, "path": "/checkin", "heightPercent": 20 },
  "reloadOnShow": false,
  "reloadIntervalSeconds": 300,
  "slides": [
    {
      "id": "live-stats",
      "title": "Live",
      "url": "https://...",
      "durationSeconds": 30,
      "reloadIntervalSeconds": 120
    },
    {
      "id": "info",
      "title": "Info",
      "url": "https://...",
      "durationSeconds": 20,
      "reloadIntervalSeconds": 0
    }
  ]
}
```

| Fält | Betydelse |
|------|-----------|
| `durationSeconds` | Hur länge sidan visas i karusellen |
| `KIOSK.reloadIntervalSeconds` | Standard-refresh om slide saknar eget värde |
| `slides[].reloadIntervalSeconds` | Egen refresh för sidan (sekunder) |
| `…: 120` | Hämta om tidigast var 2:e minut när sidan visas |
| `…: 0` | Aldrig omhämtning (statiskt tills kiosk-omstart) |
| saknas | Använd global standard |
| `reloadOnShow: true` | Gammalt läge: ladda om vid varje bildbyte |

Incheckningen ligger kvar längst ner. Sidor byts automatiskt — ingen Space behövs.

---

## 4. Starta om

```bash
vkc-kiosk restart
```

Efter `setup-reader` eller första install: **reboot** så cmdline / grupper tar effekt:

```bash
sudo reboot
```

---

## 5. Kontrollera

```bash
vkc-kiosk status
curl -s http://127.0.0.1:8081/healthz
```

Förväntat:

- API svarar på porten i `config.json` (standard `8081`)
- Chromium i fullskärm med slides + incheckning
- Kortblipp ger status i den nedre ytan

Loggar:

```bash
vkc-kiosk logs
journalctl -u vkc-kiosk -f
```

Vid kortblipp ska du kunna se rader i stil med:

```text
KORT RÅDATA: '00000055984065' ...
KORT EFTER KONVERT: '1443137877' ...
```

---

## 6. Ljud (valfritt)

Lägg i `~/vkc-kiosk/static/`:

- `success.mp3`
- `failure.mp3`
- `warning.mp3`

---

## Daglig drift

| Kommando | Vad det gör |
|----------|-------------|
| `vkc-kiosk status` | Status + healthz |
| `vkc-kiosk restart` | Starta om API + browser |
| `vkc-kiosk devices` | Lista input-enheter |
| `vkc-kiosk setup-reader` | YAROGNTEC systemfix (kräver sudo + reboot) |
| `vkc-kiosk configure-reader` | Välj läsare + kortformat → `config.json` |
| `vkc-kiosk slides` | Hantera karusell (URL, ordning, visningstid) |
| `vkc-kiosk fix-wifi` | Spara WiFi som systemanslutning (utan nyckelring) |
| `vkc-kiosk update` | `git pull` + pip + ominstallation |
| `vkc-kiosk logs` | Följ journal-loggar |
| `vkc-kiosk config` | Öppna `config.json` |
| `vkc-kiosk url` | Visa lokal URL |

### API-hjälp

| URL | Syfte |
|-----|--------|
| `/healthz` | Hälsokoll + cachestorlek |
| `/api/cache/refresh` | Tvinga omhämtning från GAS |
| `/api/cache/lookup/<id>` | Finns kortet i cachen? |
| `/api/input-devices` | Lista evdev-enheter |

---

## Felsökning

**Kortläsaren reagerar inte**

1. `vkc-kiosk devices` / `configure-reader` — rätt läsare?
2. YAROGNTEC: har du kört `setup-reader` + reboot?
3. `groups` — ska innehålla `input` (evdev) / `plugdev` (usb)
4. `vkc-kiosk logs` — fel om saknad enhet / behörighet?
5. Stoppa API och testa: `sudo systemctl stop vkc-kiosk` sedan `configure-reader`

**Kortet har fel antal siffror / fel ID**

```bash
vkc-kiosk configure-reader
```

Ange det ID som står i medlemslistan och välj den kombination som matchar.

**Kortet hittas inte**

1. Finns rätt nummer i GAS-medlemslistan (`DATA_URL`)?
2. Uppdatera cache: `curl -s http://127.0.0.1:8081/api/cache/refresh`
3. Kontrollera: `curl -s http://127.0.0.1:8081/api/cache/lookup/<id>`

**Tom/vit skärm i Chromium**

1. `curl -s --max-time 3 http://127.0.0.1:8081/healthz`
2. `sudo systemctl restart vkc-kiosk vkc-kiosk-browser`
3. Grafisk session / autologin aktiv?

**Chromium öppnar nya flikar i loop**

```bash
sudo systemctl stop vkc-kiosk-browser
rm -f ~/.config/autostart/vkc-kiosk.desktop
pkill -f vkc-kiosk-chromium || true
cd ~/vkc-kiosk && git pull && sudo SKIP_APT=1 ./install.sh
```

**USB `HC died` / iface-1-fel (YAROGNTEC)**

```bash
sudo vkc-kiosk setup-reader
sudo reboot
```

Kontrollera efter reboot:

```bash
cat /proc/cmdline | tr ' ' '\n' | grep -E 'authorized_default|usbhid.quirks'
journalctl -t vkc-kiosk -n 20
```

**WiFi frågar lösenord / "visa lösenord" visar skräp**

Vanligt med autologin: lösenordet sparades i användarnyckelringen, som inte alltid låses upp. Spara som systemanslutning i stället:

```bash
sudo vkc-kiosk fix-wifi
```

Ange SSID + lösenord. Kontrollera att filen ligger under `/etc/NetworkManager/system-connections/`. Undvik att spara nätet via skrivbordsdialogen efteråt.

**Pi Connect**  
Chromium körs med `--start-fullscreen` (inte hård `--kiosk`). Lämna med F11 eller Alt+Tab.

**`git pull` blockeras av lokala ändringar**

Använd `vkc-kiosk pull` (stashar lokala filändringar, behåller `config.json`).
Manuellt:

```bash
cp -a config.json config.json.localbak
git stash push -u -m "pi local before pull"
git pull --ff-only
cp -a config.json.localbak config.json
```

---

## Avinstallera

```bash
cd ~/vkc-kiosk
sudo ./uninstall.sh
# sudo REMOVE_DIR=1 ./uninstall.sh   # tar även bort kodkatalogen
```
