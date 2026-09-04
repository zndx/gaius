-- migrate:up
-- The engine-hosted EngineSupervision.Supervise stream (2026-09-04): one row per
-- supervisor session so ABSENCE is visible after a restart — an engine that has
-- never seen its supervisor connect is a finding, not a blank. Updated by the
-- servicer on open, every heartbeat, and on close. The ops_backlog objective's
-- nautilus_connected gate reads it.
CREATE TABLE IF NOT EXISTS supervision_sessions (
    id                    BIGSERIAL PRIMARY KEY,
    connected_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    disconnected_at       TIMESTAMPTZ,
    peer                  TEXT NOT NULL DEFAULT '',
    supervisor_id         TEXT NOT NULL,
    supervisor_epoch      TEXT NOT NULL DEFAULT '',
    since_unix_ms         BIGINT NOT NULL DEFAULT 0,
    replay_rows           INTEGER NOT NULL DEFAULT 0,
    events_sent           BIGINT NOT NULL DEFAULT 0,
    events_dropped        BIGINT NOT NULL DEFAULT 0,
    directives_received   INTEGER NOT NULL DEFAULT 0,
    directives_accepted   INTEGER NOT NULL DEFAULT 0,
    directives_refused    INTEGER NOT NULL DEFAULT 0,
    last_heartbeat_at     TIMESTAMPTZ,
    goodbye_reason        TEXT
);
COMMENT ON TABLE supervision_sessions IS
  'EngineSupervision.Supervise sessions (the resident Nautilus dialing this engine). '
  'A live session has disconnected_at IS NULL and a fresh last_heartbeat_at.';
CREATE INDEX IF NOT EXISTS supervision_sessions_live_idx
  ON supervision_sessions (connected_at DESC) WHERE disconnected_at IS NULL;
GRANT SELECT, INSERT, UPDATE ON supervision_sessions TO gaius;
GRANT USAGE, SELECT ON SEQUENCE supervision_sessions_id_seq TO gaius;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nautilus') THEN
    EXECUTE 'GRANT SELECT ON supervision_sessions TO nautilus';
  END IF;
END $$;

-- migrate:down
DROP TABLE IF EXISTS supervision_sessions;
