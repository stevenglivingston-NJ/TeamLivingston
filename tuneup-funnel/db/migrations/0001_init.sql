-- KTU Instant Tune-Up Funnel — initial D1 schema.
-- Money columns are integer cents. Every funnel gate writes a funnel_events row.

CREATE TABLE IF NOT EXISTS quote_sessions (
  id TEXT PRIMARY KEY,                -- uuid
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  stage TEXT NOT NULL DEFAULT 'landing',
  -- landing | zip | details | photos | contact | price | schedule | agreement | confirmed
  zip TEXT,
  in_service_area INTEGER,            -- 0/1
  openings INTEGER,
  cabinet_material TEXT,
  cabinet_age TEXT,
  level TEXT,                         -- L1_2 | L3 | L4 (AI-assigned)
  ai_confidence REAL,
  white_wash INTEGER,                 -- 0/1
  quote_cents INTEGER,
  floor_applied INTEGER,              -- 0/1
  sdd_applied INTEGER,                -- 0/1
  sdd_deadline TEXT,
  deposit_cents INTEGER,
  status TEXT NOT NULL DEFAULT 'open'
  -- open | human_review | booked | abandoned | out_of_area
);

CREATE TABLE IF NOT EXISTS leads (
  id TEXT PRIMARY KEY,                -- uuid
  session_id TEXT NOT NULL REFERENCES quote_sessions(id),
  created_at TEXT NOT NULL,
  name TEXT NOT NULL,
  phone TEXT NOT NULL,
  email TEXT NOT NULL,
  callback_requested INTEGER NOT NULL DEFAULT 0,
  pushed_to_highlevel_at TEXT
);

-- Per-gate audit log: every gate transition, quote reveal, callback request, etc.
CREATE TABLE IF NOT EXISTS funnel_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT,
  created_at TEXT NOT NULL,
  event TEXT NOT NULL,
  detail TEXT                          -- JSON
);
CREATE INDEX IF NOT EXISTS idx_funnel_events_session ON funnel_events(session_id);

-- One row per pricing-sync run (ok / incomplete / error) for rate traceability.
CREATE TABLE IF NOT EXISTS rate_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fetched_at TEXT NOT NULL,
  event TEXT NOT NULL,                 -- sync_ok | sync_incomplete | sync_error
  detail TEXT                          -- JSON: rates or error message
);
