CREATE TABLE IF NOT EXISTS members (
  card_id TEXT PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '',
  expires_at TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tencards (
  card_id TEXT PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  remaining INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS checkin_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  kiosk_id TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_checkin_logs_created ON checkin_logs (created_at);
CREATE INDEX IF NOT EXISTS idx_checkin_logs_card ON checkin_logs (card_id);

CREATE TABLE IF NOT EXISTS kiosk_config (
  kiosk_id TEXT PRIMARY KEY,
  slides_json TEXT NOT NULL DEFAULT '[]',
  checkin_enabled INTEGER NOT NULL DEFAULT 1,
  checkin_height_percent INTEGER NOT NULL DEFAULT 20,
  reload_on_show INTEGER NOT NULL DEFAULT 0,
  reload_interval_seconds INTEGER NOT NULL DEFAULT 300,
  status_display_seconds INTEGER NOT NULL DEFAULT 3,
  last_clip_ok_seconds INTEGER NOT NULL DEFAULT 3,
  last_clip_return_seconds INTEGER NOT NULL DEFAULT 5,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO kiosk_config (kiosk_id, slides_json) VALUES (
  'reception',
  '[{"id":"wallflow","title":"WallFlow statistik","url":"https://wallflow.vastervikclimbing.se/display.html","durationSeconds":15,"reloadIntervalSeconds":900}]'
);
