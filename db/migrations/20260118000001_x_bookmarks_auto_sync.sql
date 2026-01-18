-- migrate:up
-- X Bookmarks Auto-Sync: Background continuation of incremental sync
--
-- When user initiates /xb sync, this schedules background continuation
-- that runs every 16 minutes until all folders are synced or token expires.

-- ============================================================================
-- AUTO-SYNC SCHEDULE TABLE
-- ============================================================================

-- Track active auto-sync schedules per user
CREATE TABLE IF NOT EXISTS x_auto_sync_schedules (
    user_id VARCHAR(64) PRIMARY KEY REFERENCES x_oauth_tokens(user_id) ON DELETE CASCADE,

    -- Schedule state
    is_active BOOLEAN DEFAULT TRUE,
    next_run_at TIMESTAMPTZ NOT NULL,

    -- Progress tracking
    folders_total INTEGER DEFAULT 0,
    folders_synced INTEGER DEFAULT 0,
    sync_iterations INTEGER DEFAULT 0,

    -- Timing configuration (from Basic tier: 10 req/15 min)
    interval_minutes INTEGER DEFAULT 16,  -- rate limit window + 1 minute buffer

    -- Limits to prevent runaway
    max_iterations INTEGER DEFAULT 50,    -- ~13 hours max for 20 folders at 3/batch

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    -- Metadata for debugging
    last_error TEXT,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_x_auto_sync_active ON x_auto_sync_schedules(is_active, next_run_at)
    WHERE is_active = TRUE;

COMMENT ON TABLE x_auto_sync_schedules IS 'Active auto-sync schedules for X bookmarks';
COMMENT ON COLUMN x_auto_sync_schedules.interval_minutes IS 'Minutes between sync iterations (16 = 15min rate limit + 1min buffer)';
COMMENT ON COLUMN x_auto_sync_schedules.max_iterations IS 'Maximum iterations before auto-cancel (prevents runaway)';

-- ============================================================================
-- AUTO-SYNC HELPER FUNCTIONS
-- ============================================================================

-- Start or restart auto-sync for a user
-- Called when user runs /xb sync
CREATE OR REPLACE FUNCTION x_start_auto_sync(
    p_user_id VARCHAR(64),
    p_folders_total INTEGER DEFAULT 0,
    p_interval_minutes INTEGER DEFAULT 16
) RETURNS BOOLEAN AS $$
DECLARE
    v_next_run TIMESTAMPTZ;
BEGIN
    -- Schedule first continuation run after rate limit window
    v_next_run := NOW() + (p_interval_minutes || ' minutes')::INTERVAL;

    INSERT INTO x_auto_sync_schedules (
        user_id, is_active, next_run_at, folders_total, interval_minutes, metadata
    ) VALUES (
        p_user_id, TRUE, v_next_run, p_folders_total, p_interval_minutes,
        jsonb_build_object('started_at', NOW(), 'trigger', 'manual')
    )
    ON CONFLICT (user_id) DO UPDATE SET
        is_active = TRUE,
        next_run_at = v_next_run,
        folders_total = COALESCE(NULLIF(p_folders_total, 0), x_auto_sync_schedules.folders_total),
        folders_synced = 0,  -- Reset progress
        sync_iterations = 0,
        interval_minutes = p_interval_minutes,
        updated_at = NOW(),
        completed_at = NULL,
        last_error = NULL,
        metadata = jsonb_build_object('restarted_at', NOW(), 'trigger', 'manual');

    RAISE NOTICE 'Started auto-sync for user %, next run at %', p_user_id, v_next_run;
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Update progress after a sync iteration
CREATE OR REPLACE FUNCTION x_update_auto_sync_progress(
    p_user_id VARCHAR(64),
    p_folders_synced_this_batch INTEGER,
    p_folders_remaining INTEGER,
    p_error TEXT DEFAULT NULL
) RETURNS BOOLEAN AS $$
DECLARE
    v_schedule RECORD;
    v_next_run TIMESTAMPTZ;
BEGIN
    SELECT * INTO v_schedule FROM x_auto_sync_schedules WHERE user_id = p_user_id;

    IF NOT FOUND OR NOT v_schedule.is_active THEN
        RETURN FALSE;
    END IF;

    -- Update progress
    UPDATE x_auto_sync_schedules SET
        folders_synced = folders_synced + p_folders_synced_this_batch,
        sync_iterations = sync_iterations + 1,
        updated_at = NOW(),
        last_error = p_error
    WHERE user_id = p_user_id;

    -- Check completion conditions
    IF p_folders_remaining = 0 THEN
        -- All done!
        PERFORM x_stop_auto_sync(p_user_id, 'completed');
        RETURN TRUE;
    END IF;

    IF v_schedule.sync_iterations + 1 >= v_schedule.max_iterations THEN
        -- Hit iteration limit
        PERFORM x_stop_auto_sync(p_user_id, 'max_iterations');
        RETURN TRUE;
    END IF;

    -- Schedule next iteration
    v_next_run := NOW() + (v_schedule.interval_minutes || ' minutes')::INTERVAL;
    UPDATE x_auto_sync_schedules SET next_run_at = v_next_run WHERE user_id = p_user_id;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Stop auto-sync for a user
CREATE OR REPLACE FUNCTION x_stop_auto_sync(
    p_user_id VARCHAR(64),
    p_reason TEXT DEFAULT 'manual'
) RETURNS BOOLEAN AS $$
BEGIN
    UPDATE x_auto_sync_schedules SET
        is_active = FALSE,
        completed_at = NOW(),
        metadata = metadata || jsonb_build_object('stop_reason', p_reason, 'stopped_at', NOW())
    WHERE user_id = p_user_id AND is_active = TRUE;

    IF FOUND THEN
        RAISE NOTICE 'Stopped auto-sync for user %, reason: %', p_user_id, p_reason;
        RETURN TRUE;
    END IF;

    RETURN FALSE;
END;
$$ LANGUAGE plpgsql;

-- Get users due for auto-sync (called by pg_cron)
CREATE OR REPLACE FUNCTION x_get_due_auto_syncs()
RETURNS TABLE(user_id VARCHAR(64), folders_remaining INTEGER, iterations INTEGER) AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.user_id,
        s.folders_total - s.folders_synced AS folders_remaining,
        s.sync_iterations
    FROM x_auto_sync_schedules s
    JOIN x_oauth_tokens t ON t.user_id = s.user_id
    WHERE s.is_active = TRUE
      AND s.next_run_at <= NOW()
      AND t.expires_at > NOW()  -- Token still valid
    ORDER BY s.next_run_at ASC
    LIMIT 5;  -- Process up to 5 users at a time
END;
$$ LANGUAGE plpgsql;

-- Check if auto-sync is active for a user
CREATE OR REPLACE FUNCTION x_is_auto_sync_active(p_user_id VARCHAR(64))
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM x_auto_sync_schedules
        WHERE user_id = p_user_id AND is_active = TRUE
    );
