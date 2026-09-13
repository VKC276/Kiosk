# Deploy Worker + D1 (utan Pi) — underlag för WallFlow

Pi:n kan vänta. Det som behövs nu är Workern, databasen och `ADMIN_TOKEN`,
så WallFlow kan lista/skapa/ändra 10-kort bakom rollerna **superadmin** och **hallvärd**.

Kör detta på en dator där ni är inloggade i Cloudflare (inte på kiosken).

## 1. Deploy

Från repo-roten, branch `cursor/cloudflare-kiosk-checkin-a077` (eller `main` när PR:en är mergad):

```bash
cd cloudflare
npm install
npx wrangler login
npx wrangler d1 create vkc-kiosk
```

Klistra in `database_id` i `wrangler.jsonc` (fältet som nu är nollor).

```bash
npx wrangler d1 migrations apply vkc-kiosk --remote
```

Skapa en lång slumpsträng till admin (spara i WallFlows server-miljö, inte i git):

```bash
openssl rand -hex 32
npx wrangler secret put ADMIN_TOKEN
# Klistra in samma värde
```

`KIOSK_TOKEN` kan ni sätta senare, när Pi:n ska börja klippa:

```bash
npx wrangler secret put KIOSK_TOKEN
npx wrangler deploy
```

URL blir typ `https://vkc-kiosk.<subdomain>.workers.dev`. Kolla med:

```bash
curl -sS https://vkc-kiosk.<subdomain>.workers.dev/healthz
# {"ok":true}
```

## 2. Fyll databasen

```bash
# från repo-roten
pip install openpyxl requests
python scripts/import-from-xlsx.py "Förteckning 10-kort.xlsx" \
  --api-url https://vkc-kiosk.<subdomain>.workers.dev \
  --admin-token "$ADMIN_TOKEN"
```

## 3. WallFlow ska anropa Workern **server-side**

Webbläsaren ska inte få `ADMIN_TOKEN`. WallFlow-backenden (som redan vet rollen) anropar Cloudflare.

Pseudokod:

```
om användare.roll inte i {superadmin, hallvärd}:
    403
annars:
    fetch(WORKER + "/api/admin/tencards", {
      headers: { Authorization: "Bearer " + ADMIN_TOKEN }
    })
```

## 4. API som UI:t behöver

Alla admin-anrop: header `Authorization: Bearer <ADMIN_TOKEN>`.

### Lista

`GET /api/admin/tencards`

```json
{
  "ok": true,
  "tencards": [
    {
      "card_id": "623662933",
      "remaining": 10,
      "status": "Aktivt",
      "last_clipped_at": "2025-12-23 12:27:34",
      "name": ""
    }
  ]
}
```

Fält motsvarar Excel: Kortnummer, Antal kvarvarande besök, Status, Senast klippt.

### Ett kort

`GET /api/admin/tencards/623662933`

```json
{
  "ok": true,
  "card": {
    "card_id": "623662933",
    "kind": "tencard",
    "remaining": 10,
    "status": "Aktivt",
    "last_clipped_at": "2025-12-23 12:27:34",
    "name": "",
    "expires_at": null
  }
}
```

404 om kortet saknas eller är medlemskort.

### Skapa eller uppdatera (nytt kort / sätt saldo till 10)

`POST /api/admin/tencards`

```json
{
  "card_id": "623662933",
  "remaining": 10,
  "status": "Aktivt",
  "name": ""
}
```

Svar: `{ "ok": true, "card_id": "...", "card": { ... } }`.

Om `status` utelämnas blir det `Aktivt` när `remaining > 0`, annars `Inga besök kvar`.
Kiosk-token kan **inte** anropa den här routen.

### Bulk från Excel-format

`POST /api/admin/import/tencards` med JSON-lista av rader
`{ "Kortnummer", "Antal kvarvarande besök", "Status", "Senast klippt" }`.

## 5. Verifiera innan ni bygger UI

```bash
export API=https://vkc-kiosk.<subdomain>.workers.dev
export ADMIN_TOKEN=...

curl -sS -H "Authorization: Bearer $ADMIN_TOKEN" "$API/api/admin/tencards" | head
curl -sS -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"card_id":"999000001","remaining":10,"status":"Aktivt"}' \
  "$API/api/admin/tencards"
```

Utan token ska ni få `401`.

## 6. Pi senare

När WallFlow-UI:t funkar: `vkc-kiosk pull` på Pi, fyll `CLOUDFLARE.token` med **KIOSK_TOKEN** (inte admin), sätt `enabled: true`. Kiosken får bara klippa, inte skapa kort.
