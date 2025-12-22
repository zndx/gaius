-- migrate:up

-- ============================================================================
-- DOC SYNC FUNCTIONS
-- These functions are called by pg_cron or manually via CLI
-- ============================================================================

-- Check if a doc archive needs re-sync based on content hash
CREATE OR REPLACE FUNCTION check_archive_changed(
    p_source_id INTEGER,
    p_archive_url TEXT,
    p_new_hash TEXT
) RETURNS BOOLEAN AS $$
DECLARE
    v_old_hash TEXT;
BEGIN
    SELECT content_hash INTO v_old_hash
    FROM doc_archives
    WHERE source_id = p_source_id AND archive_url = p_archive_url;

    IF v_old_hash IS NULL THEN
        RETURN TRUE;  -- New archive, needs sync
    END IF;

    RETURN v_old_hash != p_new_hash;  -- Changed if hash differs
END;
$$ LANGUAGE plpgsql;

-- Mark an archive as processing
CREATE OR REPLACE FUNCTION start_archive_sync(
    p_source_id INTEGER,
    p_archive_url TEXT,
    p_version TEXT DEFAULT NULL
) RETURNS INTEGER AS $$
DECLARE
    v_archive_id INTEGER;
BEGIN
    INSERT INTO doc_archives (source_id, archive_url, version, status)
    VALUES (p_source_id, p_archive_url, p_version, 'downloading')
    ON CONFLICT (source_id, archive_url)
    DO UPDATE SET
        status = 'downloading',
        version = COALESCE(p_version, doc_archives.version),
        retry_count = doc_archives.retry_count + 1
    RETURNING id INTO v_archive_id;

    RETURN v_archive_id;
END;
$$ LANGUAGE plpgsql;

-- Mark an archive as completed
CREATE OR REPLACE FUNCTION complete_archive_sync(
    p_archive_id INTEGER,
    p_content_hash TEXT,
    p_pages_extracted INTEGER,
    p_kb_path_prefix TEXT
) RETURNS VOID AS $$
BEGIN
    UPDATE doc_archives SET
        status = 'completed',
        content_hash = p_content_hash,
        pages_extracted = p_pages_extracted,
        kb_path_prefix = p_kb_path_prefix,
        processed_at = NOW(),
        error_message = NULL
    WHERE id = p_archive_id;
END;
$$ LANGUAGE plpgsql;

-- Mark an archive as failed
CREATE OR REPLACE FUNCTION fail_archive_sync(
    p_archive_id INTEGER,
    p_error_message TEXT
) RETURNS VOID AS $$
BEGIN
    UPDATE doc_archives SET
        status = 'failed',
        error_message = p_error_message,
        processed_at = NOW()
    WHERE id = p_archive_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- QUARTERLY ARCHIVE ROTATION
-- Move old docs to archive/ on version change
-- ============================================================================

-- Get the current quarter string (e.g., '2025Q1')
CREATE OR REPLACE FUNCTION get_current_quarter() RETURNS TEXT AS $$
BEGIN
    RETURN EXTRACT(YEAR FROM NOW())::TEXT || 'Q' ||
           CEIL(EXTRACT(MONTH FROM NOW()) / 3.0)::TEXT;
END;
$$ LANGUAGE plpgsql;

-- Rotate archives for a specific domain
CREATE OR REPLACE FUNCTION rotate_domain_archive(
    p_archive_id INTEGER,
    p_source_kb_path TEXT,
    p_archive_kb_path TEXT
) RETURNS INTEGER AS $$
DECLARE
    v_rotation_id INTEGER;
    v_quarter TEXT;
    v_version TEXT;
BEGIN
    v_quarter := get_current_quarter();

    -- Get version from archive
    SELECT version INTO v_version
    FROM doc_archives
    WHERE id = p_archive_id;

    -- Create rotation record
    INSERT INTO archive_rotations (
        quarter, doc_archive_id, source_kb_path, archive_kb_path,
        version_at_archive, status
    )
    VALUES (
        v_quarter, p_archive_id, p_source_kb_path, p_archive_kb_path,
        v_version, 'pending'
    )
    RETURNING id INTO v_rotation_id;

    RETURN v_rotation_id;
