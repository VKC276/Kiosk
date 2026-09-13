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
| GET | `/healthz` | nej | antal medlemmar/10-kort |
| GET | `/api/kiosk/config?kiosk=` | nej | slides + timeouts |
| GET | `/api/kiosk/ws?kiosk=` | nej | WebSocket till skärmen |
| POST | `/api/checkin/reading` | KIOSK | blå "Läser kort…" |
| POST | `/api/checkin` | KIOSK | uppslag + 10-kortsklipp + logg |
| POST | `/api/admin/import/members` | ADMIN | GAS-format JSON-lista |
| POST | `/api/admin/import/tencards` | ADMIN | GAS-format JSON-lista |
| PUT | `/api/admin/kiosk/config` | ADMIN | karusell |
| GET | `/api/admin/lookup/<id>` | ADMIN | felsök kort |
| GET | `/api/admin/stats` | ADMIN | räkningar |

Incheckning är ett D1-uppslag (millisekunder) i stället för Google Apps Script.
10-kort minskas atomärt med `UPDATE … WHERE remaining > 0 RETURNING`.
