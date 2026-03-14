-- migrate:up

-- ============================================================================
-- Prospects Scheduled Task Infrastructure
-- ============================================================================
-- Replaces broken pg_cron job that SELECTed to nowhere with one that
-- INSERTs into scheduled_tasks, using the LISTEN/NOTIFY pipeline.

-- Cooldown state table (mirrors collections.curation_state pattern)
CREATE TABLE IF NOT EXISTS meta.prospects_cron_state (
    key TEXT PRIMARY KEY,
    last_run_at TIMESTAMPTZ,
    run_count INTEGER DEFAULT 0
);

INSERT INTO meta.prospects_cron_state (key, last_run_at, run_count)
VALUES ('prospects_check', NULL, 0)
ON CONFLICT (key) DO NOTHING;

-- 24-hour cooldown gate
CREATE OR REPLACE FUNCTION meta.should_run_prospects_check()
RETURNS BOOLEAN AS $$
DECLARE
    v_last_run TIMESTAMPTZ;
    v_hours_since NUMERIC;
BEGIN
    SELECT last_run_at INTO v_last_run
    FROM meta.prospects_cron_state
    WHERE key = 'prospects_check';

    IF v_last_run IS NULL THEN
        RETURN TRUE;
    END IF;

    v_hours_since := EXTRACT(EPOCH FROM (NOW() - v_last_run)) / 3600;
    RETURN v_hours_since >= 24;
END;
$$ LANGUAGE plpgsql;

-- Mark check as started (called by handler after pickup)
CREATE OR REPLACE FUNCTION meta.mark_prospects_check_started()
RETURNS VOID AS $$
BEGIN
    UPDATE meta.prospects_cron_state
    SET last_run_at = NOW(),
        run_count = run_count + 1
    WHERE key = 'prospects_check';
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Replace broken pg_cron job
-- ============================================================================

-- Remove the old broken job that SELECTed to nowhere
SELECT cron.unschedule('prospects-daily-check');

-- New job: INSERT into scheduled_tasks with cooldown gate
-- Runs at 7 AM daily, but only inserts if 24+ hours since last run
SELECT cron.schedule(
    'prospects-daily-check',
    '0 7 * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      SELECT 'prospects_check', '{}', 'pg_cron', NOW()
      WHERE meta.should_run_prospects_check()$$
);

-- ============================================================================
-- Permissions
-- ============================================================================

GRANT SELECT, INSERT, UPDATE ON meta.prospects_cron_state TO gaius;
GRANT EXECUTE ON FUNCTION meta.should_run_prospects_check() TO gaius;
GRANT EXECUTE ON FUNCTION meta.mark_prospects_check_started() TO gaius;

-- ============================================================================
-- Comments
-- ============================================================================

COMMENT ON TABLE meta.prospects_cron_state IS
'Tracks prospects check state for 24-hour cooldown enforcement.
Used by pg_cron job to implement daily interval via should_run_prospects_check().';

COMMENT ON FUNCTION meta.should_run_prospects_check() IS
'Returns TRUE if 24+ hours have passed since last prospects check.
Called by pg_cron job to enforce cooldown period.';

COMMENT ON FUNCTION meta.mark_prospects_check_started() IS
'Updates last_run_at and increments run_count. Called by the
ScheduledTaskProcessor handler after picking up a prospects_check task.';


-- migrate:down

-- Remove new cron job
SELECT cron.unschedule('prospects-daily-check');

-- Restore original broken cron job (for rollback fidelity)
SELECT cron.schedule(
    'prospects-daily-check',
    '0 7 * * *',
    $$SELECT * FROM meta.prospects_daily_check()$$
);

-- Drop new objects
DROP FUNCTION IF EXISTS meta.mark_prospects_check_started();
DROP FUNCTION IF EXISTS meta.should_run_prospects_check();
DROP TABLE IF EXISTS meta.prospects_cron_state;
