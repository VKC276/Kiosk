import { describe, expect, it } from "vitest";
import {
  clipSuccessStatus,
  displayName,
  mapMemberStatus,
  memberStatus,
  normalizeCardNumber,
  performCheckin,
  tencardStatus,
} from "../src/checkin";
import type { CardRow, CardStore, MemberRow, TencardRow } from "../src/types";
import { memberFromGas, tencardFromGas } from "../src/import";

function memoryStore(opts: {
  members?: MemberRow[];
  tencards?: TencardRow[];
}): CardStore {
  const members = new Map((opts.members || []).map((m) => [m.card_id, { ...m }]));
  const tencards = new Map((opts.tencards || []).map((t) => [t.card_id, { ...t }]));
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
    async clipTencard(id) {
      const row = tencards.get(id);
      if (!row) return "missing";
      if (row.remaining <= 0) return "exhausted";
      row.remaining -= 1;
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
      }),
    ).toEqual({
      card_id: "99",
      name: "Klippkorts-användare",
      remaining: 8,
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
    expect(status.secondary_message).toBe("");
  });
});
