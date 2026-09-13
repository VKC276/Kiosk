CREATE TABLE IF NOT EXISTS cards (
  card_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('member', 'tencard')),
  name TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '',
  expires_at TEXT,
  remaining INTEGER,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO cards (card_id, kind, name, remaining, updated_at)
SELECT card_id, 'tencard', name, remaining, updated_at FROM tencards;

INSERT OR IGNORE INTO cards (card_id, kind, name, status, expires_at, remaining, updated_at)
SELECT card_id, 'member', name, status, expires_at, NULL, updated_at FROM members;

DROP TABLE IF EXISTS checkin_logs;
DROP TABLE IF EXISTS members;
DROP TABLE IF EXISTS tencards;

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value INTEGER NOT NULL DEFAULT 0
);

INSERT OR IGNORE INTO meta (key, value) VALUES ('members', 0), ('tencards', 0);

INSERT OR REPLACE INTO meta (key, value)
SELECT 'tencards', COUNT(*) FROM cards WHERE kind = 'tencard';

INSERT OR REPLACE INTO meta (key, value)
SELECT 'members', COUNT(*) FROM cards WHERE kind = 'member';
