import { describe, expect, it } from "vitest";
import {
  checkinErrorStatus,
  clipSuccessStatus,
  displayName,
  lookupCard,
  mapMemberStatus,
  memberStatus,
  normalizeCardNumber,
  performCheckin,
  tencardStatus,
} from "../src/checkin";
import { CLIP_DEBOUNCE_SECONDS, isRecentlyClipped } from "../src/clip-policy";
import type { CardRow, CardStore, MemberRow, TencardRow } from "../src/types";
import { memberFromGas, tencardFromGas } from "../src/import";

function utcNowSql(): string {
  return new Date().toISOString().replace("T", " ").slice(0, 19);
}

function memoryStore(opts: {
  members?: MemberRow[];
  tencards?: TencardRow[];
}): CardStore {
  const members = new Map((opts.members || []).map((m) => [m.card_id, { ...m }]));
  const tencards = new Map(
    (opts.tencards || []).map((t) => [t.card_id, { ...t, last_clipped_at: t.last_clipped_at ?? null }]),
  );
  return {
    async getCard(id): Promise<CardRow | null> {
      const tencard = tencards.get(id);
      if (tencard) {
        return {
          card_id: tencard.card_id,
          kind: "tencard",
          name: tencard.name,
          status: "",
          expires_at: null,
          remaining: tencard.remaining,
          last_clipped_at: tencard.last_clipped_at ?? null,
        };
      }
      const member = members.get(id);
      if (member) {
        return {
          card_id: member.card_id,
          kind: "member",
          name: member.name,
          status: member.status,
          expires_at: member.expires_at,
          remaining: null,
        };
      }
      return null;
    },
    async clipTencard(id, debounceSeconds = CLIP_DEBOUNCE_SECONDS) {
      const row = tencards.get(id);
      if (!row) return "missing";
      if (row.remaining <= 0) return "exhausted";
      if (isRecentlyClipped(row.last_clipped_at, debounceSeconds)) {
        return { remaining: row.remaining, name: row.name, replay: true };
      }
      row.remaining -= 1;
      row.last_clipped_at = utcNowSql();
      return { remaining: row.remaining, name: row.name };
    },
  };
}

describe("normalizeCardNumber", () => {
  it("strips sheet floats", () => {
    expect(normalizeCardNumber("1443137877.0")).toBe("1443137877");
    expect(normalizeCardNumber(1443137877)).toBe("1443137877");
  });
});

describe("displayName", () => {
  it("hides placeholder 10-kort names", () => {
    expect(displayName("Klippkorts-användare")).toBe("");
    expect(displayName("Anna")).toBe("Anna");
  });
});

describe("mapMemberStatus", () => {
  it("maps Swedish sheet statuses", () => {
    expect(mapMemberStatus("Aktivt").translated).toBe("ACTIVE");
    expect(mapMemberStatus("Går snart ut").translated).toBe("EXPIRING_SOON");
    expect(mapMemberStatus("Utgånget").translated).toBe("EXPIRED");
  });
});

describe("performCheckin", () => {
  it("clips a 10-kort atomically", async () => {
    const store = memoryStore({
      tencards: [{ card_id: "111", name: "Anna", remaining: 3 }],
    });
    const status = await performCheckin(store, "111", "reception");
    expect(status.status).toBe("TENCARD_CLIPPED_OK");
    expect(status.message).toContain("2 klipp kvar");
  });

  it("uses last-clip status at 1 remaining", async () => {
    const store = memoryStore({
      tencards: [{ card_id: "111", name: "", remaining: 1 }],
    });
    const status = await performCheckin(store, "111", "reception");
    expect(status.status).toBe("TENCARD_CLIPPED_LAST");
    expect(clipSuccessStatus("111", 0, "").status_color).toBe("orange");
  });

  it("prefers 10-kort over member cards", async () => {
    const store = memoryStore({
      tencards: [{ card_id: "111", name: "", remaining: 0 }],
      members: [{ card_id: "111", name: "Bo", status: "Aktivt", expires_at: null }],
    });
    const status = await performCheckin(store, "111", "reception");
    expect(status.type).toBe("TENCARD");
    expect(status.status).toBe("TENCARD_EXHAUSTED");
  });

  it("welcomes active members without extra writes", async () => {
    const store = memoryStore({
      members: [{ card_id: "222", name: "Bo", status: "Aktivt", expires_at: "2027-01-01" }],
    });
    const status = await performCheckin(store, "222", "reception");
    expect(status.status).toBe("ACTIVE");
    expect(memberStatus({ card_id: "222", name: "Bo", status: "Aktivt", expires_at: null }).status).toBe("ACTIVE");
  });

  it("returns expired members without clipping", async () => {
    const store = memoryStore({
      members: [{ card_id: "222", name: "Bo", status: "Utgånget", expires_at: null }],
    });
    const status = await performCheckin(store, "222", "reception");
    expect(status.status).toBe("EXPIRED");
  });

  it("returns not found", async () => {
    const store = memoryStore({});
    const status = await performCheckin(store, "999", "reception");
    expect(status.status).toBe("NOT_FOUND");
  });
});

