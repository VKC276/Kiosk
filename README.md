# VKC Kiosk

Lokal kiosk + MIFARE-incheckning för Västerviks klättercenter (Raspberry Pi).

- **Övre ytan:** timer-styrd karusell (iframes / WallFlow / RSS)
- **Nedre ytan:** kortincheckning (medlem + 10-kort)
- **Cloudflare (rekommenderat):** Pi skickar bara det blippade kortnumret till Workern. Ingen lokal kortlista — kiosken behöver internet ändå (Pages/WallFlow).
- **Fallback:** Flask med nedladdad GAS-cache om `CLOUDFLARE.enabled` är `false`

Full guide: **[INSTALLATION.md](INSTALLATION.md)** · Worker: **[cloudflare/README.md](cloudflare/README.md)**

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

Sätt sedan `CLOUDFLARE` i `config.json` (Worker-URL + kiosk-token) efter [cloudflare/README.md](cloudflare/README.md).

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
| `url` | Kiosk-URL (Cloudflare eller lokal) |
| `setup-reader` | YAROGNTEC systemfix (sudo + reboot) |
| `configure-reader` | Läsare + kortformat → `config.json` |
| `slides` | Karusell (alias: `karusell`; publicerar till Worker om `adminToken` finns) |

WiFi: skrivbordets nätverks-GUI + login-nyckelring (Seahorse) — **inte** `vkc-kiosk`.

---

## Arkitektur (Cloudflare)

```
USB-läsare → agent.py (Pi) --POST /api/checkin--> Worker + D1
Chromium (Pi) --------------WebSocket-----------> samma Worker (kiosk-UI)
```

Pi driver ingen kiosk-webbserver. `vkc-kiosk.service` startar `agent.py`. Chromium öppnar Worker-URL:en.

Importera befintliga GAS-listor:

```bash
./venv/bin/python scripts/import-from-gas.py
```

---

## HTTP-API (Worker)

| URL | Syfte |
|-----|--------|
| `/` | Hel kiosk (slides + incheckning) |
| `/checkin.html` | Bara incheckning |
| `/api/kiosk/ws` | Live-status till skärmen |
| `/healthz` | Hälsokoll + antal kort |
| `/api/checkin` | Blipp (kiosk-token) |

Lokal Flask-API (`CLOUDFLARE.enabled=false`) finns kvar som tidigare: `/checkin`, `/stream`, `/api/cache/*`.

---

## Config

- **Lokal** `config.json` — trackas **inte** i git
- Mall: [`config.example.json`](config.example.json)
- Efter ändring: `vkc-kiosk save-config`
- Uppdatera kod: alltid `vkc-kiosk pull` (inte rå `git pull`)

`CLOUDFLARE.enabled=true` kräver `apiUrl` + `token`. Utan det fortsätter Pi:n med lokal Flask/GAS.

Detaljer om `READER`, `CARD_PROCESSING`, `KIOSK.slides`, cache, timeouts, 10-kort och WiFi: [INSTALLATION.md](INSTALLATION.md).

---

## Repostruktur

| Sökväg | Roll |
|--------|------|
| `agent.py` | Kortläsar-agent mot Cloudflare |
| `app.py` / `wsgi.py` | Flask-fallback + Gunicorn |
| `cloudflare/` | Worker, D1-migrationer, kiosk-UI |
| `card_convert.py` | Kort-ID-konvertering (HEX/DEC, byte/nibble-order) |
| `reader_usb.py` | PyUSB-backend (YAROGNTEC iface 0) |
| `config.example.json` | Mall för lokal `config.json` |
| `templates/` | Flask-UI (endast fallback) |
| `scripts/vkc-kiosk.sh` | CLI (`vkc-kiosk`) |
| `scripts/import-from-gas.py` | Flytta GAS-listor → D1 |
| `deploy/` | systemd, udev, browser-start, USB-quirk |
| `install.sh` / `uninstall.sh` | Installation |

---

## Utveckling lokalt

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp config.example.json config.json   # fyll i Cloudflare eller GAS
cd cloudflare && npm install && npm test
```

Worker: `cd cloudflare && npx wrangler dev`

Lokal Flask-fallback: `./venv/bin/python wsgi.py`

## Avinstallera

```bash
sudo ./uninstall.sh
# sudo REMOVE_DIR=1 ./uninstall.sh
```
