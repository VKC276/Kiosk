import { requireToken } from "./auth";
import { jsonWithCors, preflight } from "./cors";
import { performCheckin } from "./checkin";
import { d1CardStore } from "./d1-store";
import {
  listTencards,
  loadKioskConfig,
  saveKioskConfig,
  saveTencard,
  upsertMembers,
  upsertTencards,
} from "./import";
import { KioskHub } from "./kiosk-hub";
import type { CheckinStatus, KioskConfig } from "./types";

export { KioskHub };

function json(request: Request, data: unknown, status = 200): Response {
  return jsonWithCors(request, data, status);
}

function clipPayload(status: CheckinStatus) {
  const remaining =
    typeof status.klipp_kvar_local === "number" ? status.klipp_kvar_local : null;
  return {
    ok: true,
    remaining,
    exhausted: remaining === 0 && status.type === "TENCARD",
    found: status.status !== "NOT_FOUND" && status.status !== "INVALID_FORMAT",
    status,
  };
}

function kioskIdFrom(url: URL, env: Env, body?: { kiosk_id?: string }): string {
  return (
    body?.kiosk_id ||
    url.searchParams.get("kiosk") ||
    env.DEFAULT_KIOSK_ID ||
    "reception"
  ).trim();
}

async function hub(env: Env, kioskId: string) {
  return env.KIOSK_HUB.getByName(kioskId);
}

