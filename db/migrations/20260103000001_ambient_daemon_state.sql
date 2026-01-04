-- migrate:up
-- Ambient daemon state persistence for auto-restart after engine restart.
--
-- The ambient daemon runs continuous cycles but loses state on engine restart.
-- This table persists the daemon state so it can be resumed automatically.

CREATE TABLE IF NOT EXISTS ambient_daemon_state (
    id INTEGER PRIMARY KEY DEFAULT 1,  -- Singleton pattern: always ID 1

    -- Daemon control state
    running BOOLEAN NOT NULL DEFAULT FALSE,
    baseline_only BOOLEAN NOT NULL DEFAULT FALSE,
    max_cycles INTEGER,  -- NULL = infinite

    -- Progress tracking
    cycles_completed INTEGER NOT NULL DEFAULT 0,
    total_tasks INTEGER NOT NULL DEFAULT 0,
    successful_tasks INTEGER NOT NULL DEFAULT 0,

    -- Timestamps
    started_at TIMESTAMPTZ,
    stopped_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Ensure singleton: only row with id=1 can exist
    CONSTRAINT ambient_daemon_state_singleton CHECK (id = 1)
);

-- Insert the singleton row
INSERT INTO ambient_daemon_state (id, running) VALUES (1, FALSE)
ON CONFLICT (id) DO NOTHING;

-- Function to update ambient daemon state atomically
CREATE OR REPLACE FUNCTION update_ambient_daemon_state(
    p_running BOOLEAN,
    p_baseline_only BOOLEAN DEFAULT FALSE,
    p_max_cycles INTEGER DEFAULT NULL,
    p_cycles_completed INTEGER DEFAULT 0,
    p_total_tasks INTEGER DEFAULT 0,
    p_successful_tasks INTEGER DEFAULT 0
) RETURNS ambient_daemon_state AS $$
DECLARE
    result ambient_daemon_state;
BEGIN
    UPDATE ambient_daemon_state
    SET
        running = p_running,
        baseline_only = p_baseline_only,
        max_cycles = p_max_cycles,
        cycles_completed = p_cycles_completed,
        total_tasks = p_total_tasks,
        successful_tasks = p_successful_tasks,
        started_at = CASE
            WHEN p_running AND NOT running THEN NOW()  -- Starting fresh
            WHEN p_running THEN started_at             -- Keep existing start time
            ELSE NULL                                   -- Stopped
        END,
        stopped_at = CASE
            WHEN NOT p_running AND running THEN NOW()  -- Just stopped
            ELSE stopped_at                             -- Keep existing
        END,
        updated_at = NOW()
    WHERE id = 1
    RETURNING * INTO result;

    RETURN result;
END;
$$ LANGUAGE plpgsql;

-- Function to increment cycle count (called after each cycle)
CREATE OR REPLACE FUNCTION increment_ambient_cycle(
    p_tasks_in_cycle INTEGER DEFAULT 0,
    p_successful_in_cycle INTEGER DEFAULT 0
) RETURNS VOID AS $$
BEGIN
    UPDATE ambient_daemon_state
    SET
        cycles_completed = cycles_completed + 1,
        total_tasks = total_tasks + p_tasks_in_cycle,
        successful_tasks = successful_tasks + p_successful_in_cycle,
        updated_at = NOW()
    WHERE id = 1 AND running = TRUE;
END;
$$ LANGUAGE plpgsql;

-- View for easy status checking
CREATE OR REPLACE VIEW ambient_daemon_status AS
SELECT
    running,
    baseline_only,
    max_cycles,
    cycles_completed,
    CASE
        WHEN max_cycles IS NOT NULL THEN max_cycles - cycles_completed
        ELSE NULL
    END as cycles_remaining,
    total_tasks,
    successful_tasks,
    CASE
        WHEN total_tasks > 0
        THEN ROUND((successful_tasks::NUMERIC / total_tasks) * 100, 1)
        ELSE NULL
    END as success_rate_pct,
    started_at,
    stopped_at,
    updated_at,
    CASE
        WHEN running AND started_at IS NOT NULL
        THEN EXTRACT(EPOCH FROM (NOW() - started_at))::INTEGER
        ELSE NULL
    END as uptime_seconds
FROM ambient_daemon_state
WHERE id = 1;

COMMENT ON TABLE ambient_daemon_state IS 'Singleton table for ambient daemon state persistence. Auto-restart on engine restart.';

-- Grant permissions to gaius user (used by engine)
GRANT SELECT, INSERT, UPDATE ON ambient_daemon_state TO gaius;
GRANT SELECT ON ambient_daemon_status TO gaius;
GRANT EXECUTE ON FUNCTION update_ambient_daemon_state TO gaius;
GRANT EXECUTE ON FUNCTION increment_ambient_cycle TO gaius;

-- migrate:down
DROP VIEW IF EXISTS ambient_daemon_status;
DROP FUNCTION IF EXISTS increment_ambient_cycle;
DROP FUNCTION IF EXISTS update_ambient_daemon_state;
DROP TABLE IF EXISTS ambient_daemon_state;
