interface Env {
  DB: D1Database;
  KIOSK_HUB: DurableObjectNamespace<import("./kiosk-hub").KioskHub>;
  ASSETS: Fetcher;
  KIOSK_TOKEN: string;
  ADMIN_TOKEN: string;
  DEFAULT_KIOSK_ID: string;
}
