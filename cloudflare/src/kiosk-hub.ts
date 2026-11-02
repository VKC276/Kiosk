import { DurableObject } from "cloudflare:workers";
import { performCheckin } from "./checkin";
import { d1CardStore } from "./d1-store";
import type { CheckinStatus } from "./types";

export type HubEvent =
  | { type: "reading"; message?: string }
  | { type: "status"; data: CheckinStatus }
  | { type: "clear" };

type PendingClip = { cardId: string; expiresAt: number };

const PENDING_TTL_MS = 90_000;

export class KioskHub extends DurableObject<Env> {
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair("ping", "pong"));
  }

  async fetch(request: Request): Promise<Response> {
    if (request.headers.get("Upgrade") !== "websocket") {
      return new Response("Expected WebSocket", { status: 426 });
    }
    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);
    this.ctx.acceptWebSocket(server);
    return new Response(null, { status: 101, webSocket: client });
  }

  async setPending(cardId: string | null): Promise<void> {
    if (!cardId) {
      await this.ctx.storage.delete("pending");
      return;
    }
    const pending: PendingClip = { cardId, expiresAt: Date.now() + PENDING_TTL_MS };
    await this.ctx.storage.put("pending", pending);
  }

  async broadcast(event: HubEvent): Promise<void> {
    const payload = JSON.stringify(event);
    for (const ws of this.ctx.getWebSockets()) {
      try {
        ws.send(payload);
      } catch {
        // Drop broken sockets; hibernation API will clean them up.
      }
    }
  }

  async confirmClip(): Promise<void> {
    const pending = await this.ctx.storage.get<PendingClip>("pending");
    await this.ctx.storage.delete("pending");
    if (!pending || !pending.cardId || pending.expiresAt < Date.now()) {
      await this.broadcast({
        type: "status",
        data: {
          type: "UNKNOWN",
          status: "CHECKIN_ERROR",
          message: "Ingen aktiv blipp att klippa.",
          secondary_message: "Blippa kortet igen.",
          status_color: "orange",
          color_code: "#FF9800",
          card_number_dec: "",
          member_name: "",
        },
      });
      return;
    }

    await this.broadcast({ type: "reading", message: "Klipper markering…" });
    const kioskId = this.ctx.id.name || "retail";
    const status = await performCheckin(d1CardStore(this.env.DB), pending.cardId, kioskId);
    await this.broadcast({ type: "status", data: status });
  }

  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer): Promise<void> {
    if (message === "ping") {
      ws.send("pong");
      return;
    }
    const text = typeof message === "string" ? message : new TextDecoder().decode(message);
    let msg: { type?: string };
    try {
      msg = JSON.parse(text) as { type?: string };
    } catch {
      return;
    }
    if (msg.type === "confirm_clip") {
      await this.confirmClip();
    }
  }

  async webSocketClose(ws: WebSocket, code: number, reason: string): Promise<void> {
    ws.close(code, reason);
  }
}
