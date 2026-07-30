# VKC Kiosk

Lokal kiosk + MIFARE-incheckning för Västerviks klättercenter (Raspberry Pi).

## Installation

Se **[INSTALLATION.md](INSTALLATION.md)** för steg-för-steg.

Kortversion:

```bash
curl -fsSL https://raw.githubusercontent.com/VKC276/Kiosk/main/install.sh | sudo bash
vkc-kiosk devices
nano ~/vkc-kiosk/config.json   # sätt READER.device
vkc-kiosk restart
sudo reboot
```

## Vad systemet gör

- **`/`** – hel kiosk: timer-styrda slides + incheckning
- **`/checkin`** – bara incheckningsytan
- **`/stream`** – SSE vid kortblipp
- **`/healthz`** – hälsokoll
- **`/api/input-devices`** – lista tangentbord/input-enheter

Kortläsaren körs via `evdev`. Medlems- och 10-kort cacheas från Google Apps Script. Innehållssidor byts automatiskt enligt `config.json` (ingen Space behövs). Chromium körs i fullskärm så **Pi Connect** fortfarande fungerar.

## Config

Allt styrs i `config.json`: kortläsare, cache-intervall, timeouts, kortformat, serverport och `KIOSK.slides`. Detaljer i [INSTALLATION.md](INSTALLATION.md).

## Drift

```bash
vkc-kiosk status
vkc-kiosk restart
vkc-kiosk update
vkc-kiosk logs
```

## Utveckling lokalt

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python wsgi.py
```

## Avinstallera

```bash
sudo ./uninstall.sh
```
