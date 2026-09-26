import { CLIP_DEBOUNCE_SECONDS, isRecentlyClipped } from "./clip-policy";
import type { CardRow, CardStore, ClipResult } from "./types";

export function d1CardStore(db: D1Database): CardStore {
  return {
    async getCard(cardId: string): Promise<CardRow | null> {
      const row = await db
        .prepare(
          `SELECT card_id, kind, name, status, expires_at, remaining, last_clipped_at
           FROM cards WHERE card_id = ?`,
        )
        .bind(cardId)
        .first<CardRow>();
      return row ?? null;
    },

    async clipTencard(
      cardId: string,
      debounceSeconds: number = CLIP_DEBOUNCE_SECONDS,
    ): Promise<ClipResult> {
      const debounce = Math.max(1, Math.trunc(debounceSeconds));
      // Atomiskt: klipp bara om remaining > 0 och inte nyligen klippt.
      const row = await db
        .prepare(
          `UPDATE cards
           SET remaining = remaining - 1,
               last_clipped_at = datetime('now'),
               status = CASE WHEN remaining - 1 <= 0 THEN 'Inga besök kvar' ELSE 'Aktivt' END,
               updated_at = datetime('now')
           WHERE card_id = ?
             AND kind = 'tencard'
             AND remaining > 0
             AND (
               last_clipped_at IS NULL
               OR last_clipped_at = ''
               OR last_clipped_at < datetime('now', ?)
             )
           RETURNING remaining, name, status`,
        )
        .bind(cardId, `-${debounce} seconds`)
        .first<{ remaining: number; name: string }>();

      if (row) {
        return { remaining: Number(row.remaining), name: row.name || "" };
      }

      const existing = await db
        .prepare(
          `SELECT kind, remaining, name, last_clipped_at
           FROM cards WHERE card_id = ?`,
        )
        .bind(cardId)
        .first<{
          kind: string;
          remaining: number | null;
          name: string | null;
          last_clipped_at: string | null;
        }>();

      if (!existing || existing.kind !== "tencard") return "missing";

      const remaining = Number(existing.remaining) || 0;
      if (remaining <= 0) return "exhausted";

      // Debounce-träff eller race: visa senaste lyckade klippet utan ny decrement.
      if (isRecentlyClipped(existing.last_clipped_at, debounce)) {
        return {
          remaining,
          name: existing.name || "",
          replay: true,
        };
      }

      return "exhausted";
    },
  };
}
