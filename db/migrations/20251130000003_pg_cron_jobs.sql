-- migrate:up

-- ============================================================================
-- HELPER FUNCTIONS FOR CRON JOBS
-- ============================================================================

-- Function to log scheduled fetch jobs (called by pg_cron)
-- Actual fetching happens via Python/MCP, this just creates the job record
CREATE OR REPLACE FUNCTION schedule_fetch(p_source_name TEXT)
RETURNS INTEGER AS $$
DECLARE
    v_source_id INTEGER;
    v_job_id INTEGER;
BEGIN
    SELECT id INTO v_source_id FROM feed_sources WHERE name = p_source_name AND active = true;

    IF v_source_id IS NULL THEN
        RAISE NOTICE 'Source % not found or inactive', p_source_name;
        RETURN NULL;
    END IF;

    INSERT INTO fetch_jobs (source_id, status, metadata)
    VALUES (v_source_id, 'scheduled', jsonb_build_object('scheduled_by', 'pg_cron'))
    RETURNING id INTO v_job_id;

    -- Update last_fetch_at to prevent duplicate scheduling
    UPDATE feed_sources SET last_fetch_at = NOW() WHERE id = v_source_id;

    RETURN v_job_id;
END;
$$ LANGUAGE plpgsql;

-- Function to check for due sources and schedule them
CREATE OR REPLACE FUNCTION schedule_due_fetches()
RETURNS TABLE(source_name TEXT, job_id INTEGER) AS $$
BEGIN
    RETURN QUERY
    SELECT
        fs.name,
        schedule_fetch(fs.name)
    FROM feed_sources fs
    WHERE fs.active = true
      AND (
          fs.last_fetch_at IS NULL
          OR fs.last_fetch_at < NOW() - (fs.fetch_interval_minutes || ' minutes')::INTERVAL
      );
END;
$$ LANGUAGE plpgsql;

-- Function to clean up old fetch jobs (keep last 100 per source)
CREATE OR REPLACE FUNCTION cleanup_old_fetch_jobs()
RETURNS INTEGER AS $$
DECLARE
    v_deleted INTEGER := 0;
BEGIN
    WITH ranked_jobs AS (
        SELECT id, ROW_NUMBER() OVER (PARTITION BY source_id ORDER BY started_at DESC) as rn
        FROM fetch_jobs
    )
    DELETE FROM fetch_jobs
    WHERE id IN (SELECT id FROM ranked_jobs WHERE rn > 100);

    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

-- Function to archive old content items (older than 90 days, not in KB)
CREATE OR REPLACE FUNCTION archive_stale_content()
RETURNS INTEGER AS $$
DECLARE
    v_archived INTEGER := 0;
BEGIN
    -- For now, just mark as processed if old and not written to KB
    UPDATE content_items
    SET metadata = metadata || jsonb_build_object('archived', true, 'archived_at', NOW())
    WHERE fetched_at < NOW() - INTERVAL '90 days'
      AND kb_path IS NULL
      AND NOT (metadata ? 'archived');

    GET DIAGNOSTICS v_archived = ROW_COUNT;
    RETURN v_archived;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- PG_CRON JOB SCHEDULING
-- Note: Actual fetch execution happens via Python workers that poll fetch_jobs
-- ============================================================================

-- Main scheduler: Check for due fetches every 15 minutes
SELECT cron.schedule(
    'check-due-fetches',
    '*/15 * * * *',
    $$SELECT * FROM schedule_due_fetches()$$
);

-- Cleanup: Remove old fetch job records weekly (Sunday 3 AM)
SELECT cron.schedule(
    'cleanup-fetch-jobs',
    '0 3 * * 0',
    $$SELECT cleanup_old_fetch_jobs()$$
);

-- Archive: Mark stale content monthly (1st of month, 4 AM)
SELECT cron.schedule(
    'archive-stale-content',
    '0 4 1 * *',
    $$SELECT archive_stale_content()$$
);

-- ============================================================================
-- VIEW FOR MONITORING
-- ============================================================================

CREATE OR REPLACE VIEW v_source_status AS
SELECT
    fs.name,
    fs.source_type,
    fs.active,
    fs.fetch_interval_minutes,
    fs.last_fetch_at,
    CASE
        WHEN fs.last_fetch_at IS NULL THEN 'never'
        WHEN fs.last_fetch_at < NOW() - (fs.fetch_interval_minutes || ' minutes')::INTERVAL THEN 'overdue'
        ELSE 'ok'
    END as status,
    (SELECT COUNT(*) FROM content_items ci WHERE ci.source_id = fs.id) as total_items,
    (SELECT COUNT(*) FROM content_items ci WHERE ci.source_id = fs.id AND ci.kb_path IS NOT NULL) as kb_items,
    (SELECT COUNT(*) FROM fetch_jobs fj WHERE fj.source_id = fs.id AND fj.status = 'scheduled') as pending_jobs,
    array_agg(DISTINCT p.name) as profiles
FROM feed_sources fs
LEFT JOIN profile_sources ps ON ps.source_id = fs.id
LEFT JOIN profiles p ON p.id = ps.profile_id
GROUP BY fs.id
ORDER BY fs.name;


-- migrate:down

DROP VIEW IF EXISTS v_source_status;

-- Remove cron jobs
SELECT cron.unschedule('check-due-fetches');
SELECT cron.unschedule('cleanup-fetch-jobs');
SELECT cron.unschedule('archive-stale-content');

DROP FUNCTION IF EXISTS archive_stale_content();
DROP FUNCTION IF EXISTS cleanup_old_fetch_jobs();
DROP FUNCTION IF EXISTS schedule_due_fetches();
DROP FUNCTION IF EXISTS schedule_fetch(TEXT);
