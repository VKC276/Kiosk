import type { CardRow, CardStore } from "./types";

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

    async clipTencard(cardId: string) {
      const existing = await db
        .prepare(`SELECT kind, remaining FROM cards WHERE card_id = ?`)
        .bind(cardId)
        .first<{ kind: string; remaining: number | null }>();
      if (!existing || existing.kind !== "tencard") return "missing";
      if (!(Number(existing.remaining) > 0)) return "exhausted";

      const row = await db
        .prepare(
          `UPDATE cards
           SET remaining = remaining - 1,
               last_clipped_at = datetime('now'),
               status = CASE WHEN remaining - 1 <= 0 THEN 'Inga besök kvar' ELSE 'Aktivt' END,
               updated_at = datetime('now')
           WHERE card_id = ? AND kind = 'tencard' AND remaining > 0
           RETURNING remaining, name, status`,
        )
        .bind(cardId)
        .first<{ remaining: number; name: string }>();

      if (row) {
        return { remaining: Number(row.remaining), name: row.name || "" };
      }
      return "exhausted";
    },
  };
}
