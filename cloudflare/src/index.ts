import { requireToken } from "./auth";
import { performCheckin } from "./checkin";
import { d1CardStore } from "./d1-store";
import { loadKioskConfig, saveKioskConfig, upsertMembers, upsertTencards } from "./import";
import { KioskHub } from "./kiosk-hub";
import type { KioskConfig } from "./types";

export { KioskHub };

function json(data: unknown, status = 200): Response {
  return Response.json(data, { status });
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
      if (url.pathname === "/healthz") {
        const members = await env.DB.prepare("SELECT COUNT(*) AS n FROM members").first<{ n: number }>();
        const tencards = await env.DB.prepare("SELECT COUNT(*) AS n FROM tencards").first<{ n: number }>();
        return json({
          ok: true,
          members: Number(members?.n) || 0,
          tencards: Number(tencards?.n) || 0,
        });
      }

      if (url.pathname === "/api/kiosk/config" && request.method === "GET") {
        const cfg = await loadKioskConfig(env.DB, kioskIdFrom(url, env));
        return json({ ok: true, config: cfg });
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
        return json({ ok: true });
      }

      if (url.pathname === "/api/checkin" && request.method === "POST") {
        const denied = requireToken(request, env.KIOSK_TOKEN, "KIOSK_TOKEN");
        if (denied) return denied;
        const body = await readJsonBody(request);
        const id = kioskIdFrom(url, env, body as { kiosk_id?: string });
        const cardId = body.card_id ?? body.cardId;
        const status = await performCheckin(d1CardStore(env.DB), cardId, id);
        await (await hub(env, id)).broadcast({ type: "status", data: status });
        return json({ ok: true, status });
      }

      if (url.pathname === "/api/admin/import/members" && request.method === "POST") {
        const denied = requireToken(request, env.ADMIN_TOKEN, "ADMIN_TOKEN");
        if (denied) return denied;
        const payload = await request.json();
        const rows = Array.isArray(payload) ? payload : (payload as { members?: unknown[] }).members;
        if (!Array.isArray(rows)) return json({ ok: false, error: "expected JSON array" }, 400);
        const result = await upsertMembers(env.DB, rows as Record<string, unknown>[]);
        return json({ ok: true, ...result });
      }

      if (url.pathname === "/api/admin/import/tencards" && request.method === "POST") {
        const denied = requireToken(request, env.ADMIN_TOKEN, "ADMIN_TOKEN");
        if (denied) return denied;
        const payload = await request.json();
        const rows = Array.isArray(payload)
          ? payload
          : (payload as { tencards?: unknown[] }).tencards;
        if (!Array.isArray(rows)) return json({ ok: false, error: "expected JSON array" }, 400);
        const result = await upsertTencards(env.DB, rows as Record<string, unknown>[]);
        return json({ ok: true, ...result });
      }

      if (url.pathname === "/api/admin/kiosk/config" && request.method === "PUT") {
        const denied = requireToken(request, env.ADMIN_TOKEN, "ADMIN_TOKEN");
        if (denied) return denied;
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
        return json({ ok: true, config: next });
      }

      if (url.pathname === "/api/admin/kiosk/config" && request.method === "GET") {
        const denied = requireToken(request, env.ADMIN_TOKEN, "ADMIN_TOKEN");
        if (denied) return denied;
        const cfg = await loadKioskConfig(env.DB, kioskIdFrom(url, env));
        return json({ ok: true, config: cfg });
      }

      if (url.pathname.startsWith("/api/admin/lookup/") && request.method === "GET") {
        const denied = requireToken(request, env.ADMIN_TOKEN, "ADMIN_TOKEN");
        if (denied) return denied;
        const cardId = decodeURIComponent(url.pathname.slice("/api/admin/lookup/".length));
        const store = d1CardStore(env.DB);
        const tencard = await store.getTencard(cardId);
        const member = tencard ? null : await store.getMember(cardId);
        return json({ ok: true, card_id: cardId, tencard, member });
      }

      if (url.pathname === "/api/admin/stats" && request.method === "GET") {
        const denied = requireToken(request, env.ADMIN_TOKEN, "ADMIN_TOKEN");
        if (denied) return denied;
        const members = await env.DB.prepare("SELECT COUNT(*) AS n FROM members").first<{ n: number }>();
        const tencards = await env.DB.prepare("SELECT COUNT(*) AS n FROM tencards").first<{ n: number }>();
        const logs = await env.DB.prepare("SELECT COUNT(*) AS n FROM checkin_logs").first<{ n: number }>();
        return json({
          ok: true,
          members: Number(members?.n) || 0,
          tencards: Number(tencards?.n) || 0,
          logs: Number(logs?.n) || 0,
        });
      }

      return env.ASSETS.fetch(request);
    } catch (error) {
      console.error(JSON.stringify({ path: url.pathname, error: String(error) }));
      return json({ ok: false, error: "internal_error" }, 500);
    }
  },
} satisfies ExportedHandler<Env>;
