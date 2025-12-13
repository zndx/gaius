-- migrate:up

-- ============================================================================
-- pg_cron Periodic Tasks for Long-Term Evolution
-- ============================================================================
-- This migration configures pg_cron jobs for autonomous operation on
-- timescales of weeks and months. Key design principles:
--
-- 1. Content diversity as primary driver (not fixed time intervals)
-- 2. Extended cadences for slow-burn improvement
-- 3. Jitter to prevent thundering herd
-- 4. Complement GPU-idle reactive triggers, don't replace them
-- ============================================================================

-- ============================================================================
-- UPDATE EXISTING JOBS (extend intervals, add jitter)
-- ============================================================================

-- Remove old feed check job (was every 15 min via schedule_due_fetches)
SELECT cron.unschedule('check-due-fetches');

-- Feed Source Checks: ~4 hours with jitter (6x daily)
-- Minute offset (17) spreads load away from the hour
SELECT cron.schedule(
    'check-due-fetches',
    '17 */4 * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('feed_check', '{}', 'pg_cron',
              NOW() + (random() * INTERVAL '30 minutes'))$$
);

-- Remove old cognition job (was every 4 hours at minute 0)
SELECT cron.unschedule('cognition-periodic');

-- Cognition Cycles: 6x daily with jitter (every 4 hours at minute 43)
SELECT cron.schedule(
    'cognition-periodic',
    '43 0,4,8,12,16,20 * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('cognition_cycle', '{"trigger": "scheduled"}', 'pg_cron',
              NOW() + (random() * INTERVAL '45 minutes'))$$
);

-- ============================================================================
-- CONTENT DIVERSITY FUNCTION
-- Primary driver of evolution - checks if enough new content has accumulated
-- ============================================================================

CREATE OR REPLACE FUNCTION check_content_diversity()
RETURNS TABLE(
    should_trigger BOOLEAN,
    reason TEXT,
    new_content_items INTEGER,
    new_thoughts INTEGER,
    domains_active INTEGER,
    external_ingested INTEGER,
    days_since_last INTEGER
) AS $$
DECLARE
    last_evolution TIMESTAMPTZ;
    v_new_content INTEGER;
    v_new_thoughts INTEGER;
    v_domains INTEGER;
    v_external INTEGER;
    v_days INTEGER;
    -- Configurable thresholds (extended for long-term operation)
    min_content_items INTEGER := 100;  -- New content items with kb_path
    min_thoughts INTEGER := 50;        -- New cognition thoughts
    min_domains INTEGER := 3;          -- Unique domains active
    min_external INTEGER := 50;        -- External content ingested
    min_days INTEGER := 7;             -- Minimum days between cycles
    max_days INTEGER := 30;            -- Force trigger after this
BEGIN
    -- Find last successful evolution cycle
    SELECT MAX(completed_at) INTO last_evolution
    FROM evolution_cycles
    WHERE success = true;

    -- Default to 30 days ago if no evolution yet
    last_evolution := COALESCE(last_evolution, NOW() - INTERVAL '30 days');

    -- Count new content items written to KB
    SELECT COUNT(*) INTO v_new_content
    FROM content_items
    WHERE fetched_at > last_evolution
      AND kb_path IS NOT NULL;

    -- Count new cognition thoughts
    SELECT COUNT(*) INTO v_new_thoughts
    FROM cognition_thoughts
    WHERE created_at > last_evolution;

    -- Count active domains from activity events
    SELECT COUNT(DISTINCT domain) INTO v_domains
    FROM activity_events
    WHERE created_at > last_evolution
      AND domain IS NOT NULL;

    -- Count external content ingested (processed_at indicates ingestion)
    SELECT COUNT(*) INTO v_external
    FROM content_items
    WHERE processed_at > last_evolution;

    -- Days since last evolution
    v_days := EXTRACT(DAY FROM NOW() - last_evolution)::INTEGER;

    -- Determine if we should trigger
    IF v_days >= max_days THEN
        RETURN QUERY SELECT true, 'Max days exceeded - forcing evolution'::TEXT,
            v_new_content, v_new_thoughts, v_domains, v_external, v_days;
    ELSIF v_days >= min_days AND
          v_new_content >= min_content_items AND
          v_domains >= min_domains AND
          v_external >= min_external THEN
        RETURN QUERY SELECT true, 'Diversity thresholds met'::TEXT,
            v_new_content, v_new_thoughts, v_domains, v_external, v_days;
    ELSE
        RETURN QUERY SELECT false,
            format('Waiting: content=%s/%s, thoughts=%s/%s, domains=%s/%s, external=%s/%s, days=%s/%s',
                   v_new_content, min_content_items,
                   v_new_thoughts, min_thoughts,
                   v_domains, min_domains,
                   v_external, min_external,
                   v_days, min_days)::TEXT,
            v_new_content, v_new_thoughts, v_domains, v_external, v_days;
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION check_content_diversity IS
'Checks if enough new content has accumulated to trigger evolution.
Returns should_trigger=true if diversity thresholds are met or max_days exceeded.
Called twice daily by pg_cron as the PRIMARY driver of evolution.';

