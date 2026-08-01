# VKC Kiosk

Lokal kiosk + MIFARE-incheckning för Västerviks klättercenter (Raspberry Pi).

- **Övre ytan:** timer-styrd karusell (iframes / WallFlow / RSS)
- **Nedre ytan:** kortincheckning (medlem + 10-kort) via USB-läsare
- **Backend:** Flask/Gunicorn, lokal cache mot Google Apps Script
- **Drift-CLI:** `vkc-kiosk`

Full guide: **[INSTALLATION.md](INSTALLATION.md)**

---

## Snabbstart

```bash
curl -fsSL https://raw.githubusercontent.com/VKC276/Kiosk/main/install.sh | sudo bash
```

**YAROGNTEC / SDZNKJLTD** (`ffff:0035`) — krävs separat (annars kan Pi USB dö):

```bash
sudo vkc-kiosk setup-reader
sudo reboot
vkc-kiosk configure-reader
vkc-kiosk save-config
vkc-kiosk restart
```

Övriga keyboard-wedge-läsare: bara `configure-reader` (ingen `setup-reader`).

---

## Verktyg (`vkc-kiosk`)

```bash
vkc-kiosk help
```

| Kommando | Beskrivning |
|----------|-------------|
| `status` / `start` / `stop` / `restart` / `logs` | Tjänster + healthz / journal |
| `devices` | Lista kortläsare |
| `pull` | `git pull` med skydd av `config.json` |
| `update` | `pull` + pip + ominstallation |
| `config` | Öppna `config.json` |
| `save-config` | Spegla config → `~/.config/vkc-kiosk/` (**kör efter manuell edit**) |
| `restore-config` | Återställ från `~/.config/vkc-kiosk/` |
| `url` | Lokal kiosk-URL |
| `setup-reader` | YAROGNTEC systemfix (sudo + reboot) |
| `configure-reader` | Läsare + kortformat → `config.json` |
| `slides` | Karusell (alias: `karusell`) |

WiFi: skrivbordets nätverks-GUI + login-nyckelring (Seahorse) — **inte** `vkc-kiosk`.

---

## HTTP-API

| URL | Syfte |
|-----|--------|
| `/` | Hel kiosk (slides + incheckning) |
| `/checkin` | Bara incheckning |
| `/stream` | SSE vid kortblipp |
| `/healthz` | Hälsokoll + cache |
| `/api/cache/refresh` | Tvinga omhämtning från GAS |
| `/api/cache/lookup/<id>` | Finns kortet i cachen? |
| `/api/input-devices` | Lista evdev-enheter |

---

## Config

- **Lokal** `config.json` — trackas **inte** i git
- Mall: [`config.example.json`](config.example.json)
- Efter ändring: `vkc-kiosk save-config`
- Uppdatera kod: alltid `vkc-kiosk pull` (inte rå `git pull`)

Detaljer om `READER`, `CARD_PROCESSING`, `KIOSK.slides`, cache, timeouts, 10-kort och WiFi: [INSTALLATION.md](INSTALLATION.md).

---

## Repostruktur

| Sökväg | Roll |
|--------|------|
| `app.py` / `wsgi.py` | Flask-app + Gunicorn-entry |
| `card_convert.py` | Kort-ID-konvertering (HEX/DEC, byte/nibble-order) |
| `reader_usb.py` | PyUSB-backend (YAROGNTEC iface 0) |
| `config.example.json` | Mall för lokal `config.json` |
| `templates/` | `kiosk.html` (karusell) + `checkin.html` |
| `scripts/vkc-kiosk.sh` | CLI (`vkc-kiosk`) |
| `scripts/setup-yarogntec-reader.sh` | Systemfix USB-läsare |
| `scripts/configure-card-reader.py` | Interaktiv läsar-/formatassistent |
| `scripts/manage-slides.py` | Karusell-hjälpare |
| `deploy/` | systemd, udev, browser-start, USB-quirk |
| `install.sh` / `uninstall.sh` | Installation |

---

## Utveckling lokalt

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp config.example.json config.json   # fyll i URL:er
./venv/bin/python wsgi.py
```

## Avinstallera

```bash
sudo ./uninstall.sh
# sudo REMOVE_DIR=1 ./uninstall.sh
```
