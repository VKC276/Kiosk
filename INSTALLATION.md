# Installationsanvisningar — VKC Kiosk

Guide för att sätta upp kiosken på en Raspberry Pi med Pi OS.

## Förutsättningar

- Raspberry Pi med **Pi OS** (skrivbordsversion)
- Internetuppkoppling
- **Autologin** till skrivbordet rekommenderas (så Chromium startar vid boot)
- Kortläsare inkopplad (USB)

Valfritt men praktiskt:
- [Raspberry Pi Connect](https://www.raspberrypi.com/documentation/services/connect.html) för fjärrstyrning (fungerar — skärmen är bara i fullskärm, inte hårdlåst)

## 1. Installera

Öppna Terminal på Pi:n och kör:

```bash
curl -fsSL https://raw.githubusercontent.com/VKC276/Kiosk/main/install.sh | sudo bash
```

Installern sätter upp:
- nödvändiga apt-paket (Python, Chromium, …)
- kod under `~/vkc-kiosk` (eller vald katalog)
- Python-venv och beroenden
- behörighet till kortläsare (`input`-gruppen)
- systemd-tjänster: `vkc-kiosk` (API) + `vkc-kiosk-browser` (Chromium)
- kommandot `vkc-kiosk`

### Alternativ: klona själv

```bash
git clone https://github.com/VKC276/Kiosk.git
cd Kiosk
sudo ./install.sh
```

### Valfria miljövariabler

```bash
sudo KIOSK_USER=vkc KIOSK_DIR=/home/vkc/vkc-kiosk ./install.sh
sudo SKIP_BROWSER=1 ./install.sh    # bara API, ingen Chromium-tjänst
```

## 2. Hitta kortläsaren

```bash
vkc-kiosk devices
```

Notera sökvägen, t.ex. `/dev/input/event3`.

## 3. Justera config

```bash
nano ~/vkc-kiosk/config.json
```

Minst detta:

```json
"READER": {
  "device": "/dev/input/event3",
  "nameContains": "",
  "grab": true
}
```

Tips: om `event*`-numret ändras vid omstart kan du i stället sätta `nameContains` till en unik del av enhetsnamnet (syns i `vkc-kiosk devices`).

### Slides (övre skärmytan)

Varje post i `KIOSK.slides` är en sida med egen visningstid:

```json
"KIOSK": {
  "checkin": { "enabled": true, "path": "/checkin", "heightPercent": 20 },
  "reloadOnShow": true,
  "slides": [
    { "id": "top-sends", "title": "Topp Senders", "url": "https://...", "durationSeconds": 100 },
    { "id": "chart-1", "title": "Diagram", "url": "https://...", "durationSeconds": 15 }
  ]
}
```

Incheckningen ligger alltid kvar längst ner. Sidor byts automatiskt — ingen Space behövs.

## 4. Starta om tjänster och reboot:a

```bash
vkc-kiosk restart
sudo reboot
```

Reboot behövs så att `input`-gruppens behörighet tar effekt för kortläsaren.

## 5. Kontrollera

Efter reboot:

```bash
vkc-kiosk status
```

Förväntat:
- API svarar på `http://127.0.0.1:8081/`
- Chromium öppnas i fullskärm med kiosk + incheckning
- En tunn tidslinje längst ner på innehållsytan visar tid kvar på aktuell slide

Loggar:

```bash
vkc-kiosk logs
```

## 6. Ljud (valfritt)

Lägg dessa filer i `~/vkc-kiosk/static/` om du vill ha ljud vid blipp:

- `success.mp3`
- `failure.mp3`
- `warning.mp3`

## Daglig drift

| Kommando | Vad det gör |
|----------|-------------|
| `vkc-kiosk status` | Status + healthz |
| `vkc-kiosk restart` | Starta om API/browser |
| `vkc-kiosk devices` | Lista input-enheter |
| `vkc-kiosk update` | `git pull` + pip + omstart |
| `vkc-kiosk logs` | Följ journal-loggar |
| `vkc-kiosk config` | Öppna `config.json` |

## Felsökning

**Kortläsaren reagerar inte**
1. `vkc-kiosk devices` — rätt `READER.device`?
2. Har du rebootat efter install?
3. `groups` — ska innehålla `input`
4. `vkc-kiosk logs` — fel om saknad enhet / behörighet?

**Tom/vit skärm i Chromium**
1. `curl -s http://127.0.0.1:8081/healthz`
2. `vkc-kiosk restart`
3. Kontrollera att du är inloggad på skrivbordet (grafisk session)

**Chromium öppnar nya flikar i en loop**
Orsak: browsern startades flera gånger (systemd + autostart, eller `Restart=always`).
Stoppa loopen:

```bash
sudo systemctl stop vkc-kiosk-browser
rm -f ~/.config/autostart/vkc-kiosk.desktop
pkill -f vkc-kiosk-chromium || true
cd ~/vkc-kiosk && git pull && sudo SKIP_APT=1 ./install.sh
```

**USB-läsare + `HC died` / `couldn't find an input interrupt endpoint` (SDZNKJLTD ffff:0035)**  
Kernel-`usbhid` på interface 1 krockar med Pi xHCI.  
Lösning: `authorized_default=0` + prepare-script som **lossar `usbhid` före authorize**, låser iface med `driver_override`, läser **iface 0 via PyUSB**.

```bash
cd ~/vkc-kiosk
# Om config.json blockerar pull: cp config.json /tmp/ && git checkout -- config.json
git pull
./venv/bin/pip install -r requirements.txt
sudo ./deploy/install-usb-reader-quirk.sh
sudo reboot
```

Efter reboot (gärna via USB2-hub):

```bash
cat /proc/cmdline | tr ' ' '\n' | grep -E 'authorized_default|usbhid.quirks'
# båda raderna måste synas
sudo dmesg -w
journalctl -t vkc-kiosk -n 20
```

Förväntat vid inkoppling:
- Hub + `USB Reader` syns (`authorized to connect`)
- journal: `usbhid unloaded before authorize` + `reader prepared`
- **Ingen** `usbhid ... couldn't find an input interrupt endpoint` / `HC died`

```bash
sudo systemctl restart vkc-kiosk
journalctl -u vkc-kiosk -f
# ska visa: USB-kortläsartråd startad (pyusb) / USB: Ansluten ... Lyssnar
```

`config.json`: `"READER": { "backend": "usb", "usbVendor": "0xffff", "usbProduct": "0x0035" }`  
(sätts av quirk-scriptet). Om USB redan dött → **reboot** först.

Om `usbhid`-unload misslyckas och felet kvarstår (sista utvägen — USB-tangentbord slutar fungera; använd Pi Connect):

```bash
echo 'blacklist usbhid' | sudo tee /etc/modprobe.d/blacklist-usbhid-vkc.conf
sudo reboot
```

**Pi Connect**
Chromium körs i vanlig fullskärm (`--start-fullscreen`), inte hårdlåst kiosk. Du kan lämna med F11 eller Alt+Tab.

## Avinstallera

```bash
cd ~/vkc-kiosk
sudo ./uninstall.sh
# sudo REMOVE_DIR=1 ./uninstall.sh   # tar även bort kodkatalogen
```