END;
$$ LANGUAGE plpgsql;

-- Get auto-sync status for a user
CREATE OR REPLACE FUNCTION x_get_auto_sync_status(p_user_id VARCHAR(64))
RETURNS TABLE(
    active BOOLEAN,
    folders_total INTEGER,
    folders_synced INTEGER,
    folders_remaining INTEGER,
    iterations INTEGER,
    max_iterations INTEGER,
    next_run_at TIMESTAMPTZ,
    estimated_completion TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.is_active,
        s.folders_total,
        s.folders_synced,
        s.folders_total - s.folders_synced,
        s.sync_iterations,
        s.max_iterations,
        s.next_run_at,
        CASE
            WHEN s.folders_synced = 0 THEN NULL
            ELSE NOW() + (
                ((s.folders_total - s.folders_synced)::FLOAT /
                 GREATEST(s.folders_synced::FLOAT / GREATEST(s.sync_iterations, 1), 1)) *
                s.interval_minutes
            ) * INTERVAL '1 minute'
        END AS estimated_completion
    FROM x_auto_sync_schedules s
    WHERE s.user_id = p_user_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- PG_CRON JOB: Auto-sync processor
-- Runs every 5 minutes to check for due auto-syncs
-- ============================================================================

-- Function that pg_cron calls to trigger due syncs
-- This inserts a notification that the engine will pick up
CREATE OR REPLACE FUNCTION x_trigger_due_auto_syncs()
RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER := 0;
    v_user RECORD;
BEGIN
    FOR v_user IN SELECT * FROM x_get_due_auto_syncs()
    LOOP
        -- Use pg_notify to alert the engine
        PERFORM pg_notify(
            'x_auto_sync_due',
            json_build_object(
                'user_id', v_user.user_id,
                'folders_remaining', v_user.folders_remaining,
                'iteration', v_user.iterations + 1
            )::TEXT
        );
        v_count := v_count + 1;

        RAISE NOTICE 'Triggered auto-sync for user %, iteration %',
            v_user.user_id, v_user.iterations + 1;
    END LOOP;

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- Schedule auto-sync checker every 5 minutes
SELECT cron.schedule(
    'x-auto-sync-processor',
    '*/5 * * * *',
    $$SELECT x_trigger_due_auto_syncs()$$
);

-- ============================================================================
-- MONITORING VIEW
-- ============================================================================

CREATE OR REPLACE VIEW v_x_auto_sync_status AS
SELECT
    s.user_id,
    t.username,
    s.is_active,
    s.folders_total,
    s.folders_synced,
    s.folders_total - s.folders_synced AS folders_remaining,
    s.sync_iterations,
    s.max_iterations,
    s.interval_minutes,
    s.next_run_at,
    s.last_error,
    s.created_at,
    s.completed_at,
    CASE
        WHEN NOT s.is_active THEN 'stopped'
        WHEN t.expires_at <= NOW() THEN 'token_expired'
        WHEN s.next_run_at <= NOW() THEN 'due'
        ELSE 'scheduled'
    END AS status,
    s.metadata->>'stop_reason' AS stop_reason
FROM x_auto_sync_schedules s
JOIN x_oauth_tokens t ON t.user_id = s.user_id
ORDER BY s.updated_at DESC;

COMMENT ON VIEW v_x_auto_sync_status IS 'Auto-sync schedule status per user';

-- ============================================================================
-- GRANTS
-- ============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON x_auto_sync_schedules TO gaius;
GRANT SELECT ON v_x_auto_sync_status TO gaius;
GRANT EXECUTE ON FUNCTION x_start_auto_sync(VARCHAR, INTEGER, INTEGER) TO gaius;
GRANT EXECUTE ON FUNCTION x_update_auto_sync_progress(VARCHAR, INTEGER, INTEGER, TEXT) TO gaius;
GRANT EXECUTE ON FUNCTION x_stop_auto_sync(VARCHAR, TEXT) TO gaius;
GRANT EXECUTE ON FUNCTION x_get_due_auto_syncs() TO gaius;
GRANT EXECUTE ON FUNCTION x_is_auto_sync_active(VARCHAR) TO gaius;
GRANT EXECUTE ON FUNCTION x_get_auto_sync_status(VARCHAR) TO gaius;
GRANT EXECUTE ON FUNCTION x_trigger_due_auto_syncs() TO gaius;

-- migrate:down

-- Remove cron job
SELECT cron.unschedule('x-auto-sync-processor');

-- Drop view and functions
DROP VIEW IF EXISTS v_x_auto_sync_status;
DROP FUNCTION IF EXISTS x_trigger_due_auto_syncs();
DROP FUNCTION IF EXISTS x_get_auto_sync_status(VARCHAR);
DROP FUNCTION IF EXISTS x_is_auto_sync_active(VARCHAR);
DROP FUNCTION IF EXISTS x_get_due_auto_syncs();
DROP FUNCTION IF EXISTS x_stop_auto_sync(VARCHAR, TEXT);
DROP FUNCTION IF EXISTS x_update_auto_sync_progress(VARCHAR, INTEGER, INTEGER, TEXT);
DROP FUNCTION IF EXISTS x_start_auto_sync(VARCHAR, INTEGER, INTEGER);
DROP TABLE IF EXISTS x_auto_sync_schedules;