async function readJsonBody(request: Request): Promise<Record<string, unknown>> {
  const contentType = request.headers.get("Content-Type") || "";
  if (contentType.includes("application/x-www-form-urlencoded")) {
    const form = await request.formData();
    const out: Record<string, unknown> = {};
    for (const [key, value] of form.entries()) {
      out[key] = typeof value === "string" ? value : String(value);
    }
    return out;
  }
  try {
    const parsed = await request.json();
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
    return { data: parsed };
  } catch {
    return {};
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    try {
      if (request.method === "OPTIONS") {
        return preflight(request);
      }

      if (url.pathname === "/healthz") {
        return json(request, { ok: true });
      }

      if (url.pathname === "/api/kiosk/config" && request.method === "GET") {
        const cfg = await loadKioskConfig(env.DB, kioskIdFrom(url, env));
        return json(request, { ok: true, config: cfg });
      }

      if ((url.pathname === "/api/kiosk/ws" || url.pathname === "/ws") && request.method === "GET") {
        return (await hub(env, kioskIdFrom(url, env))).fetch(request);
      }

      if (url.pathname === "/api/checkin/reading" && request.method === "POST") {
        const denied = requireToken(request, env.KIOSK_TOKEN, "KIOSK_TOKEN");
        if (denied) return denied;
        const body = await readJsonBody(request);
        const id = kioskIdFrom(url, env, body as { kiosk_id?: string });
        await (await hub(env, id)).broadcast({ type: "reading" });
        return json(request, { ok: true });
      }

      if (
        (url.pathname === "/api/checkin" || url.pathname === "/api/clip") &&
        request.method === "POST"
      ) {
        const denied = requireToken(request, env.KIOSK_TOKEN, "KIOSK_TOKEN");
        if (denied) return denied;
        const body = await readJsonBody(request);
        const id = kioskIdFrom(url, env, body as { kiosk_id?: string });
        const cardId = body.card_id ?? body.cardId;
        const status = await performCheckin(d1CardStore(env.DB), cardId, id);
        await (await hub(env, id)).broadcast({ type: "status", data: status });
        return json(request, clipPayload(status));
      }

      if (url.pathname.startsWith("/api/admin/")) {
        const denied = requireToken(request, env.ADMIN_TOKEN, "ADMIN_TOKEN");
        if (denied) return denied;
      }

      if (url.pathname === "/api/admin/import/members" && request.method === "POST") {
        const payload = await request.json();
        const rows = Array.isArray(payload) ? payload : (payload as { members?: unknown[] }).members;
        if (!Array.isArray(rows)) return json(request, { ok: false, error: "expected JSON array" }, 400);
        const result = await upsertMembers(env.DB, rows as Record<string, unknown>[]);
        return json(request, { ok: true, ...result });
      }

      if (url.pathname === "/api/admin/import/tencards" && request.method === "POST") {
        const payload = await request.json();
        const rows = Array.isArray(payload)
          ? payload
          : (payload as { tencards?: unknown[] }).tencards;
        if (!Array.isArray(rows)) return json(request, { ok: false, error: "expected JSON array" }, 400);
        const result = await upsertTencards(env.DB, rows as Record<string, unknown>[]);
        return json(request, { ok: true, ...result });
      }

      if (url.pathname === "/api/admin/tencards" && request.method === "GET") {
        const cards = await listTencards(env.DB);
        return json(request, { ok: true, tencards: cards });
      }

      if (url.pathname === "/api/admin/tencards" && request.method === "POST") {
        const body = await readJsonBody(request);
        const cardId = String(body.card_id ?? body.cardId ?? "").trim();
        if (!cardId) return json(request, { ok: false, error: "card_id required" }, 400);
        if (typeof body.remaining !== "number" && typeof body.remaining !== "string") {
          return json(request, { ok: false, error: "remaining required" }, 400);
        }
        await saveTencard(env.DB, {
          card_id: cardId,
          remaining: Number(body.remaining),
          status: body.status != null ? String(body.status) : undefined,
          last_clipped_at: body.last_clipped_at != null ? String(body.last_clipped_at) : null,
          name: body.name != null ? String(body.name) : "",
        });
        const card = await d1CardStore(env.DB).getCard(cardId);
        return json(request, { ok: true, card_id: cardId, card });
      }

      if (url.pathname.startsWith("/api/admin/tencards/") && request.method === "GET") {
        const cardId = decodeURIComponent(url.pathname.slice("/api/admin/tencards/".length));
        if (!cardId) return json(request, { ok: false, error: "card_id required" }, 400);
        const card = await d1CardStore(env.DB).getCard(cardId);
        if (!card || card.kind !== "tencard") {
          return json(request, { ok: false, error: "not_found" }, 404);
        }
        return json(request, { ok: true, card });
      }

      if (url.pathname === "/api/admin/kiosk/config" && request.method === "PUT") {
        const body = (await request.json()) as Partial<KioskConfig> & { kiosk_id?: string };
        const id = body.kiosk_id || env.DEFAULT_KIOSK_ID || "reception";
        const current = await loadKioskConfig(env.DB, id);
        const next: KioskConfig = {
          ...current,
          ...body,
          kiosk_id: id,
          slides: Array.isArray(body.slides) ? body.slides : current.slides,
        };
        await saveKioskConfig(env.DB, next);
        return json(request, { ok: true, config: next });
      }

      if (url.pathname === "/api/admin/kiosk/config" && request.method === "GET") {
        const cfg = await loadKioskConfig(env.DB, kioskIdFrom(url, env));
        return json(request, { ok: true, config: cfg });
      }

      if (url.pathname.startsWith("/api/admin/lookup/") && request.method === "GET") {
        const cardId = decodeURIComponent(url.pathname.slice("/api/admin/lookup/".length));
        const store = d1CardStore(env.DB);
        const card = await store.getCard(cardId);
        return json(request, { ok: true, card_id: cardId, card });
      }

      if (url.pathname === "/api/admin/stats" && request.method === "GET") {
        const rows = await env.DB.prepare("SELECT key, value FROM meta").all<{ key: string; value: number }>();
        const counts = Object.fromEntries((rows.results || []).map((r) => [r.key, Number(r.value) || 0]));
        return json(request, {
          ok: true,
          members: counts.members || 0,
          tencards: counts.tencards || 0,
        });
      }

      return env.ASSETS.fetch(request);
    } catch (error) {
      console.error(JSON.stringify({ path: url.pathname, error: String(error) }));
      return json(request, { ok: false, error: "internal_error" }, 500);
    }
  },
} satisfies ExportedHandler<Env>;