END;
$$ LANGUAGE plpgsql;

-- Complete a rotation (called after files are moved)
CREATE OR REPLACE FUNCTION complete_archive_rotation(
    p_rotation_id INTEGER,
    p_files_moved INTEGER
) RETURNS VOID AS $$
BEGIN
    UPDATE archive_rotations SET
        status = 'completed',
        files_moved = p_files_moved,
        completed_at = NOW()
    WHERE id = p_rotation_id;
END;
$$ LANGUAGE plpgsql;

-- Main function to check and schedule quarterly rotations
-- Called by pg_cron on 1st of quarter
CREATE OR REPLACE FUNCTION rotate_quarterly_archives() RETURNS JSONB AS $$
DECLARE
    v_quarter TEXT;
    v_archive RECORD;
    v_rotation_id INTEGER;
    v_results JSONB := '[]'::JSONB;
BEGIN
    v_quarter := get_current_quarter();

    -- Find all completed archives that haven't been rotated this quarter
    FOR v_archive IN
        SELECT da.id, da.kb_path_prefix, da.version, da.content_hash,
               da.source_id, fs.name as source_name
        FROM doc_archives da
        JOIN feed_sources fs ON da.source_id = fs.id
        WHERE da.status = 'completed'
          AND da.kb_path_prefix IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM archive_rotations ar
              WHERE ar.doc_archive_id = da.id
                AND ar.quarter = v_quarter
          )
    LOOP
        -- Create rotation record for each
        v_rotation_id := rotate_domain_archive(
            v_archive.id,
            v_archive.kb_path_prefix,
            'archive/' || v_quarter || '/' ||
                REPLACE(v_archive.kb_path_prefix, 'current/', '')
        );

        v_results := v_results || jsonb_build_object(
            'archive_id', v_archive.id,
            'rotation_id', v_rotation_id,
            'source', v_archive.source_name,
            'source_path', v_archive.kb_path_prefix,
            'version', v_archive.version
        );
    END LOOP;

    RETURN jsonb_build_object(
        'quarter', v_quarter,
        'rotations_scheduled', jsonb_array_length(v_results),
        'details', v_results
    );
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- DOC SYNC STATUS VIEW
-- Useful for monitoring and CLI commands
-- ============================================================================

CREATE OR REPLACE VIEW doc_sync_status AS
SELECT
    fs.name as source_name,
    fs.source_type,
    da.archive_url,
    da.version,
    da.status,
    da.pages_extracted,
    da.kb_path_prefix,
    da.processed_at,
    da.error_message,
    CASE
        WHEN da.status = 'completed' THEN
            EXTRACT(EPOCH FROM (NOW() - da.processed_at)) / 86400
        ELSE NULL
    END as days_since_sync
FROM doc_archives da
JOIN feed_sources fs ON da.source_id = fs.id
ORDER BY da.processed_at DESC NULLS LAST;

-- ============================================================================
-- PG_CRON JOBS (if pg_cron extension is available)
-- Note: pg_cron may not be available in all environments
-- These jobs can be created manually when pg_cron is enabled
-- ============================================================================

-- Store cron job definitions for manual setup
-- The actual cron.schedule() calls should be run by an admin with pg_cron enabled

