# VKC Kiosk

Lokal kiosk + MIFARE-incheckning för Västerviks klättercenter (Raspberry Pi).

- **Övre ytan:** timer-styrd karusell (iframes / WallFlow / RSS)
- **Nedre ytan:** kortincheckning (medlem + 10-kort)
- **Cloudflare:** Pi skickar bara det blippade kortnumret till Workern. Ingen lokal kortlista — kiosken behöver internet ändå (Pages/WallFlow).

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

Äldre Pi som fortfarande kör Flask/GAS → Cloudflare (släcker lokal webbserver, behåller READER):

```bash
sudo KIOSK_TOKEN='samma-som-wrangler-secret' ./scripts/switch-to-cloudflare.sh
```

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
| `update` | `pull` + pip + ominstallation (`SKIP_READER`) |
| `switch-cloudflare` | Migrera äldre Flask/GAS-Pi, behåller läsarconfig |
| `config` | Öppna `config.json` |
| `save-config` | Spegla config → `~/.config/vkc-kiosk/` (**kör efter manuell edit**) |
| `restore-config` | Återställ från `~/.config/vkc-kiosk/` |
| `url` | Kiosk-URL (Worker) |
| `setup-reader` | YAROGNTEC systemfix (sudo + reboot) |
| `configure-reader` | Läsare + kortformat → `config.json` |
| `slides` | Karusell (alias: `karusell`; publicerar till Worker om `adminToken` finns) |

WiFi: skrivbordets nätverks-GUI + login-nyckelring (Seahorse) — **inte** `vkc-kiosk`.

---

## Arkitektur

```
USB-läsare → agent.py (Pi) --POST /api/checkin--> Worker + D1
Chromium (Pi) --------------WebSocket-----------> samma Worker (kiosk-UI)
```

Pi driver ingen lokal webbserver. `vkc-kiosk.service` startar `agent.py`. Chromium öppnar Worker-URL:en.

Importera kortlistor (xlsx rekommenderas):

```bash
cd cloudflare && node scripts/import-from-xlsx.mjs ../CurrentDataSet/10-kort.xlsx \
  --api-url https://vkc-kiosk.<konto>.workers.dev \
  --admin-token "$ADMIN_TOKEN"
```

---

## HTTP-API (Worker)

| URL | Syfte |
|-----|--------|
| `/` | Hel kiosk (slides + incheckning) |
| `/checkin.html` | Bara incheckning |
| `/api/kiosk/ws` | Live-status till skärmen |
| `/healthz` | Hälsokoll |
| `/api/checkin` | Blipp (kiosk-token) |

---

## Config

- **Lokal** `config.json` — trackas **inte** i git
- Mall: [`config.example.json`](config.example.json)
- Efter ändring: `vkc-kiosk save-config`
- Uppdatera kod: alltid `vkc-kiosk pull` (inte rå `git pull`)

Kräver `CLOUDFLARE.apiUrl` + `CLOUDFLARE.token` (samma värde som Worker-secret `KIOSK_TOKEN`).

Detaljer: [INSTALLATION.md](INSTALLATION.md).

---

## Repostruktur

| Sökväg | Roll |
|--------|------|
| `agent.py` | Kortläsar-agent mot Cloudflare |
| `cloudflare/` | Worker, D1-migrationer, kiosk-UI |
| `card_convert.py` | Kort-ID-konvertering (HEX/DEC, byte/nibble-order) |
| `reader_usb.py` | PyUSB-backend (YAROGNTEC iface 0) |
| `config.example.json` | Mall för lokal `config.json` |
| `scripts/vkc-kiosk.sh` | CLI (`vkc-kiosk`) |
| `scripts/import-from-xlsx.py` | Import xlsx → D1 |
| `scripts/import-from-gas.py` | Engångsimport från gamla GAS-URL:er |
| `deploy/` | systemd, udev, browser-start, USB-quirk |
| `install.sh` / `uninstall.sh` | Installation |

---

## Utveckling lokalt

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp config.example.json config.json   # fyll i CLOUDFLARE.token
cd cloudflare && npm install && npm test
```

Worker: `cd cloudflare && npx wrangler dev`

Agent (mot lokal Worker): `./venv/bin/python agent.py`

## Avinstallera

```bash
sudo ./uninstall.sh
# sudo REMOVE_DIR=1 ./uninstall.sh
```
