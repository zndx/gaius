-- migrate:up
-- Directive idempotency (2026-09-04). The supervisor sends directives at least once
-- (it resends after a reconnect until a DirectiveResult arrives); the engine must
-- apply each directive_id exactly once and answer resends from this table — never
-- re-apply a reclaim after its own restart. Append-only by privilege.
CREATE TABLE IF NOT EXISTS supervision_directives (
    directive_id  UUID PRIMARY KEY,
    kind          TEXT NOT NULL,          -- reclaim_orphan | escalation | backlog_transition
    received_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    session_id    BIGINT,
    accepted      BOOLEAN NOT NULL,
    applied       BOOLEAN NOT NULL,
    forecast_id   UUID,                   -- the probe_forecasts row the engine recorded
    result        JSONB NOT NULL DEFAULT '{}'
);
COMMENT ON TABLE supervision_directives IS
  'Every supervisor directive the engine has answered, keyed by directive_id: the dedup '
  'table for at-least-once delivery over EngineSupervision.Supervise. Immutable rows.';
CREATE INDEX IF NOT EXISTS supervision_directives_recv_idx ON supervision_directives (received_at DESC);
GRANT SELECT, INSERT ON supervision_directives TO gaius;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nautilus') THEN
    EXECUTE 'GRANT SELECT ON supervision_directives TO nautilus';
  END IF;
END $$;

-- migrate:down
DROP TABLE IF EXISTS supervision_directives;
