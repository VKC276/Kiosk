# Cloudflare Worker — VKC incheckning

Kiosk-UI + D1-databas + check-in-API på Cloudflare. Raspberry Pi kör bara
`agent.py` (kortläsare) och Chromium mot den här Workern.

## En gång

```bash
cd cloudflare
npm install
npx wrangler login
npx wrangler d1 create vkc-kiosk
```

Kopiera `database_id` från kommandot till `wrangler.jsonc`.

```bash
cp .dev.vars.example .dev.vars   # lokala tokens
npx wrangler d1 migrations apply vkc-kiosk --local
npx wrangler d1 migrations apply vkc-kiosk --remote
npx wrangler secret put KIOSK_TOKEN
npx wrangler secret put ADMIN_TOKEN
npx wrangler deploy
```

Samma `KIOSK_TOKEN` ska stå i Pi:ns `config.json` under `CLOUDFLARE.token`.
`ADMIN_TOKEN` används bara för import och karusell-publicering.

## Importera från Google Apps Script

På en dator med de gamla GAS-URL:erna (kan vara Pi:n):

```bash
./venv/bin/python scripts/import-from-gas.py \
  --api-url https://vkc-kiosk.<ditt-konto>.workers.dev \
  --admin-token "$ADMIN_TOKEN"
```

Scriptet läser `DATA_URL` och `TEN_VISIT_DATA_URL` från `config.json` om de finns.

## Lokalt

```bash
cd cloudflare
npm test
npx wrangler d1 migrations apply vkc-kiosk --local
npx wrangler dev
```

Simulera ett blipp:

```bash
curl -sS -X POST http://127.0.0.1:8787/api/checkin \
  -H "Authorization: Bearer dev-kiosk-token" \
  -H "Content-Type: application/json" \
  -d '{"card_id":"1443137877","kiosk_id":"reception"}'
```

## API

| Metod | Sökväg | Auth | Syfte |
|-------|--------|------|--------|
| GET | `/healthz` | nej | `{ ok: true }` (ingen D1-fråga) |
| GET | `/api/kiosk/config?kiosk=` | nej | slides + timeouts (1 rad) |
| GET | `/api/kiosk/ws?kiosk=` | nej | WebSocket till skärmen |
| POST | `/api/checkin/reading` | KIOSK | blå "Läser kort…" (ingen D1) |
| POST | `/api/checkin` | KIOSK | 1 rad läst; 10-kort skriver 1 rad |
| POST | `/api/admin/import/members` | ADMIN | GAS-format JSON-lista |
| POST | `/api/admin/import/tencards` | ADMIN | GAS-format JSON-lista |
| PUT | `/api/admin/kiosk/config` | ADMIN | karusell |
| GET | `/api/admin/lookup/<id>` | ADMIN | felsök kort (1 rad) |
| GET | `/api/admin/stats` | ADMIN | räknare i `meta` (2 rader) |

## D1-rader (~50 kort)

D1 tar betalt per **läst/skriven rad**, inte per kort i klubben. 50 kort i en tabell med primärnyckel är en rad per blipp.

| Händelse | Läs | Skriv |
|----------|-----|--------|
| Medlemsblipp | 1 (`cards` via `card_id`) | 0 |
| 10-kortsklipp | 1 | 1 (`remaining - 1`) |
| Okänt kort | 1 (miss) | 0 |
| `GET /healthz` (Pi pollar vid boot) | 0 | 0 |
| Kiosk-sidan laddas | 1 (`kiosk_config`) | 0 |
| Import om listan är oförändrad | ~0 extra writes (`WHERE` hoppar över lika rader) | |

Incheckningar loggas med `console.log` (Workers-loggar), inte som extra D1-rader. Återimportera GAS bara när listan faktiskt ändrats.