-- ============================================================================
-- DIVERSITY THRESHOLD CHECKING (Primary driver of evolution)
-- ============================================================================

-- Content Diversity Check: Twice daily (6 AM and 6 PM)
-- This is the PRIMARY driver - checks if enough new content has accumulated
SELECT cron.schedule(
    'content-diversity-check',
    '0 6,18 * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('content_diversity_check', '{}', 'pg_cron', NOW())$$
);

-- ============================================================================
-- WEEKLY CADENCE
-- ============================================================================

-- Evolution: Sunday 3 AM (backup if diversity thresholds not triggering)
SELECT cron.schedule(
    'evolution-weekly',
    '0 3 * * 0',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('evolution_cycle',
              '{"agents": ["leader", "risk", "critic", "opportunity", "domain"], "num_items": 10, "source": "weekly_scheduled"}',
              'pg_cron', NOW())$$
);

-- Weekly Summary: Sunday 8 PM
SELECT cron.schedule(
    'weekly-summary',
    '0 20 * * 0',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('weekly_summary', '{"use_llm": true, "write_to_kb": true}', 'pg_cron', NOW())$$
);

-- Research Processing: Sunday 4:30 AM
SELECT cron.schedule(
    'research-processing-weekly',
    '30 4 * * 0',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('research_processing', '{}', 'pg_cron', NOW())$$
);

-- ============================================================================
-- BI-WEEKLY CADENCE
-- ============================================================================

-- Content Summarization: Monday and Thursday 5 AM
SELECT cron.schedule(
    'content-summarization-biweekly',
    '0 5 * * 1,4',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('content_summarization', '{"batch_size": 20}', 'pg_cron', NOW())$$
);

-- TDA Computation: Monday and Thursday 6 AM
SELECT cron.schedule(
    'tda-biweekly',
    '0 6 * * 1,4',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('tda_computation', '{}', 'pg_cron', NOW())$$
);

-- ============================================================================
-- MONTHLY CADENCE
-- ============================================================================

-- Task Ideation: 1st of month, 2 AM
SELECT cron.schedule(
    'task-ideation-monthly',
    '0 2 1 * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('task_ideation', '{"max_concepts": 5, "novelty_threshold": 0.4}', 'pg_cron', NOW())$$
);

-- ============================================================================
-- QUARTERLY CADENCE
-- ============================================================================

-- Model Merging: Quarterly (Jan, Apr, Jul, Oct 1st at 4 AM)
SELECT cron.schedule(
    'model-merge-quarterly',
    '0 4 1 1,4,7,10 *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('model_merge', '{"agents": null}', 'pg_cron', NOW())$$
);

-- Held-Out Refresh: Quarterly (Jan, Apr, Jul, Oct 1st at 3 AM)
SELECT cron.schedule(
    'held-out-refresh-quarterly',
    '0 3 1 1,4,7,10 *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('held_out_refresh', '{"sample_size": 100}', 'pg_cron', NOW())$$
);

