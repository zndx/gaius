-- migrate:up
-- Operator disable vs YK preempt: auto-start must not undo /ambient stop.

ALTER TABLE ambient_daemon_state
    ADD COLUMN IF NOT EXISTS operator_disabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS preempted BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN ambient_daemon_state.operator_disabled IS
    'True after explicit /ambient stop. Engine start will not auto-start.';
COMMENT ON COLUMN ambient_daemon_state.preempted IS
    'True while YK Yield paused GPU phases. RAM buffer stays.';

GRANT SELECT, INSERT, UPDATE ON ambient_daemon_state TO gaius;

-- migrate:down
ALTER TABLE ambient_daemon_state
    DROP COLUMN IF EXISTS operator_disabled,
    DROP COLUMN IF EXISTS preempted;
