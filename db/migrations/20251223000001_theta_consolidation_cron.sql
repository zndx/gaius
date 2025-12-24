-- migrate:up

-- ============================================================================
-- THETA CONSOLIDATION TRACKING
-- ============================================================================

-- Table to track consolidation cycles
CREATE TABLE IF NOT EXISTS theta_consolidation_runs (
    id SERIAL PRIMARY KEY,
    slice_id TEXT NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,

    -- NVAR signal
    urgency REAL,
    drift REAL,

    -- Results
    candidates_evaluated INTEGER DEFAULT 0,
    candidates_selected INTEGER DEFAULT 0,
    documents_augmented INTEGER DEFAULT 0,

    -- Status
    status TEXT DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'running', 'completed', 'failed')),
    error TEXT,

    -- Metadata
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_theta_consolidation_slice ON theta_consolidation_runs(slice_id);
CREATE INDEX idx_theta_consolidation_status ON theta_consolidation_runs(status);
CREATE INDEX idx_theta_consolidation_started ON theta_consolidation_runs(started_at);

-- Partial unique index to prevent duplicate pending jobs per slice
CREATE UNIQUE INDEX idx_theta_unique_pending
    ON theta_consolidation_runs(slice_id)
    WHERE status IN ('scheduled', 'running');

-- ============================================================================
-- CONSOLIDATION HELPER FUNCTIONS
-- ============================================================================

-- Function to schedule a consolidation cycle
-- Returns the job ID if scheduled, NULL if already pending
CREATE OR REPLACE FUNCTION schedule_theta_consolidation(p_slice_id TEXT DEFAULT NULL)
RETURNS INTEGER AS $$
DECLARE
    v_slice_id TEXT;
    v_job_id INTEGER;
    v_existing INTEGER;
BEGIN
    -- Default to current week if not specified
    v_slice_id := COALESCE(p_slice_id, to_char(NOW(), 'YYYY-"W"IW'));

    -- Check for existing pending job for this slice
    SELECT id INTO v_existing
    FROM theta_consolidation_runs
    WHERE slice_id = v_slice_id
      AND status IN ('scheduled', 'running');

    IF v_existing IS NOT NULL THEN
        RAISE NOTICE 'Consolidation already pending for slice %', v_slice_id;
        RETURN NULL;
    END IF;

    -- Create new scheduled job
    INSERT INTO theta_consolidation_runs (slice_id, status, metadata)
    VALUES (v_slice_id, 'scheduled', jsonb_build_object('scheduled_by', 'pg_cron', 'scheduled_at', NOW()))
    RETURNING id INTO v_job_id;

    RAISE NOTICE 'Scheduled consolidation job % for slice %', v_job_id, v_slice_id;
    RETURN v_job_id;
END;
$$ LANGUAGE plpgsql;

-- Function to mark a consolidation job as started
CREATE OR REPLACE FUNCTION start_theta_consolidation(p_job_id INTEGER)
RETURNS BOOLEAN AS $$
BEGIN
    UPDATE theta_consolidation_runs
    SET status = 'running',
        started_at = NOW()
    WHERE id = p_job_id AND status = 'scheduled';

    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- Function to complete a consolidation job
CREATE OR REPLACE FUNCTION complete_theta_consolidation(
    p_job_id INTEGER,
    p_urgency REAL DEFAULT NULL,
    p_drift REAL DEFAULT NULL,
    p_candidates_evaluated INTEGER DEFAULT 0,
    p_candidates_selected INTEGER DEFAULT 0,
    p_documents_augmented INTEGER DEFAULT 0,
    p_error TEXT DEFAULT NULL
)
RETURNS BOOLEAN AS $$
BEGIN
    UPDATE theta_consolidation_runs
    SET status = CASE WHEN p_error IS NULL THEN 'completed' ELSE 'failed' END,
        completed_at = NOW(),
        urgency = p_urgency,
        drift = p_drift,
        candidates_evaluated = p_candidates_evaluated,
        candidates_selected = p_candidates_selected,
        documents_augmented = p_documents_augmented,
        error = p_error,
        metadata = metadata || jsonb_build_object('duration_ms', EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000)
    WHERE id = p_job_id AND status = 'running';

    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- Function to get pending consolidation jobs
CREATE OR REPLACE FUNCTION get_pending_theta_consolidations()
RETURNS TABLE(job_id INTEGER, slice_id TEXT, scheduled_at TIMESTAMP WITH TIME ZONE) AS $$
BEGIN
    RETURN QUERY
    SELECT id, t.slice_id, t.started_at
    FROM theta_consolidation_runs t
    WHERE status = 'scheduled'
    ORDER BY started_at ASC
    LIMIT 10;  -- Process up to 10 at a time
END;
$$ LANGUAGE plpgsql;

-- Function to clean up old consolidation records (keep last 100)
CREATE OR REPLACE FUNCTION cleanup_theta_consolidation_history()
RETURNS INTEGER AS $$
DECLARE
    v_deleted INTEGER := 0;
BEGIN
    WITH ranked_runs AS (
        SELECT id, ROW_NUMBER() OVER (ORDER BY started_at DESC) as rn
        FROM theta_consolidation_runs
        WHERE status IN ('completed', 'failed')
    )
    DELETE FROM theta_consolidation_runs
    WHERE id IN (SELECT id FROM ranked_runs WHERE rn > 100);

    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- PG_CRON JOB SCHEDULING
-- ============================================================================

-- Schedule weekly consolidation (Monday 6 AM - after overnight evolution completes)
-- This creates a scheduled job; the actual execution happens via gRPC in gaius-engine
SELECT cron.schedule(
    'theta-weekly-consolidation',
    '0 6 * * 1',  -- Every Monday at 6 AM
    $$SELECT schedule_theta_consolidation()$$
);

-- Cleanup old consolidation records (monthly, 1st at 5 AM)
SELECT cron.schedule(
    'cleanup-theta-consolidation',
    '0 5 1 * *',
    $$SELECT cleanup_theta_consolidation_history()$$
);

-- ============================================================================
-- VIEW FOR MONITORING
-- ============================================================================

CREATE OR REPLACE VIEW v_theta_consolidation_status AS
SELECT
    slice_id,
    status,
    started_at,
    completed_at,
    urgency,
    drift,
    candidates_evaluated,
    candidates_selected,
    documents_augmented,
    error,
    EXTRACT(EPOCH FROM (COALESCE(completed_at, NOW()) - started_at)) as duration_seconds
FROM theta_consolidation_runs
ORDER BY started_at DESC
LIMIT 20;

-- ============================================================================
-- GRANTS
-- ============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON theta_consolidation_runs TO gaius;
GRANT USAGE, SELECT ON SEQUENCE theta_consolidation_runs_id_seq TO gaius;
GRANT SELECT ON v_theta_consolidation_status TO gaius;

-- migrate:down

-- Remove cron jobs
SELECT cron.unschedule('theta-weekly-consolidation');
SELECT cron.unschedule('cleanup-theta-consolidation');

DROP VIEW IF EXISTS v_theta_consolidation_status;
DROP FUNCTION IF EXISTS cleanup_theta_consolidation_history();
DROP FUNCTION IF EXISTS get_pending_theta_consolidations();
DROP FUNCTION IF EXISTS complete_theta_consolidation(INTEGER, REAL, REAL, INTEGER, INTEGER, INTEGER, TEXT);
DROP FUNCTION IF EXISTS start_theta_consolidation(INTEGER);
DROP FUNCTION IF EXISTS schedule_theta_consolidation(TEXT);
DROP TABLE IF EXISTS theta_consolidation_runs;
