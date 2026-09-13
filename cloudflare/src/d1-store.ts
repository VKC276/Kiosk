import type { CardStore, MemberRow, TencardRow } from "./types";

export function d1CardStore(db: D1Database): CardStore {
  return {
    async getTencard(cardId: string): Promise<TencardRow | null> {
      const row = await db
        .prepare("SELECT card_id, name, remaining FROM tencards WHERE card_id = ?")
        .bind(cardId)
        .first<TencardRow>();
      return row ?? null;
    },

    async getMember(cardId: string): Promise<MemberRow | null> {
      const row = await db
        .prepare("SELECT card_id, name, status, expires_at FROM members WHERE card_id = ?")
        .bind(cardId)
        .first<MemberRow>();
      return row ?? null;
    },

    async clipTencard(cardId: string) {
      const row = await db
        .prepare(
          `UPDATE tencards
           SET remaining = remaining - 1, updated_at = datetime('now')
           WHERE card_id = ? AND remaining > 0
           RETURNING remaining, name`,
        )
        .bind(cardId)
        .first<{ remaining: number; name: string }>();

      if (row) {
        return { remaining: Number(row.remaining), name: row.name || "" };
      }

      const existing = await db
        .prepare("SELECT remaining FROM tencards WHERE card_id = ?")
        .bind(cardId)
        .first<{ remaining: number }>();
      if (!existing) return "missing";
      return "exhausted";
    },

    async logCheckin(entry) {
      await db
        .prepare(
          "INSERT INTO checkin_logs (card_id, kind, status, kiosk_id) VALUES (?, ?, ?, ?)",
        )
        .bind(entry.cardId, entry.kind, entry.status, entry.kioskId)
        .run();
    },
  };
}