CREATE TABLE IF NOT EXISTS scheduled_jobs_config (
    id SERIAL PRIMARY KEY,
    job_name TEXT NOT NULL UNIQUE,
    schedule TEXT NOT NULL,         -- cron expression
    function_call TEXT NOT NULL,    -- SQL to execute
    description TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE scheduled_jobs_config IS
    'Stores pg_cron job definitions. Apply with: SELECT cron.schedule(job_name, schedule, function_call) for each enabled row.';

-- Insert job definitions (not actually scheduled yet)
INSERT INTO scheduled_jobs_config (job_name, schedule, function_call, description) VALUES
(
    'quarterly-archive-rotation',
    '0 3 1 1,4,7,10 *',  -- 3 AM on 1st of Jan/Apr/Jul/Oct
    'SELECT rotate_quarterly_archives()',
    'Rotate docs from current/ to archive/<quarter>/ on version change'
),
(
    'weekly-sync-check',
    '0 2 * * 0',  -- 2 AM every Sunday
    'SELECT check_stale_archives()',
    'Check for archives that need re-sync (not yet implemented)'
)
ON CONFLICT (job_name) DO UPDATE SET
    schedule = EXCLUDED.schedule,
    function_call = EXCLUDED.function_call,
    description = EXCLUDED.description;

-- Helper function to apply pg_cron jobs (run as superuser when pg_cron is available)
CREATE OR REPLACE FUNCTION apply_cron_jobs() RETURNS TEXT AS $$
DECLARE
    v_job RECORD;
    v_count INTEGER := 0;
BEGIN
    -- Check if pg_cron is available
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        RETURN 'pg_cron extension not installed. Jobs stored in scheduled_jobs_config table.';
    END IF;

    FOR v_job IN SELECT * FROM scheduled_jobs_config WHERE enabled LOOP
        EXECUTE format(
            'SELECT cron.schedule(%L, %L, %L)',
            v_job.job_name,
            v_job.schedule,
            v_job.function_call
        );
        v_count := v_count + 1;
    END LOOP;

    RETURN format('Applied %s pg_cron jobs', v_count);
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- DOC SYNC CLI HELPERS
-- Functions for /docs-sync CLI command
-- ============================================================================

-- Get pending/failed archives for retry
CREATE OR REPLACE FUNCTION get_archives_needing_sync() RETURNS TABLE (
    archive_id INTEGER,
    source_name TEXT,
    archive_url TEXT,
    status TEXT,
    retry_count INTEGER,
    last_error TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        da.id,
        fs.name,
        da.archive_url,
        da.status,
        da.retry_count,
        da.error_message
    FROM doc_archives da
    JOIN feed_sources fs ON da.source_id = fs.id
    WHERE da.status IN ('discovered', 'failed')
      AND (da.retry_count < 3 OR da.status = 'discovered')
    ORDER BY da.discovered_at;
END;
$$ LANGUAGE plpgsql;

-- Get summary of doc sync status
CREATE OR REPLACE FUNCTION get_doc_sync_summary() RETURNS JSONB AS $$
DECLARE
    v_result JSONB;
BEGIN
    SELECT jsonb_build_object(
        'total_archives', COUNT(*),
        'by_status', jsonb_object_agg(status, cnt),
        'total_pages', SUM(pages_extracted),
        'last_sync', MAX(processed_at)
    ) INTO v_result
    FROM (
        SELECT status, COUNT(*) as cnt, SUM(pages_extracted) as pages_extracted,
               MAX(processed_at) as processed_at
        FROM doc_archives
        GROUP BY status
    ) stats;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql;


-- migrate:down

DROP FUNCTION IF EXISTS get_doc_sync_summary();
DROP FUNCTION IF EXISTS get_archives_needing_sync();
DROP FUNCTION IF EXISTS apply_cron_jobs();
DROP TABLE IF EXISTS scheduled_jobs_config;
DROP VIEW IF EXISTS doc_sync_status;
DROP FUNCTION IF EXISTS rotate_quarterly_archives();
DROP FUNCTION IF EXISTS complete_archive_rotation(INTEGER, INTEGER);
DROP FUNCTION IF EXISTS rotate_domain_archive(INTEGER, TEXT, TEXT);
DROP FUNCTION IF EXISTS get_current_quarter();
DROP FUNCTION IF EXISTS fail_archive_sync(INTEGER, TEXT);
DROP FUNCTION IF EXISTS complete_archive_sync(INTEGER, TEXT, INTEGER, TEXT);
DROP FUNCTION IF EXISTS start_archive_sync(INTEGER, TEXT, TEXT);
DROP FUNCTION IF EXISTS check_archive_changed(INTEGER, TEXT, TEXT);
