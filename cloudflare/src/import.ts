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

export function tencardFromGas(row: GasTencard): {
  card_id: string;
  name: string;
  remaining: number;
  status: string;
  last_clipped_at: string | null;
} | null {
  const cardId = normalizeCardNumber(pick(row, ["Kortnummer", "card_id", "kortnummer"]));
  if (!cardId) return null;
  const remainingRaw = pick(row, ["Antal kvarvarande besök", "remaining", "klipp_kvar"]);
  const remaining = Number(remainingRaw);
  const lastRaw = pick(row, ["Senast klippt", "last_clipped_at", "lastClipped"]);
  let last_clipped_at: string | null = null;
  if (lastRaw instanceof Date) {
    last_clipped_at = lastRaw.toISOString().replace("T", " ").slice(0, 19);
  } else if (lastRaw != null && String(lastRaw).trim()) {
    last_clipped_at = String(lastRaw).trim();
  }
  const remainingInt = Number.isFinite(remaining) ? Math.max(0, Math.trunc(remaining)) : 0;
  const statusRaw = String(pick(row, ["Status", "status"]) || "").trim();
  return {
    card_id: cardId,
    name: String(pick(row, ["Namn", "name"]) || "").trim(),
    remaining: remainingInt,
    status: statusRaw || (remainingInt > 0 ? "Aktivt" : "Inga besök kvar"),
    last_clipped_at,
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
          `INSERT INTO cards (card_id, kind, name, status, expires_at, remaining, last_clipped_at, updated_at)
           VALUES (?, 'tencard', ?, ?, NULL, ?, ?, datetime('now'))
           ON CONFLICT(card_id) DO UPDATE SET
             kind = 'tencard',
             name = excluded.name,
             remaining = excluded.remaining,
             status = excluded.status,
             expires_at = NULL,
             last_clipped_at = excluded.last_clipped_at,
             updated_at = datetime('now')
           WHERE cards.kind IS NOT 'tencard'
             OR cards.name IS NOT excluded.name
             OR cards.remaining IS NOT excluded.remaining
             OR cards.status IS NOT excluded.status
             OR cards.last_clipped_at IS NOT excluded.last_clipped_at`,
        )
        .bind(
          mapped.card_id,
          mapped.name,
          mapped.status,
          mapped.remaining,
          mapped.last_clipped_at,
        ),
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

export async function listTencards(db: D1Database) {
  const result = await db
    .prepare(
      `SELECT card_id, remaining, status, last_clipped_at, name
       FROM cards WHERE kind = 'tencard' ORDER BY card_id`,
    )
    .all<{
      card_id: string;
      remaining: number | null;
      status: string;
      last_clipped_at: string | null;
      name: string;
    }>();
  return result.results || [];
}

export async function saveTencard(
  db: D1Database,
  input: {
    card_id: string;
    remaining: number;
    status?: string;
    last_clipped_at?: string | null;
    name?: string;
  },
): Promise<{ ok: true } | { ok: false; error: string; status: number }> {
  const remaining = Math.max(0, Math.trunc(Number(input.remaining)));
  if (!Number.isFinite(remaining)) {
    return { ok: false, error: "remaining required", status: 400 };
  }
  const existing = await db
    .prepare(`SELECT kind FROM cards WHERE card_id = ?`)
    .bind(input.card_id)
    .first<{ kind: string }>();
  if (existing && existing.kind !== "tencard") {
    return { ok: false, error: "card_id is not a 10-kort", status: 409 };
  }
  const status = (input.status || (remaining > 0 ? "Aktivt" : "Inga besök kvar")).trim();
  await db
    .prepare(
      `INSERT INTO cards (card_id, kind, name, status, remaining, last_clipped_at, updated_at)
       VALUES (?, 'tencard', ?, ?, ?, ?, datetime('now'))
       ON CONFLICT(card_id) DO UPDATE SET
         kind = 'tencard',
         name = excluded.name,
         status = excluded.status,
         remaining = excluded.remaining,
         last_clipped_at = COALESCE(excluded.last_clipped_at, cards.last_clipped_at),
         updated_at = datetime('now')`,
    )
    .bind(
      input.card_id,
      input.name || "",
      status,
      remaining,
      input.last_clipped_at ?? null,
    )
    .run();
  return { ok: true };
}

export async function deleteTencard(db: D1Database, cardId: string) {
  const existing = await db
    .prepare(`SELECT kind FROM cards WHERE card_id = ?`)
    .bind(cardId)
    .first<{ kind: string }>();
  if (!existing || existing.kind !== "tencard") {
    return { deleted: false, reason: existing ? "not_tencard" : "not_found" as const };
  }
  await db.prepare(`DELETE FROM cards WHERE card_id = ? AND kind = 'tencard'`).bind(cardId).run();
  return { deleted: true as const };
}
