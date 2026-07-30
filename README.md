# VKC Kiosk

Lokal kiosk + MIFARE-incheckning för Västerviks klättercenter (Raspberry Pi).

## Installera med ett kommando

På en Raspberry Pi (med skrivbord/autologin rekommenderas):

```bash
curl -fsSL https://raw.githubusercontent.com/VKC276/Kiosk/main/install.sh | sudo bash
```

Tills branchen är mergad till `main` kan du peka på feature-branchen:

```bash
curl -fsSL https://raw.githubusercontent.com/VKC276/Kiosk/cursor/kiosk-forbattringar-a840/install.sh \
  | sudo env KIOSK_BRANCH=cursor/kiosk-forbattringar-a840 bash
```

Eller från en redan klonad katalog:

```bash
git clone https://github.com/VKC276/Kiosk.git
cd Kiosk
sudo ./install.sh
```

Valfritt:

```bash
sudo KIOSK_USER=vkc KIOSK_DIR=/home/vkc/vkc-kiosk ./install.sh
sudo SKIP_BROWSER=1 ./install.sh          # bara API-tjänsten
```

Installern gör automatiskt:
- apt-paket (python3-venv, chromium, …)
- git-klon / uppdatering
- Python-venv + `requirements.txt`
- lägger användaren i gruppen `input` (kortläsare)
- systemd-tjänster: `vkc-kiosk` (API) + `vkc-kiosk-browser` (Chromium i **fullskärm**, inte hårdlåst kiosk)
- CLI-kommandot `vkc-kiosk`
- autostart-fallback för skrivbordet

Chromium startas med `--start-fullscreen` (inte `--kiosk`), så du kan fortfarande använda **Pi Connect**, Alt+Tab och F11.

## Efter installation

```bash
vkc-kiosk devices     # hitta kortläsarens /dev/input/event*
nano ~/vkc-kiosk/config.json
vkc-kiosk restart
vkc-kiosk status
vkc-kiosk logs
vkc-kiosk update      # git pull + pip + omstart
```

Reboot en gång efter första install så att `input`-behörigheten tar effekt.

## Config (`config.json`)

### Kortläsare

```json
"READER": {
  "device": "/dev/input/event0",
  "nameContains": "",
  "grab": true
}
```

### Cache / timeouts / kortformat / server

Se nycklarna `CACHE`, `TIMEOUTS`, `CARD_PROCESSING`, `SERVER` i `config.json`.

### Kiosk-slides (ingen Space behövs)

Övre delen byter sida **automatiskt** enligt timer. Incheckningen ligger kvar under — fokus stannar där, så du slipper Space-bläddring.

```json
"KIOSK": {
  "checkin": { "enabled": true, "path": "/checkin", "heightPercent": 20 },
  "reloadOnShow": true,
  "slides": [
    { "id": "top-sends", "title": "Topp Senders", "url": "https://...", "durationSeconds": 100 },
    { "id": "chart-1", "title": "Sändningar/dag", "url": "https://...", "durationSeconds": 15 },
    { "id": "wallflow", "title": "WallFlow", "url": "https://wallflow.vastervikclimbing.se/display.html", "durationSeconds": 60 }
  ]
}
```

Lägg till/ta bort/ändra ordning och `durationSeconds` per sida i config. (`durationMs` går också bra.)

## URL:er

- `/` – hel kiosk (timer-slides + incheckning)
- `/checkin` – bara incheckning
- `/healthz` – hälsokoll
- `/api/input-devices` – lista input-enheter

## Avinstallera

```bash
sudo ./uninstall.sh
# sudo REMOVE_DIR=1 ./uninstall.sh   # tar även bort kodkatalogen
```

## Manuell utveckling

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python wsgi.py
```
