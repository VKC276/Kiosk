import { normalizeCardNumber } from "./checkin";
import type { KioskConfig } from "./types";

type GasMember = Record<string, unknown>;
type GasTencard = Record<string, unknown>;

function pick(row: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) {
    if (row[key] !== undefined && row[key] !== null && row[key] !== "") {
      return row[key];
    }
  }
  const lower = Object.fromEntries(
    Object.entries(row).map(([k, v]) => [k.toLowerCase(), v]),
  );
  for (const key of keys) {
    const hit = lower[key.toLowerCase()];
    if (hit !== undefined && hit !== null && hit !== "") return hit;
  }
  return undefined;
}

export function memberFromGas(row: GasMember): { card_id: string; name: string; status: string; expires_at: string | null } | null {
  const cardId = normalizeCardNumber(pick(row, ["Kortnummer", "card_id", "kortnummer"]));
  if (!cardId) return null;
  return {
    card_id: cardId,
    name: String(pick(row, ["Namn", "name"]) || "").trim(),
    status: String(pick(row, ["Status", "status"]) || "").trim(),
    expires_at: pick(row, ["Giltigt till och med", "expires_at", "expiry"]) != null
      ? String(pick(row, ["Giltigt till och med", "expires_at", "expiry"]))
      : null,
  };
}

export function tencardFromGas(row: GasTencard): { card_id: string; name: string; remaining: number } | null {
  const cardId = normalizeCardNumber(pick(row, ["Kortnummer", "card_id", "kortnummer"]));
  if (!cardId) return null;
  const remainingRaw = pick(row, ["Antal kvarvarande besök", "remaining", "klipp_kvar"]);
  const remaining = Number(remainingRaw);
  return {
    card_id: cardId,
    name: String(pick(row, ["Namn", "name"]) || "").trim(),
    remaining: Number.isFinite(remaining) ? Math.max(0, Math.trunc(remaining)) : 0,
  };
}

export async function upsertMembers(db: D1Database, rows: GasMember[]): Promise<{ upserted: number; skipped: number }> {
  let upserted = 0;
  let skipped = 0;
  const stmts: D1PreparedStatement[] = [];
  for (const row of rows) {
    const mapped = memberFromGas(row);
    if (!mapped) {
      skipped += 1;
      continue;
    }
    stmts.push(
      db
        .prepare(
          `INSERT INTO cards (card_id, kind, name, status, expires_at, remaining, updated_at)
           VALUES (?, 'member', ?, ?, ?, NULL, datetime('now'))
           ON CONFLICT(card_id) DO UPDATE SET
             name = excluded.name,
             status = excluded.status,
             expires_at = excluded.expires_at,
             updated_at = datetime('now')
           WHERE cards.kind = 'member'
             AND (
               cards.name IS NOT excluded.name
               OR cards.status IS NOT excluded.status
               OR cards.expires_at IS NOT excluded.expires_at
             )`,
        )
        .bind(mapped.card_id, mapped.name, mapped.status, mapped.expires_at),
    );
    upserted += 1;
  }
  await runChunks(db, stmts);
  await setMeta(db, "members", upserted);
  return { upserted, skipped };
}

export async function upsertTencards(db: D1Database, rows: GasTencard[]): Promise<{ upserted: number; skipped: number }> {
  let upserted = 0;
  let skipped = 0;
  const stmts: D1PreparedStatement[] = [];
  for (const row of rows) {
    const mapped = tencardFromGas(row);
    if (!mapped) {
      skipped += 1;
      continue;
    }
    stmts.push(
      db
        .prepare(
          `INSERT INTO cards (card_id, kind, name, status, expires_at, remaining, updated_at)
           VALUES (?, 'tencard', ?, '', NULL, ?, datetime('now'))
           ON CONFLICT(card_id) DO UPDATE SET
             kind = 'tencard',
             name = excluded.name,
             remaining = excluded.remaining,
             status = '',
             expires_at = NULL,
             updated_at = datetime('now')
           WHERE cards.kind IS NOT 'tencard'
             OR cards.name IS NOT excluded.name
             OR cards.remaining IS NOT excluded.remaining`,
        )
        .bind(mapped.card_id, mapped.name, mapped.remaining),
    );
    upserted += 1;
  }
  await runChunks(db, stmts);
  await setMeta(db, "tencards", upserted);
  return { upserted, skipped };
}

