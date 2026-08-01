# Installationsanvisningar — VKC Kiosk

Guide för Raspberry Pi (Pi OS, skrivbordsversion). Pi 4/5 rekommenderas.

## Förutsättningar

- Pi OS med skrivbord
- Internet (WiFi eller ethernet)
- **Autologin** till skrivbordet (Chromium startar vid boot)
- USB-kortläsare

Valfritt: [Raspberry Pi Connect](https://www.raspberrypi.com/documentation/services/connect.html) — fungerar; skärmen är fullskärm, inte hårdlåst kiosk.

---

## 1. Installera

```bash
curl -fsSL https://raw.githubusercontent.com/VKC276/Kiosk/main/install.sh | sudo bash
```

Installern sätter upp:

- apt-paket (Python, Chromium, …)
- kod under `~/vkc-kiosk` (klon från `main`)
- Python-venv och beroenden
- behörighet till kortläsare (`input` / `plugdev`)
- systemd: `vkc-kiosk` (API) + `vkc-kiosk-browser` (Chromium)
- kommandot `vkc-kiosk` → `/usr/local/bin/vkc-kiosk`
- `config.json` från `config.example.json` om den saknas

### Alternativ: klona själv

```bash
git clone https://github.com/VKC276/Kiosk.git ~/vkc-kiosk
cd ~/vkc-kiosk
sudo ./install.sh
```

### Valfria miljövariabler

```bash
sudo KIOSK_USER=vkc KIOSK_DIR=/home/vkc/vkc-kiosk ./install.sh
sudo SKIP_BROWSER=1 ./install.sh    # bara API
sudo SKIP_APT=1 ./install.sh        # vid uppdatering / ominstallation
```

---

## 2. Kortläsare

### A) YAROGNTEC / SDZNKJLTD (`ffff:0035`) — kräver systemfix

Läsaren kan krascha Pi USB (`HC died`) om kernel-`usbhid` binder interface 1. Kör **alltid**:

```bash
sudo vkc-kiosk setup-reader
# samma: sudo ./scripts/setup-yarogntec-reader.sh
sudo reboot
```

| Ändring | Syfte |
|--------|--------|
| `usbcore.authorized_default=0` i cmdline | Enheter startar unauthorized |
| `usbhid.quirks=0xffff:0x0035:0x4` | Extra ignore-skydd |
| udev + `deploy/prepare-sdznkj-reader.sh` | Authorize säkert, `driver_override`, undvik iface 1 |
| modprobe-quirk | Persistens över reboot |
| `pyusb` i venv | Appen läser iface 0 direkt |
| `READER.backend=usb` i config | PyUSB-backend |

**Övriga läsare** (HID keyboard-wedge): **ingen** `setup-reader`.

**USB-tangentbord** (t.ex. ActiveJet): blacklista **inte** hela `usbhid`.

### B) Konfigurera läsare + kortformat (alla läsare)

```bash
vkc-kiosk configure-reader
# samma: ./venv/bin/python scripts/configure-card-reader.py
vkc-kiosk save-config
```

Assistenten:

1. Listar USB- och evdev-läsare  
2. Stoppar tillfälligt `vkc-kiosk` om den håller läsaren  
3. Blippa kort (eller klistra in rådata)  
4. Visar kombinationer av `FORMAT` / `BYTE_ORDER` / `NIBBLE_ORDER` / `hexUidChars`  
5. Sparar till `config.json` (även `config.json.bak`)

Ange gärna förväntat medlems-ID (t.ex. `1443137877`) så rätt rad markeras.

### Typisk YAROGNTEC-config

Rå `'00000055984065'` → `'1443137877'`:

```json
"READER": {
  "backend": "usb",
  "usbVendor": "0xffff",
  "usbProduct": "0x0035",
  "nameContains": "SDZNKJLTD USB Reader",
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

`hexUidChars` = UID-längd i hex-tecken (4-byte MIFARE = 8). Ledande `00` från läsarpadding trimmas bara om strängen är längre än så.

Delad logik: `card_convert.py`.

---

## 3. Config (`config.json`)

- Trackas **inte** i git (se `.gitignore`)
- Mall: `config.example.json`
- Redigera: `vkc-kiosk config` eller `nano ~/vkc-kiosk/config.json`
- **Efter varje manuell ändring:** `vkc-kiosk save-config`  
  (speglar till `~/.config/vkc-kiosk/` utanför repot)

### Google Apps Script

| Nyckel | Innehåll |
|--------|----------|
| `DATA_URL` | Medlemslista (fält `Kortnummer`) |
| `TEN_VISIT_DATA_URL` | 10-kort / klippkort |
| `LOG_URL` | Incheckningslogg |
| `GAS_UPDATE_URL_BASE` | Klippning av 10-kort |

### Cache

| Nyckel | Standard | Betydelse |
|--------|----------|-----------|
| `CACHE.updateIntervalSeconds` | `1800` | Omhämtning ca var 30:e min |
| `CACHE.fetchTimeoutSeconds` | `30` | Timeout mot GAS |
| `CACHE.userAgent` | `Mifare Reader Backend` | HTTP User-Agent |

Före första lyckade hämtningen visas väntetext om kort blippas. Tvinga omhämtning:

```bash
curl -s http://127.0.0.1:8081/api/cache/refresh
curl -s http://127.0.0.1:8081/api/cache/lookup/1443137877
```

### Timeouts / UI

| Nyckel | Standard | Betydelse |
|--------|----------|-----------|
| `TIMEOUTS.statusDisplaySeconds` | `3` | Hur länge vanlig status visas |
| `TIMEOUTS.lastClipOkSeconds` | `3` | Fas 1 vid sista 10-kortklipp (“Klipp OK!”) |
| `TIMEOUTS.lastClipReturnSeconds` | `5` | Fas 2 (“Lämna in kortet i reception”) |
| `TIMEOUTS.logRequestSeconds` | `5` | Timeout logg-anrop |
| `TIMEOUTS.clipRequestSeconds` | `10` | Timeout klipp-anrop |
| `TIMEOUTS.sseHeartbeatSeconds` | `20` | SSE-heartbeat |

### 10-kort / klippkort

- Anonyma 10-kort visar inte placeholder-namn (“Klippkorts-användare”)
- Slut / 0 kvar: uppmaning att lämna in kortet i reception
- Sista klippet (1→0): orange status i två faser (OK → lämna in) + varningsljud om `static/warning.mp3` finns

### Slides / karusell

```bash
vkc-kiosk slides
```

```json
"KIOSK": {
  "checkin": { "enabled": true, "path": "/checkin", "heightPercent": 20 },
  "reloadOnShow": false,
  "reloadIntervalSeconds": 300,
  "slides": [
    {
      "id": "bl-leder",
      "title": "Blå leder",
      "url": "https://wallflow.vastervikclimbing.se/display.html#blå",
      "durationSeconds": 15,
      "reloadIntervalSeconds": 900
    }
  ]
}
```

| Fält | Betydelse |
|------|-----------|
| `durationSeconds` | Visningstid i karusellen |
| `KIOSK.reloadIntervalSeconds` | Standard-refresh om slide saknar eget värde |
| `slides[].reloadIntervalSeconds` | Egen refresh (sekunder); `0` = aldrig |
| `reloadOnShow: true` | Gammalt läge: ladda om vid varje byte |

**Hash-URL:er** (`#blå`, `#grön`, …) stöds: URL:er skickas via JSON till webbläsaren så fragmentet bevaras. Refresh-parametern läggs **före** `#`.

Iframes behålls mellan varv (`reloadOnShow: false`) — bra för CPU.

---

## 4. Starta / kontrollera

```bash
vkc-kiosk restart
vkc-kiosk status
curl -s http://127.0.0.1:8081/healthz
```

Efter `setup-reader` / första install: `sudo reboot`.

Förväntat:

- API på porten i config (standard `8081`)
- Chromium fullskärm: slides + incheckning
- Kortblipp → status i nedre ytan

```bash
vkc-kiosk logs
# Exempel i loggen:
# KORT RÅDATA: '00000055984065' ...
# KORT EFTER KONVERT: '1443137877' ...
```

---

## 5. Ljud (valfritt)

Lägg i `~/vkc-kiosk/static/`:

- `success.mp3`
- `failure.mp3`
- `warning.mp3` (sista 10-kortklipp)

---

## 6. WiFi / nyckelring (GUI)

WiFi sköts **inte** av `vkc-kiosk` — använd skrivbordets nätverksmeny.

### Skapa login-nyckelring (om bara Chromium syns)

Chromium har egen nyckelring. WiFi behöver en **login**-nyckelring:

1. `sudo apt install -y seahorse gnome-keyring`
2. Öppna **Lösenord och nycklar** (`seahorse`)
3. **+** → Password keyring → namn `login`
4. **Lösenord: lämna tomt** (auto-upplås vid autologin)
5. Högerklicka → **Ange som standard**
6. Anslut WiFi via GUI och spara lösenordet
7. Reboot

### Om login redan finns

Seahorse → **Inloggning** → **Ändra lösenord** → nytt lösenord **tomt**.

Valfritt PAM (samma lösen som användarkonto): se äldre anteckningar i git-historik; på kiosk med autologin är **tom login-nyckelring** mer pålitligt.

Rensa ev. gamla automatiska wifi-filer:

```bash
sudo rm -f /etc/netplan/99-vkc-kiosk-wifi.yaml
sudo rm -f /etc/NetworkManager/system-connections/vkc-kiosk-wifi.nmconnection
sudo nmcli connection reload
```

---

## Verktyg — `vkc-kiosk`

Installeras som `/usr/local/bin/vkc-kiosk` → `scripts/vkc-kiosk.sh`.  
Hjälp: `vkc-kiosk` / `vkc-kiosk help`.

| Kommando | sudo? | Vad det gör |
|----------|-------|-------------|
| `status` | nej | systemd + `/healthz` |
| `start` / `stop` / `restart` | ja | Styra API (+ browser) |
| `logs` | ja | `journalctl -f` |
| `devices` | nej | Lista läsare + API |
| `pull` | nej | `git pull`; skyddar **nuvarande** `config.json` via `/tmp`-kopia; speglar även till `~/.config/vkc-kiosk/`; stashar bara **tracked** filer |
| `update` | delvis | `pull` + pip + `install.sh` / restart |
| `config` | nej | Öppna `config.json` |
| `save-config` | nej | Spegla nuvarande config → `~/.config/vkc-kiosk/` |
| `restore-config` | nej | Återställ från `~/.config/vkc-kiosk/` |
| `url` | nej | Lokal URL |
| `setup-reader` | **ja** | YAROGNTEC systemfix + reboot |
| `configure-reader` | nej* | Läsare + format (*stoppar tjänsten tillfälligt) |
| `slides` / `karusell` | nej | Hantera karusell |

### Script bakom CLI

| CLI | Script |
|-----|--------|
| `setup-reader` | `scripts/setup-yarogntec-reader.sh` → `deploy/install-usb-reader-quirk.sh` |
| `configure-reader` | `scripts/configure-card-reader.py` (+ `card_convert.py`) |
| `slides` | `scripts/manage-slides.py` |
| `devices` | `scripts/list_input_devices.py` |

### Rekommenderad daglig uppdatering

```bash
vkc-kiosk save-config    # om du nyss editerat config
vkc-kiosk pull
vkc-kiosk restart
```

### API

| URL | Syfte |
|-----|--------|
| `/` | Hel kiosk |
| `/checkin` | Bara incheckning |
| `/stream` | SSE |
| `/healthz` | Hälsokoll + cache |
| `/api/cache/refresh` | Omhämtning GAS |
| `/api/cache/lookup/<id>` | Uppslag i cache |
| `/api/input-devices` | evdev-lista |

---

## Repostruktur

| Sökväg | Roll |
|--------|------|
| `app.py`, `wsgi.py` | Flask + Gunicorn |
| `card_convert.py` | Kortkonvertering |
| `reader_usb.py` | PyUSB-läsning |
| `config.example.json` | Mall (ersätter inte din lokala config) |
| `templates/kiosk.html` | Karusell (JSON-URL:er, hash-stöd) |
| `templates/checkin.html` | Inchecknings-UI |
| `deploy/` | systemd, udev, browser-start, USB-quirk |
| `scripts/` | CLI och assistenter |
| `static/` | Valfria ljudfiler |
| `install.sh` / `uninstall.sh` | Install / avinstallera |

---

## Felsökning

**Kortläsaren reagerar inte**

1. `vkc-kiosk devices` / `configure-reader`
2. YAROGNTEC: `setup-reader` + reboot?
3. `groups` ska innehålla `input` / `plugdev`
4. `vkc-kiosk logs`
5. `sudo systemctl stop vkc-kiosk` sedan `configure-reader`

**Fel kort-ID / antal siffror** → `vkc-kiosk configure-reader` med förväntat ID från medlemslistan.

**Kortet hittas inte**

```bash
curl -s http://127.0.0.1:8081/api/cache/refresh
curl -s http://127.0.0.1:8081/api/cache/lookup/<id>
```

**Tom/vit skärm**

```bash
curl -s --max-time 3 http://127.0.0.1:8081/healthz
sudo systemctl restart vkc-kiosk vkc-kiosk-browser
```

**Chromium öppnar flikar i loop**

```bash
sudo systemctl stop vkc-kiosk-browser
rm -f ~/.config/autostart/vkc-kiosk.desktop
pkill -f vkc-kiosk-chromium || true
cd ~/vkc-kiosk && vkc-kiosk pull && sudo SKIP_APT=1 ./install.sh
```

**USB `HC died` (YAROGNTEC)**

```bash
sudo vkc-kiosk setup-reader && sudo reboot
cat /proc/cmdline | tr ' ' '\n' | grep -E 'authorized_default|usbhid.quirks'
```

**`config.json` fel / borta**

```bash
vkc-kiosk restore-config
# eller: cp -a ~/.config/vkc-kiosk/config.json ~/vkc-kiosk/config.json
ls -lt ~/.config/vkc-kiosk/
```

Använd **alltid** `vkc-kiosk pull`. Efter manuell edit: `vkc-kiosk save-config`.

**WallFlow-färg (`#blå` m.m.) fel sida** → uppdatera kod (`vkc-kiosk pull`) och hårdstarta browser. URL:er ska komma via JSON, inte trasiga HTML-attribut.

**Pi Connect** — fullskärm (`--start-fullscreen`), lämna med F11 / Alt+Tab.

**Hög CPU** — normalt med Chromium + flera iframes. Längre `reloadIntervalSeconds` sänker lasten. Temp ~70 °C under last är ofta OK; oro runt ~80–85 °C.

---

## Avinstallera

```bash
cd ~/vkc-kiosk
sudo ./uninstall.sh
# sudo REMOVE_DIR=1 ./uninstall.sh   # tar även bort kodkatalogen
```