describe("GAS import mapping", () => {
  it("maps member rows", () => {
    expect(
      memberFromGas({
        Kortnummer: "1443137877.0",
        Namn: "Test",
        Status: "Aktivt",
        "Giltigt till och med": "2026-12-31",
      }),
    ).toEqual({
      card_id: "1443137877",
      name: "Test",
      status: "Aktivt",
      expires_at: "2026-12-31",
    });
  });

  it("maps tencard rows", () => {
    expect(
      tencardFromGas({
        Kortnummer: 99,
        Namn: "Klippkorts-användare",
        "Antal kvarvarande besök": 8,
        Status: "Aktivt",
        "Senast klippt": "2026-07-23 16:44:45",
      }),
    ).toEqual({
      card_id: "99",
      name: "Klippkorts-användare",
      remaining: 8,
      status: "Aktivt",
      last_clipped_at: "2026-07-23 16:44:45",
    });
  });
});

describe("tencardStatus", () => {
  it("omits anonymous welcome", () => {
    const status = tencardStatus({
      card_id: "1",
      name: "Klippkorts-användare",
      remaining: 4,
    });
    expect(status.secondary_message).toBe("Tryck på knappen för att klippa.");
  });
});

describe("checkinErrorStatus", () => {
  it("builds orange UI status for agent failures", () => {
    const status = checkinErrorStatus("Kunde inte kontakta servern.", "Försök igen.", "123");
    expect(status.status).toBe("CHECKIN_ERROR");
    expect(status.status_color).toBe("orange");
    expect(status.card_number_dec).toBe("123");
  });
});

describe("lookup vs clip", () => {
  it("lookup shows remaining without decrementing", async () => {
    const store = memoryStore({
      tencards: [{ card_id: "111", name: "Anna", remaining: 5 }],
    });
    const looked = await lookupCard(store, "111", "retail");
    expect(looked.status).toBe("TENCARD_READY");
    expect(looked.message).toContain("5 klipp kvar");
    const card = await store.getCard("111");
    expect(card?.remaining).toBe(5);
  });

  it("confirm clip decrements; second confirm also decrements (no debounce)", async () => {
    const store = memoryStore({
      tencards: [{ card_id: "111", name: "Anna", remaining: 5 }],
    });
    const first = await performCheckin(store, "111", "retail");
    expect(first.status).toBe("TENCARD_CLIPPED_OK");
    expect(first.message).toContain("4 klipp kvar");

    const second = await performCheckin(store, "111", "retail");
    expect(second.status).toBe("TENCARD_CLIPPED_OK");
    expect(second.message).toContain("3 klipp kvar");

    const card = await store.getCard("111");
    expect(card?.remaining).toBe(3);
  });

  it("isRecentlyClipped is off when debounce is 0", () => {
    const now = Date.parse("2026-09-26T12:00:00Z");
    expect(CLIP_DEBOUNCE_SECONDS).toBe(0);
    expect(isRecentlyClipped("2026-09-26 11:59:59", CLIP_DEBOUNCE_SECONDS, now)).toBe(false);
    expect(isRecentlyClipped("2026-09-26 11:59:57", 5, now)).toBe(true);
    expect(isRecentlyClipped(null, 5, now)).toBe(false);
  });
});
