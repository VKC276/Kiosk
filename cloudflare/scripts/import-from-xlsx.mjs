#!/usr/bin/env node
/**
 * Import 10-kort.xlsx into the Worker (HTTP) or print SQL for D1.
 * Windows/Node — no Python required.
 *
 *   node scripts/import-from-xlsx.mjs "..\CurrentDataSet\Förteckning 10-kort.xlsx" --sql
 *   node scripts/import-from-xlsx.mjs "file.xlsx" --api-url https://vkc-kiosk....workers.dev --admin-token TOKEN
 */
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import * as XLSX from "xlsx";

function arg(name, fallback = "") {
  const i = process.argv.indexOf(name);
  if (i === -1) return fallback;
  return process.argv[i + 1] || fallback;
}

function sqlQuote(value) {
  return `'${String(value).replace(/'/g, "''")}'`;
}

function sqlString(value, { emptyAsNull = true } = {}) {
  if (value == null) return "NULL";
  if (value === "" && emptyAsNull) return "NULL";
  return sqlQuote(value);
}

function formatDate(value) {
  if (value == null || value === "") return null;
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())} ${pad(value.getHours())}:${pad(value.getMinutes())}:${pad(value.getSeconds())}`;
  }
  const text = String(value).trim();
  return text || null;
}

function normalizeCardNumber(value) {
  if (value == null || typeof value === "boolean") return "";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "";
    if (Number.isInteger(value)) return String(value);
    if (Number.isInteger(Math.round(value)) && Math.abs(value - Math.round(value)) < 1e-9) {
      return String(Math.round(value));
    }
    return String(value).trim();
  }
  let text = String(value).trim().replace(/ /g, "");
  if (!text) return "";
  const asFloat = Number(text);
  if (Number.isFinite(asFloat) && Number.isInteger(asFloat)) return String(asFloat);
  if (text.endsWith(".0") && /^\d+\.0$/.test(text)) return text.slice(0, -2);
  return text;
}

function pick(row, keys) {
  for (const key of keys) {
    if (row[key] !== undefined && row[key] !== null && row[key] !== "") return row[key];
  }
  const lower = Object.fromEntries(Object.entries(row).map(([k, v]) => [k.toLowerCase(), v]));
  for (const key of keys) {
    const hit = lower[key.toLowerCase()];
    if (hit !== undefined && hit !== null && hit !== "") return hit;
  }
  return undefined;
}

function rowsFromXlsx(path) {
  const wb = XLSX.read(readFileSync(path), { type: "buffer", cellDates: true });
  const sheetName = wb.SheetNames.find((n) => /klippkort/i.test(n)) || wb.SheetNames[0];
  const sheet = wb.Sheets[sheetName];
  const rows = XLSX.utils.sheet_to_json(sheet, { defval: "", raw: true });
  return { sheetName, rows };
}

function mapTencard(row) {
  const cardId = normalizeCardNumber(pick(row, ["Kortnummer", "card_id", "kortnummer"]));
  if (!cardId) return null;
  const remainingRaw = pick(row, ["Antal kvarvarande besök", "remaining", "klipp_kvar"]);
  const remaining = Number(remainingRaw);
  const remainingInt = Number.isFinite(remaining) ? Math.max(0, Math.trunc(remaining)) : 0;
  const statusRaw = String(pick(row, ["Status", "status"]) || "").trim();
  return {
    card_id: cardId,
    name: String(pick(row, ["Namn", "name"]) || "").trim(),
    remaining: remainingInt,
    status: statusRaw || (remainingInt > 0 ? "Aktivt" : "Inga besök kvar"),
    last_clipped_at: formatDate(pick(row, ["Senast klippt", "last_clipped_at", "lastClipped"])),
  };
}

const xlsxPath = resolve(process.argv[2] || "");
if (!xlsxPath || process.argv[2]?.startsWith("-")) {
  console.error("Ange sökväg till .xlsx som första argument.");
  process.exit(1);
}

const { sheetName, rows } = rowsFromXlsx(xlsxPath);
const mapped = rows.map(mapTencard).filter(Boolean);
console.error(`Läste ${mapped.length} 10-kort från ${xlsxPath} (blad ${sheetName})`);

const wantSql = process.argv.includes("--sql");
const sqlOut = arg("--sql-file");
const apiUrl = (arg("--api-url") || process.env.API_URL || "").replace(/\/$/, "");
const adminToken = arg("--admin-token") || process.env.ADMIN_TOKEN || "";

if (wantSql || sqlOut) {
  const stmts = mapped.map((c) => {
    return `INSERT INTO cards (card_id, kind, name, status, expires_at, remaining, last_clipped_at, updated_at)
VALUES (${sqlString(c.card_id)}, 'tencard', ${sqlString(c.name, { emptyAsNull: false })}, ${sqlString(c.status, { emptyAsNull: false })}, NULL, ${c.remaining}, ${sqlString(c.last_clipped_at)}, datetime('now'))
ON CONFLICT(card_id) DO UPDATE SET
  kind = 'tencard',
  name = excluded.name,
  remaining = excluded.remaining,
  status = excluded.status,
  expires_at = NULL,
  last_clipped_at = excluded.last_clipped_at,
  updated_at = datetime('now');`;
  });
  stmts.push(
    `INSERT INTO meta (key, value) VALUES ('tencards', ${mapped.length})
ON CONFLICT(key) DO UPDATE SET value = excluded.value;`,
  );
  const sql = stmts.join("\n");
  if (sqlOut) writeFileSync(sqlOut, sql, "utf8");
  else process.stdout.write(sql);
  process.exit(0);
}

if (!apiUrl || !adminToken) {
  console.error("Saknar --api-url och --admin-token (eller kör med --sql / --sql-file).");
  process.exit(1);
}

const response = await fetch(`${apiUrl}/api/admin/import/tencards`, {
  method: "POST",
  headers: {
    Authorization: `Bearer ${adminToken}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify(mapped),
});
const text = await response.text();
if (!response.ok) {
  console.error(`Importfel: HTTP ${response.status} ${text.slice(0, 300)}`);
  process.exit(1);
}
console.log(text);
