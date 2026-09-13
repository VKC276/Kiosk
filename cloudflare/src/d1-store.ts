import type { CardRow, CardStore } from "./types";

export function d1CardStore(db: D1Database): CardStore {
  return {
    async getCard(cardId: string): Promise<CardRow | null> {
      const row = await db
        .prepare(
          `SELECT card_id, kind, name, status, expires_at, remaining
           FROM cards WHERE card_id = ?`,
        )
        .bind(cardId)
        .first<CardRow>();
      return row ?? null;
    },

    async clipTencard(cardId: string) {
      const row = await db
        .prepare(
          `UPDATE cards
           SET remaining = remaining - 1, updated_at = datetime('now')
           WHERE card_id = ? AND kind = 'tencard' AND remaining > 0
           RETURNING remaining, name`,
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
