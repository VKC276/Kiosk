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

## Verktyg — `vkc-kiosk`

Kommandot installeras som `/usr/local/bin/vkc-kiosk` och pekar på `scripts/vkc-kiosk.sh`.  
Visa inbyggd hjälp: `vkc-kiosk` / `vkc-kiosk help`.

### Översikt

| Kommando | sudo? | Vad det gör |
|----------|-------|-------------|
| `status` | nej | Status för `vkc-kiosk` + `vkc-kiosk-browser` och `GET /healthz` |
| `start` | ja | Starta API-tjänsten |
| `stop` | ja | Stoppa browser + API |
| `restart` | ja | Starta om API (+ browser om den finns) och visa status |
| `logs` | ja | `journalctl -f` för API och browser |
| `devices` | nej | Lista kortläsare (evdev/USB) + `/api/input-devices` |
| `pull` | nej | `git pull`; sparar `config.json` i `~/.config/vkc-kiosk/` **utanför** repot och återställer efteråt. Stashar bara tracked kod (aldrig `-u`) |
| `update` | delvis | `pull` + `pip install -r requirements.txt` + `install.sh`/`restart` |
| `config` | nej | Öppna `config.json` i `$EDITOR` (standard `nano`) |
| `save-config` | nej | Spegla nuvarande (bra) `config.json` → `~/.config/vkc-kiosk/` — kör efter manuell edit |
| `restore-config` | nej | Återställ `config.json` från `~/.config/vkc-kiosk/` |
| `url` | nej | Skriv ut `http://127.0.0.1:<port>/` |
| `setup-reader` | **ja** | YAROGNTEC/SDZNKJLTD (`ffff:0035`): cmdline, udev, quirk — **reboot efteråt** |
| `configure-reader` | nej* | Interaktiv läsare + kortformat → `config.json` (*stoppar tjänsten tillfälligt) |
| `slides` | nej | Hantera karusell (`KIOSK.slides`): URL, ordning, `durationSeconds`, `reloadIntervalSeconds`. Alias: `karusell` |

`config.json` ligger **inte** i git. Mall vid ny install: `config.example.json`.  
WiFi hanteras **inte** av `vkc-kiosk` — använd skrivbordets nätverks-GUI / nyckelring.

### Exempel

```bash
# Drift
vkc-kiosk status
vkc-kiosk restart
vkc-kiosk logs

# Hämta kod (skyddar din config)
vkc-kiosk pull
vkc-kiosk update

# Kortläsare
sudo vkc-kiosk setup-reader    # bara YAROGNTEC — sedan: sudo reboot
vkc-kiosk configure-reader
vkc-kiosk devices

# Karusell / slides
vkc-kiosk slides

# Config
vkc-kiosk config
vkc-kiosk url
```

### Script bakom kommandona

| CLI | Script |
|-----|--------|
| `setup-reader` | `scripts/setup-yarogntec-reader.sh` → `deploy/install-usb-reader-quirk.sh` |
| `configure-reader` | `scripts/configure-card-reader.py` |
| `slides` | `scripts/manage-slides.py` |
| `devices` | `scripts/list_input_devices.py` (+ API) |

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

**WiFi / nyckelring (via GUI)**

WiFi sköts via skrivbordets nätverksinställningar — **inte** av `vkc-kiosk`.

Rensa gamla profiler vid behov, skapa nyckelring, anslut via GUI:

```bash
sudo rm -f /etc/netplan/99-vkc-kiosk-wifi.yaml
sudo rm -f /etc/NetworkManager/system-connections/vkc-kiosk-wifi.nmconnection
sudo nmcli connection reload
```

### Nyckelring som låses upp vid autologin

Enklast och vanligast på kiosk: **tomt lösenord på login-nyckelringen** (då låses den upp automatiskt).

1. Installera Seahorse om det saknas: `sudo apt install -y seahorse`
2. Öppna **Lösenord och nycklar** (Seahorse) → högerklicka **Inloggning** / **Login** → **Ändra lösenord**
3. Ange nuvarande nyckelringslösen → **lämna nya lösenordet tomt** → bekräfta varningen
4. Reboot. WiFi-lösen som sparats i nyckelringen ska gälla utan fråga.

Alternativ (samma lösen som användarkonto + PAM):

```bash
# Säkerställ gnome-keyring
sudo apt install -y gnome-keyring libpam-gnome-keyring

# För lightdm-autologin (vanligt på Pi OS) — lägg till om raderna saknas:
# /etc/pam.d/lightdm-autologin
#   auth    optional  pam_gnome_keyring.so
#   session optional  pam_gnome_keyring.so auto_start
#
# /etc/pam.d/lightdm
#   auth    optional  pam_gnome_keyring.so
#   session optional  pam_gnome_keyring.so auto_start
```

Sätt nyckelringens lösenord **identiskt** med användarens inloggningslösen. Vid autologin utan lösenordsruta fungerar tom nyckelringslösenord mer pålitligt.

**Pi Connect**  
Chromium körs med `--start-fullscreen` (inte hård `--kiosk`). Lämna med F11 eller Alt+Tab.

**`git pull` / fel eller gammal `config.json`**

Använd **alltid** `vkc-kiosk pull`. Efter manuell edit:

```bash
vkc-kiosk save-config    # spegla DIN nuvarande fil till ~/.config/vkc-kiosk/
```

Pull återställer bara den kopia som togs **i samma pull** (inte en gammal hem-backup).

---

## Avinstallera

```bash
cd ~/vkc-kiosk
sudo ./uninstall.sh
# sudo REMOVE_DIR=1 ./uninstall.sh   # tar även bort kodkatalogen
```
