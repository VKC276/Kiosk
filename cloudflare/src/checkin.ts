import type { CardStore, CheckinStatus, MemberRow, TencardRow } from "./types";

const ANON_NAME_RE = /klippkort|användare|anvandare|^unknown$|^n\/a$/i;

export function normalizeCardNumber(value: unknown): string {
  if (value === null || value === undefined || typeof value === "boolean") {
    return "";
  }
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
  if (Number.isFinite(asFloat) && Number.isInteger(asFloat)) {
    return String(asFloat);
  }
  if (text.endsWith(".0") && /^\d+\.0$/.test(text)) {
    return text.slice(0, -2);
  }
  return text;
}

export function displayName(name: string | null | undefined): string {
  const n = (name || "").trim();
  if (!n || ANON_NAME_RE.test(n)) return "";
  return n;
}

export function mapMemberStatus(rawStatus: string): {
  translated: string;
  color: string;
  code: string;
} {
  const raw = (rawStatus || "Okänd Status").toUpperCase();
  if (raw.includes("AKTIVT")) {
    return { translated: "ACTIVE", color: "green", code: "#4CAF50" };
  }
  if (raw.includes("GÅR SNART UT")) {
    return { translated: "EXPIRING_SOON", color: "yellow", code: "#FFC107" };
  }
  if (raw.includes("INAKTIVT") || raw.includes("UTGÅNGET")) {
    return { translated: "EXPIRED", color: "red", code: "#F44336" };
  }
  return { translated: "EXPIRED", color: "gray", code: "#9E9E9E" };
}

export function tencardStatus(card: TencardRow): CheckinStatus {
  const memberName = displayName(card.name);
  const remaining = Number(card.remaining) || 0;
  if (remaining > 0) {
    return {
      type: "TENCARD",
      status: "TENCARD_READY",
      message: `10-kort OK: ${remaining} klipp kvar.`,
      secondary_message: memberName ? `Välkommen ${memberName}!` : "",
      status_color: "purple",
      color_code: "#9C27B0",
      card_number_dec: card.card_id,
      member_name: memberName,
      klipp_kvar_local: remaining,
    };
  }
  return {
    type: "TENCARD",
    status: "TENCARD_EXHAUSTED",
    message: "10-kort slut (0 klipp kvar).",
    secondary_message: "Vänligen lämna in kortet i receptionen",
    status_color: "red",
    color_code: "#F44336",
    card_number_dec: card.card_id,
    member_name: memberName,
    klipp_kvar_local: 0,
  };
}

export function memberStatus(card: MemberRow): CheckinStatus {
  const mapped = mapMemberStatus(card.status);
  const memberName = displayName(card.name) || card.name || "Okänt namn";
  return {
    type: "MEMBER",
    status: mapped.translated,
    message: `Välkommen ${memberName}!`,
    secondary_message: `Kortstatus: ${(card.status || "Okänd").toString()}`,
    status_color: mapped.color,
    color_code: mapped.code,
    card_number_dec: card.card_id,
    member_name: memberName,
    expiry_date: card.expires_at || "Saknas",
  };
}

export function notFoundStatus(cardId: string): CheckinStatus {
  return {
    type: "UNKNOWN",
    status: "NOT_FOUND",
    message: "Kortet hittades inte i systemet.",
    secondary_message: "Vänligen kontakta personal för registrering.",
    status_color: "red",
    color_code: "#F44336",
    card_number_dec: cardId,
    member_name: "Okänd/Ej registrerad",
    expiry_date: "",
  };
}

export function clipSuccessStatus(
  cardId: string,
  remaining: number,
  name: string,
): CheckinStatus {
  const memberName = displayName(name);
  if (remaining === 0) {
    return {
      type: "TENCARD",
      status: "TENCARD_CLIPPED_LAST",
      message: "Klipp OK!",
      secondary_message: "",
      status_color: "orange",
      color_code: "#FF9800",
      card_number_dec: cardId,
      member_name: memberName,
      klipp_kvar_local: 0,
    };
  }
  return {
    type: "TENCARD",
    status: "TENCARD_CLIPPED_OK",
    message: `Klipp OK! ${remaining} klipp kvar.`,
    secondary_message: memberName,
    status_color: "green",
    color_code: "#4CAF50",
    card_number_dec: cardId,
    member_name: memberName,
    klipp_kvar_local: remaining,
  };
}

export async function performCheckin(
  store: CardStore,
  rawCardId: unknown,
  kioskId: string,
): Promise<CheckinStatus> {
  const cardId = normalizeCardNumber(rawCardId);
  if (!cardId) {
    return {
      type: "UNKNOWN",
      status: "INVALID_FORMAT",
      message: "Fel: Ogiltigt kort-ID.",
      secondary_message: "",
      status_color: "orange",
      color_code: "#FF9800",
      card_number_dec: "",
      member_name: "N/A",
    };
  }

  const card = await store.getCard(cardId);
  if (!card) {
    console.log(JSON.stringify({ event: "checkin", kioskId, cardId, status: "NOT_FOUND" }));
    return notFoundStatus(cardId);
  }

  if (card.kind === "tencard") {
    const remaining = Number(card.remaining) || 0;
    if (remaining <= 0) {
      const status = tencardStatus({ card_id: card.card_id, name: card.name, remaining: 0 });
      console.log(JSON.stringify({ event: "checkin", kioskId, cardId, status: status.status }));
      return status;
    }

    const clip = await store.clipTencard(cardId);
    if (clip === "missing" || clip === "exhausted") {
      const status = tencardStatus({ card_id: card.card_id, name: card.name, remaining: 0 });
      status.status = "TENCARD_CLIP_FAIL_EXHAUSTED";
      status.message = "Klipp misslyckades: 0 klipp kvar!";
      console.log(JSON.stringify({ event: "checkin", kioskId, cardId, status: status.status }));
      return status;
    }

    const status = clipSuccessStatus(cardId, clip.remaining, clip.name);
    console.log(JSON.stringify({ event: "checkin", kioskId, cardId, status: status.status, remaining: clip.remaining }));
    return status;
  }

  const status = memberStatus({
    card_id: card.card_id,
    name: card.name,
    status: card.status,
    expires_at: card.expires_at,
  });
  console.log(JSON.stringify({ event: "checkin", kioskId, cardId, status: status.status }));
  return status;
}
