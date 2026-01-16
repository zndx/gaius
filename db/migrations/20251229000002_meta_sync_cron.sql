-- migrate:up

-- ============================================================================
-- pg_cron Jobs for MetaAgent Observability
-- ============================================================================
-- Schedules:
-- - Aggregation jobs: :05, :10, :15 each hour (before cleanup)
-- - Cleanup jobs: :20, :25, :30 each hour (after aggregation)
-- - Daily cleanup: 04:00, 05:00 daily

-- ============================================================================
-- AGGREGATION JOBS (run before cleanup)
-- ============================================================================

-- GPU minute stats → hourly rollup (run at :05 each hour)
SELECT cron.schedule('meta-gpu-hourly-rollup', '5 * * * *', $$
    INSERT INTO meta.gpu_hourly_stats (hour, gpu_index, samples, memory_min_mb, memory_max_mb, memory_avg_mb, util_min_pct, util_max_pct, util_avg_pct, temp_max_c, power_avg_w)
    SELECT
        date_trunc('hour', minute) AS hour,
        gpu_index,
        SUM(samples),
        MIN(memory_min_mb),
        MAX(memory_max_mb),
        SUM(memory_avg_mb * samples) / NULLIF(SUM(samples), 0),
        MIN(util_min_pct),
        MAX(util_max_pct),
        SUM(util_avg_pct * samples) / NULLIF(SUM(samples), 0),
        MAX(temp_max_c),
        SUM(power_avg_w * samples) / NULLIF(SUM(samples), 0)
    FROM meta.gpu_minute_stats
    WHERE minute >= date_trunc('hour', NOW() - INTERVAL '2 hours')
      AND minute < date_trunc('hour', NOW())
    GROUP BY 1, 2
    ON CONFLICT (hour, gpu_index) DO UPDATE SET
        samples = EXCLUDED.samples,
        memory_min_mb = LEAST(meta.gpu_hourly_stats.memory_min_mb, EXCLUDED.memory_min_mb),
        memory_max_mb = GREATEST(meta.gpu_hourly_stats.memory_max_mb, EXCLUDED.memory_max_mb),
        memory_avg_mb = EXCLUDED.memory_avg_mb,
        util_min_pct = LEAST(meta.gpu_hourly_stats.util_min_pct, EXCLUDED.util_min_pct),
        util_max_pct = GREATEST(meta.gpu_hourly_stats.util_max_pct, EXCLUDED.util_max_pct),
        util_avg_pct = EXCLUDED.util_avg_pct,
        temp_max_c = GREATEST(meta.gpu_hourly_stats.temp_max_c, EXCLUDED.temp_max_c),
        power_avg_w = EXCLUDED.power_avg_w;
$$);


-- FMEA RPN timeseries aggregation (run at :10)
SELECT cron.schedule('meta-fmea-rpn-agg', '10 * * * *', $$
    INSERT INTO meta.fmea_rpn_timeseries (failure_mode_id, hour, avg_rpn, min_rpn, max_rpn, outcome_count, success_count, failure_count)
    SELECT
        failure_mode_id,
        date_trunc('hour', created_at) AS hour,
        AVG(rpn_score),
        MIN(rpn_score),
        MAX(rpn_score),
        COUNT(*),
        SUM(CASE WHEN success THEN 1 ELSE 0 END),
        SUM(CASE WHEN NOT success THEN 1 ELSE 0 END)
    FROM fmea_outcomes
    WHERE created_at >= date_trunc('hour', NOW() - INTERVAL '2 hours')
      AND created_at < date_trunc('hour', NOW())
    GROUP BY 1, 2
    ON CONFLICT (failure_mode_id, hour) DO UPDATE SET
        avg_rpn = EXCLUDED.avg_rpn,
        min_rpn = LEAST(meta.fmea_rpn_timeseries.min_rpn, EXCLUDED.min_rpn),
        max_rpn = GREATEST(meta.fmea_rpn_timeseries.max_rpn, EXCLUDED.max_rpn),
        outcome_count = EXCLUDED.outcome_count,
        success_count = EXCLUDED.success_count,
        failure_count = EXCLUDED.failure_count;
$$);


-- Lineage Sankey daily aggregation (run at :15)
SELECT cron.schedule('meta-sankey-daily-agg', '15 * * * *', $$
    INSERT INTO meta.lineage_sankey_agg (time_window, window_start, source_namespace, source_name, target_namespace, target_name, via_job, flow_count, computed_at)
    SELECT
        'daily',
        date_trunc('day', last_observed),
        split_part(source_dataset_id, ':', 1),
        split_part(source_dataset_id, ':', 2),
        split_part(target_dataset_id, ':', 1),
        split_part(target_dataset_id, ':', 2),
        COALESCE(via_job_id, ''),
        occurrence_count,
        NOW()
    FROM meta.data_dependencies
    WHERE last_observed > NOW() - INTERVAL '25 hours'
    ON CONFLICT (time_window, window_start, source_namespace, source_name, target_namespace, target_name, via_job)
    DO UPDATE SET
        flow_count = EXCLUDED.flow_count,
        computed_at = NOW();
$$);


