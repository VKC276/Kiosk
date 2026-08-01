# VKC Kiosk

Lokal kiosk + MIFARE-incheckning för Västerviks klättercenter (Raspberry Pi).

## Installation

Se **[INSTALLATION.md](INSTALLATION.md)** för steg-för-steg.

Kortversion:

```bash
curl -fsSL https://raw.githubusercontent.com/VKC276/Kiosk/main/install.sh | sudo bash
vkc-kiosk configure-reader    # välj läsare + kortformat → skriver config.json
vkc-kiosk restart
```

### YAROGNTEC / SDZNKJLTD USB-läsare (`ffff:0035`)

Den läsaren kräver extra systemändringar (annars kan Pi USB dö). Kör **separat**:

```bash
sudo vkc-kiosk setup-reader
# eller: sudo ./scripts/setup-yarogntec-reader.sh
sudo reboot
vkc-kiosk configure-reader
vkc-kiosk restart
```

Övriga keyboard-wedge-läsare: bara `configure-reader` — ingen setup-reader.

## Vad systemet gör

- **`/`** – hel kiosk: timer-styrda slides + incheckning
- **`/checkin`** – bara incheckningsytan
- **`/stream`** – SSE vid kortblipp
- **`/healthz`** – hälsokoll
- **`/api/input-devices`** – lista tangentbord/input-enheter
- **`/api/cache/refresh`** – tvinga omhämtning av medlemscache
- **`/api/cache/lookup/<id>`** – felsök om kort finns i cache

Kortläsaren körs via `evdev` eller PyUSB (`READER.backend`). Medlems- och 10-kort cacheas från Google Apps Script. Chromium körs i fullskärm så **Pi Connect** fungerar.

## Config

Allt styrs i **lokal** `config.json` (trackas inte i git — mall: `config.example.json`).  
Använd `vkc-kiosk configure-reader` i stället för manuell kortformatsredigering när det går. Detaljer i [INSTALLATION.md](INSTALLATION.md).

## Verktyg (`vkc-kiosk`)

Efter installation: `vkc-kiosk help` (eller `vkc-kiosk` utan argument).

| Kommando | Beskrivning |
|----------|-------------|
| `status` | systemd-status för API/browser + `/healthz` |
| `start` / `stop` / `restart` | Styra tjänsterna |
| `logs` | Följ journal-loggar (`vkc-kiosk` + browser) |
| `devices` | Lista input-/USB-läsare |
| `pull` | `git pull` med config-backup i `~/.config/vkc-kiosk/` |
| `update` | `pull` + pip + ominstallation/restart |
| `config` | Öppna `config.json` i `$EDITOR` |
| `save-config` | Spegla nuvarande config → `~/.config/vkc-kiosk/` |
| `restore-config` | Återställ `config.json` från `~/.config/vkc-kiosk/` |
| `url` | Skriv ut lokal kiosk-URL |
| `setup-reader` | **YAROGNTEC/SDZNKJLTD** systemfix (sudo + reboot) |
| `configure-reader` | Välj läsare + kortformat → skriver `config.json` |
| `slides` | Karusell: lägg till/ta bort URL, ordning, tid, refresh (`karusell` = alias) |

Exempel:

```bash
vkc-kiosk status
vkc-kiosk slides
vkc-kiosk pull
sudo vkc-kiosk setup-reader          # endast YAROGNTEC
vkc-kiosk configure-reader
```

WiFi hanteras via skrivbordets nätverks-GUI / nyckelring — inte av `vkc-kiosk`.

Full steglista och felsökning: [INSTALLATION.md](INSTALLATION.md).

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
