export type CheckinStatus = {
  type: string;
  status: string;
  message: string;
  secondary_message: string;
  status_color: string;
  color_code: string;
  card_number_dec: string;
  member_name: string;
  expiry_date?: string;
  klipp_kvar_local?: number;
};

export type MemberRow = {
  card_id: string;
  name: string;
  status: string;
  expires_at: string | null;
};

export type TencardRow = {
  card_id: string;
  name: string;
  remaining: number;
};

export type KioskConfig = {
  kiosk_id: string;
  slides: unknown[];
  checkin_enabled: boolean;
  checkin_height_percent: number;
  reload_on_show: boolean;
  reload_interval_seconds: number;
  status_display_seconds: number;
  last_clip_ok_seconds: number;
  last_clip_return_seconds: number;
};

export type CardRow = {
  card_id: string;
  kind: "member" | "tencard";
  name: string;
  status: string;
  expires_at: string | null;
  remaining: number | null;
};

export type CardStore = {
  getCard(cardId: string): Promise<CardRow | null>;
  clipTencard(cardId: string): Promise<{ remaining: number; name: string } | "exhausted" | "missing">;
};