-- Sync watermarks update (run at :17)
SELECT cron.schedule('meta-sync-watermarks', '17 * * * *', $$
    UPDATE meta.sync_watermarks SET
        last_sync_at = NOW(),
        records_synced = records_synced + 1
    WHERE sync_type IN ('lineage', 'operations', 'topology');
$$);


-- ============================================================================
-- CLEANUP JOBS (24h raw retention)
-- ============================================================================

-- GPU minute stats: keep 24h (run at :20 each hour)
SELECT cron.schedule('meta-gpu-minute-cleanup', '20 * * * *', $$
    DELETE FROM meta.gpu_minute_stats
    WHERE minute < NOW() - INTERVAL '24 hours';
$$);


-- MetaAgent query cache: expire old entries (run at :22)
SELECT cron.schedule('meta-query-cache-cleanup', '22 * * * *', $$
    DELETE FROM meta.metaagent_queries
    WHERE expires_at < NOW()
       OR (expires_at IS NULL AND created_at < NOW() - INTERVAL '24 hours');
$$);


-- Healing events detail: keep 7 days for detail events, sequence summaries longer (run at :25)
SELECT cron.schedule('meta-healing-cleanup', '25 * * * *', $$
    DELETE FROM healing_events
    WHERE created_at < NOW() - INTERVAL '7 days'
      AND event_type NOT IN ('sequence_started', 'sequence_completed');
$$);


-- FMEA occurrences: keep 30 days (run at :27)
SELECT cron.schedule('meta-fmea-occurrences-cleanup', '27 * * * *', $$
    DELETE FROM fmea_occurrences
    WHERE occurred_at < NOW() - INTERVAL '30 days';
$$);


-- ============================================================================
-- DAILY CLEANUP JOBS
-- ============================================================================

-- Content items without KB path: cleanup stale items (run at 05:00 daily)
SELECT cron.schedule('meta-content-cleanup', '0 5 * * *', $$
    DELETE FROM content_items
    WHERE fetched_at < NOW() - INTERVAL '7 days'
      AND kb_path IS NULL
      AND processed_at IS NULL
      AND NOT COALESCE(summary_excluded, FALSE);
$$);


-- Hourly aggregates: keep 30 days (run at 04:00 daily)
SELECT cron.schedule('meta-hourly-agg-cleanup', '0 4 * * *', $$
    DELETE FROM meta.gpu_hourly_stats WHERE hour < NOW() - INTERVAL '30 days';
    DELETE FROM meta.inference_hourly WHERE hour < NOW() - INTERVAL '30 days';
    DELETE FROM meta.fmea_rpn_timeseries WHERE hour < NOW() - INTERVAL '30 days';
    DELETE FROM meta.lineage_sankey_agg WHERE window_start < NOW() - INTERVAL '30 days';
$$);


-- Healing sequence summaries: keep 90 days (run at 04:30 daily)
SELECT cron.schedule('meta-healing-sequence-cleanup', '30 4 * * *', $$
    DELETE FROM healing_events
    WHERE created_at < NOW() - INTERVAL '90 days';
$$);


-- Old lineage data: keep 30 days (run at 04:45 daily)
SELECT cron.schedule('meta-lineage-cleanup', '45 4 * * *', $$
    DELETE FROM meta.data_dependencies
    WHERE last_observed < NOW() - INTERVAL '30 days';
$$);


-- ============================================================================
-- Helper function to check cron job status
-- ============================================================================

CREATE OR REPLACE FUNCTION meta.cron_job_status()
RETURNS TABLE (
    jobid bigint,
    jobname text,
    schedule text,
    active boolean,
    last_run timestamptz,
    last_status text
) AS $$
    SELECT
        j.jobid,
        j.jobname,
        j.schedule,
        j.active,
        r.start_time as last_run,
        COALESCE(r.status, 'never_run') as last_status
    FROM cron.job j
    LEFT JOIN LATERAL (
        SELECT start_time, status
        FROM cron.job_run_details
        WHERE jobid = j.jobid
        ORDER BY start_time DESC
        LIMIT 1
    ) r ON TRUE
    WHERE j.jobname LIKE 'meta-%'
    ORDER BY j.jobname;
$$ LANGUAGE SQL;

COMMENT ON FUNCTION meta.cron_job_status IS 'Check status of meta observability cron jobs';


-- migrate:down

-- Remove cron jobs
SELECT cron.unschedule('meta-gpu-hourly-rollup');
SELECT cron.unschedule('meta-fmea-rpn-agg');
SELECT cron.unschedule('meta-sankey-daily-agg');
SELECT cron.unschedule('meta-sync-watermarks');
SELECT cron.unschedule('meta-gpu-minute-cleanup');
SELECT cron.unschedule('meta-query-cache-cleanup');
SELECT cron.unschedule('meta-healing-cleanup');
SELECT cron.unschedule('meta-fmea-occurrences-cleanup');
SELECT cron.unschedule('meta-content-cleanup');
SELECT cron.unschedule('meta-hourly-agg-cleanup');
SELECT cron.unschedule('meta-healing-sequence-cleanup');
SELECT cron.unschedule('meta-lineage-cleanup');

DROP FUNCTION IF EXISTS meta.cron_job_status();