-- Merge Lineage Cleanup: Quarterly (Jan, Apr, Jul, Oct 1st at 5 AM)
SELECT cron.schedule(
    'merge-lineage-cleanup-quarterly',
    '0 5 1 1,4,7,10 *',
    $$DELETE FROM lineage_events
      WHERE event_time < NOW() - INTERVAL '365 days'
      AND job_name = 'model_merge'$$
);

-- Evolution Cycles Archival: Quarterly
SELECT cron.schedule(
    'evolution-cycles-archival-quarterly',
    '0 5 1 1,4,7,10 *',
    $$UPDATE evolution_cycles
      SET archived = true
      WHERE completed_at < NOW() - INTERVAL '180 days'
      AND archived = false$$
);

-- ============================================================================
-- MONITORING FUNCTION
-- ============================================================================

-- Use SECURITY DEFINER function to access cron.job with elevated privileges
-- This allows the gaius role to view scheduled jobs without direct cron schema access
CREATE OR REPLACE FUNCTION get_scheduled_jobs_status()
RETURNS TABLE(
    jobid bigint,
    jobname text,
    schedule text,
    command text,
    nodename text,
    active boolean
) AS $$
BEGIN
    -- Check if cron schema exists (pg_cron installed)
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'cron') THEN
        RETURN QUERY
        SELECT
            j.jobid,
            j.jobname::text,
            j.schedule::text,
            j.command::text,
            j.nodename::text,
            j.active
        FROM cron.job j
        WHERE j.database = current_database()
        ORDER BY j.jobname;
    ELSE
        -- Return empty if pg_cron not installed
        RETURN;
    END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION get_scheduled_jobs_status IS
'Returns all pg_cron jobs for this database. Use: SELECT * FROM get_scheduled_jobs_status();
Uses SECURITY DEFINER to allow access regardless of cron schema permissions.';

-- Create a convenience view that calls the function
CREATE OR REPLACE VIEW v_scheduled_jobs_status AS
SELECT * FROM get_scheduled_jobs_status();

COMMENT ON VIEW v_scheduled_jobs_status IS
'View of all pg_cron jobs for this database. Use SELECT * FROM v_scheduled_jobs_status;
Backed by get_scheduled_jobs_status() function with SECURITY DEFINER.';

-- Grant permissions to gaius role
GRANT EXECUTE ON FUNCTION get_scheduled_jobs_status() TO gaius;
GRANT SELECT ON v_scheduled_jobs_status TO gaius;


-- migrate:down

-- Remove all new cron jobs
SELECT cron.unschedule('content-diversity-check');
SELECT cron.unschedule('evolution-weekly');
SELECT cron.unschedule('weekly-summary');
SELECT cron.unschedule('research-processing-weekly');
SELECT cron.unschedule('content-summarization-biweekly');
SELECT cron.unschedule('tda-biweekly');
SELECT cron.unschedule('task-ideation-monthly');
SELECT cron.unschedule('model-merge-quarterly');
SELECT cron.unschedule('held-out-refresh-quarterly');
SELECT cron.unschedule('merge-lineage-cleanup-quarterly');
SELECT cron.unschedule('evolution-cycles-archival-quarterly');

-- Restore original schedules for modified jobs
SELECT cron.unschedule('check-due-fetches');
SELECT cron.schedule(
    'check-due-fetches',
    '*/15 * * * *',
    $$SELECT * FROM schedule_due_fetches()$$
);

SELECT cron.unschedule('cognition-periodic');
SELECT cron.schedule(
    'cognition-periodic',
    '0 */4 * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('cognition_cycle', '{"trigger": "scheduled"}', 'pg_cron', NOW())$$
);

-- Drop function and view
DROP VIEW IF EXISTS v_scheduled_jobs_status;
DROP FUNCTION IF EXISTS get_scheduled_jobs_status();
DROP FUNCTION IF EXISTS check_content_diversity();