async function setMeta(db: D1Database, key: string, value: number): Promise<void> {
  await db
    .prepare(
      `INSERT INTO meta (key, value) VALUES (?, ?)
       ON CONFLICT(key) DO UPDATE SET value = excluded.value
       WHERE meta.value IS NOT excluded.value`,
    )
    .bind(key, value)
    .run();
}

async function runChunks(db: D1Database, stmts: D1PreparedStatement[]): Promise<void> {
  const size = 50;
  for (let i = 0; i < stmts.length; i += size) {
    await db.batch(stmts.slice(i, i + size));
  }
}

export async function loadKioskConfig(db: D1Database, kioskId: string): Promise<KioskConfig> {
  const row = await db
    .prepare(
      `SELECT kiosk_id, slides_json, checkin_enabled, checkin_height_percent,
              reload_on_show, reload_interval_seconds, status_display_seconds,
              last_clip_ok_seconds, last_clip_return_seconds
       FROM kiosk_config WHERE kiosk_id = ?`,
    )
    .bind(kioskId)
    .first<{
      kiosk_id: string;
      slides_json: string;
      checkin_enabled: number;
      checkin_height_percent: number;
      reload_on_show: number;
      reload_interval_seconds: number;
      status_display_seconds: number;
      last_clip_ok_seconds: number;
      last_clip_return_seconds: number;
    }>();

  if (!row) {
    return {
      kiosk_id: kioskId,
      slides: [],
      checkin_enabled: true,
      checkin_height_percent: 20,
      reload_on_show: false,
      reload_interval_seconds: 300,
      status_display_seconds: 3,
      last_clip_ok_seconds: 3,
      last_clip_return_seconds: 5,
    };
  }

  let slides: unknown[] = [];
  try {
    const parsed = JSON.parse(row.slides_json || "[]");
    slides = Array.isArray(parsed) ? parsed : [];
  } catch {
    slides = [];
  }

  return {
    kiosk_id: row.kiosk_id,
    slides,
    checkin_enabled: Boolean(row.checkin_enabled),
    checkin_height_percent: Number(row.checkin_height_percent) || 20,
    reload_on_show: Boolean(row.reload_on_show),
    reload_interval_seconds: Number(row.reload_interval_seconds) || 300,
    status_display_seconds: Number(row.status_display_seconds) || 3,
    last_clip_ok_seconds: Number(row.last_clip_ok_seconds) || 3,
    last_clip_return_seconds: Number(row.last_clip_return_seconds) || 5,
  };
}

export async function saveKioskConfig(db: D1Database, cfg: KioskConfig): Promise<void> {
  await db
    .prepare(
      `INSERT INTO kiosk_config (
         kiosk_id, slides_json, checkin_enabled, checkin_height_percent,
         reload_on_show, reload_interval_seconds, status_display_seconds,
         last_clip_ok_seconds, last_clip_return_seconds, updated_at
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
       ON CONFLICT(kiosk_id) DO UPDATE SET
         slides_json = excluded.slides_json,
         checkin_enabled = excluded.checkin_enabled,
         checkin_height_percent = excluded.checkin_height_percent,
         reload_on_show = excluded.reload_on_show,
         reload_interval_seconds = excluded.reload_interval_seconds,
         status_display_seconds = excluded.status_display_seconds,
         last_clip_ok_seconds = excluded.last_clip_ok_seconds,
         last_clip_return_seconds = excluded.last_clip_return_seconds,
         updated_at = datetime('now')`,
    )
    .bind(
      cfg.kiosk_id,
      JSON.stringify(cfg.slides ?? []),
      cfg.checkin_enabled ? 1 : 0,
      cfg.checkin_height_percent,
      cfg.reload_on_show ? 1 : 0,
      cfg.reload_interval_seconds,
      cfg.status_display_seconds,
      cfg.last_clip_ok_seconds,
      cfg.last_clip_return_seconds,
    )
    .run();
}
