-- migrate:up
-- Metabase-friendly views for Ambient Workload and AgendaTracker metrics
-- These views are designed for dashboard queries in Metabase

-- ============================================================================
-- Ambient Cycle Metrics (Hourly Aggregates)
-- ============================================================================

CREATE OR REPLACE VIEW meta.ambient_cycle_metrics AS
SELECT
    date_trunc('hour', ai.created_at) AS hour,
    ai.agenda_type::text AS agenda_type,
    ai.status::text AS status,
    ai.control_mode::text AS control_mode,
    COUNT(*) AS cycle_count,
    AVG(ai.actual_duration_ms)::integer AS avg_duration_ms,
    AVG(ai.makespan_variance_pct)::real AS avg_variance_pct,
    SUM(CASE WHEN ai.status = 'fulfilled' THEN 1 ELSE 0 END)::integer AS fulfilled_count,
    SUM(CASE WHEN ai.status = 'degraded' THEN 1 ELSE 0 END)::integer AS degraded_count,
    SUM(CASE WHEN ai.status = 'failed' THEN 1 ELSE 0 END)::integer AS failed_count,
    SUM(CASE WHEN ai.control_mode != 'positive' THEN 1 ELSE 0 END)::integer AS non_positive_count
FROM agenda_incidents ai
GROUP BY 1, 2, 3, 4
ORDER BY 1 DESC;

COMMENT ON VIEW meta.ambient_cycle_metrics IS 'Hourly aggregate metrics for Metabase ambient workload dashboards';

-- ============================================================================
-- Agenda Phase Metrics (Hourly Aggregates)
-- ============================================================================

CREATE OR REPLACE VIEW meta.agenda_phase_metrics AS
SELECT
    date_trunc('hour', ape.created_at) AS hour,
    ape.phase_name,
    ape.event_type,
    ape.control_mode::text AS control_mode,
    COUNT(*) AS event_count,
    AVG(ape.actual_duration_ms)::integer AS avg_duration_ms,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY ape.actual_duration_ms)::integer AS p50_duration_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY ape.actual_duration_ms)::integer AS p95_duration_ms,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY ape.actual_duration_ms)::integer AS p99_duration_ms
FROM agenda_phase_events ape
WHERE ape.actual_duration_ms IS NOT NULL
GROUP BY 1, 2, 3, 4
ORDER BY 1 DESC;

COMMENT ON VIEW meta.agenda_phase_metrics IS 'Hourly phase-level metrics with latency percentiles for Metabase';

-- ============================================================================
-- Endpoint Transition Metrics (Hourly Aggregates)
-- ============================================================================

CREATE OR REPLACE VIEW meta.endpoint_transition_metrics AS
SELECT
    date_trunc('hour', ape.created_at) AS hour,
    ape.endpoint,
    ape.endpoint_from_state,
    ape.endpoint_to_state,
    ape.control_mode::text AS control_mode,
    COUNT(*) AS transition_count,
    SUM(CASE WHEN ape.control_mode = 'positive' THEN 1 ELSE 0 END)::integer AS positive_count,
    SUM(CASE WHEN ape.control_mode = 'failure_recovery' THEN 1 ELSE 0 END)::integer AS failure_recovery_count,
    SUM(CASE WHEN ape.control_mode = 'restart_recovery' THEN 1 ELSE 0 END)::integer AS restart_recovery_count
FROM agenda_phase_events ape
WHERE ape.endpoint IS NOT NULL
  AND ape.endpoint_from_state IS NOT NULL
  AND ape.endpoint_to_state IS NOT NULL
GROUP BY 1, 2, 3, 4, 5
ORDER BY 1 DESC;

COMMENT ON VIEW meta.endpoint_transition_metrics IS 'Endpoint state transitions by control mode for Metabase';

-- ============================================================================
-- Agenda Resolution Time Series (Daily)
-- ============================================================================

CREATE OR REPLACE VIEW meta.agenda_resolution_daily AS
SELECT
    date_trunc('day', ai.resolved_at) AS day,
    ai.agenda_type::text AS agenda_type,
    COUNT(*) AS total_resolved,
    SUM(CASE WHEN ai.status = 'fulfilled' THEN 1 ELSE 0 END)::integer AS fulfilled_count,
    SUM(CASE WHEN ai.status = 'degraded' THEN 1 ELSE 0 END)::integer AS degraded_count,
    SUM(CASE WHEN ai.status = 'failed' THEN 1 ELSE 0 END)::integer AS failed_count,
    AVG(ai.actual_duration_ms)::integer AS avg_resolution_time_ms,
    AVG(ai.makespan_variance_pct)::real AS avg_makespan_variance_pct,
    AVG(ai.severity_score)::integer AS avg_severity_score,
    -- Calculate fulfillment rate
    CASE
        WHEN COUNT(*) > 0
        THEN (SUM(CASE WHEN ai.status = 'fulfilled' THEN 1 ELSE 0 END)::real / COUNT(*)::real)
        ELSE 0
    END AS fulfillment_rate
FROM agenda_incidents ai
WHERE ai.resolved_at IS NOT NULL
GROUP BY 1, 2
ORDER BY 1 DESC;

COMMENT ON VIEW meta.agenda_resolution_daily IS 'Daily agenda resolution metrics with fulfillment rate for Metabase trend analysis';

-- ============================================================================
-- Recent Agendas Summary (Last 24 Hours)
-- ============================================================================

CREATE OR REPLACE VIEW meta.recent_agendas_summary AS
SELECT
    ai.agenda_id,
    ai.agenda_type::text AS agenda_type,
    ai.status::text AS status,
    ai.control_mode::text AS control_mode,
    ai.current_phase_index,
    ai.phases->ai.current_phase_index->>'name' AS current_phase_name,
    ai.makespan_projection_ms,
    ai.actual_duration_ms,
    ai.makespan_variance_pct,
    ai.severity_score,
    ai.created_at,
    ai.resolved_at,
    EXTRACT(EPOCH FROM (COALESCE(ai.resolved_at, NOW()) - ai.created_at))::integer AS elapsed_seconds,
    jsonb_array_length(ai.endpoint_transitions) AS transition_count
FROM agenda_incidents ai
WHERE ai.created_at > NOW() - INTERVAL '24 hours'
ORDER BY ai.created_at DESC;

COMMENT ON VIEW meta.recent_agendas_summary IS 'Last 24 hours of agendas for Metabase real-time dashboard';

-- ============================================================================
-- Control Mode Health (Weekly Trend)
-- ============================================================================

CREATE OR REPLACE VIEW meta.control_mode_health AS
SELECT
    date_trunc('day', ai.created_at) AS day,
    COUNT(*) AS total_agendas,
    SUM(CASE WHEN ai.control_mode = 'positive' THEN 1 ELSE 0 END)::integer AS positive_control_count,
    SUM(CASE WHEN ai.control_mode = 'failure_recovery' THEN 1 ELSE 0 END)::integer AS failure_recovery_count,
    SUM(CASE WHEN ai.control_mode = 'restart_recovery' THEN 1 ELSE 0 END)::integer AS restart_recovery_count,
    -- Calculate positive control rate
    CASE
        WHEN COUNT(*) > 0
        THEN (SUM(CASE WHEN ai.control_mode = 'positive' THEN 1 ELSE 0 END)::real / COUNT(*)::real)
        ELSE 0
    END AS positive_control_rate
FROM agenda_incidents ai
WHERE ai.created_at > NOW() - INTERVAL '7 days'
GROUP BY 1
ORDER BY 1 DESC;

COMMENT ON VIEW meta.control_mode_health IS 'Daily control mode health showing positive vs recovery transitions';

-- Grant permissions
GRANT SELECT ON meta.ambient_cycle_metrics TO gaius;
GRANT SELECT ON meta.agenda_phase_metrics TO gaius;
GRANT SELECT ON meta.endpoint_transition_metrics TO gaius;
GRANT SELECT ON meta.agenda_resolution_daily TO gaius;
GRANT SELECT ON meta.recent_agendas_summary TO gaius;
GRANT SELECT ON meta.control_mode_health TO gaius;

-- migrate:down
DROP VIEW IF EXISTS meta.control_mode_health;
DROP VIEW IF EXISTS meta.recent_agendas_summary;
DROP VIEW IF EXISTS meta.agenda_resolution_daily;
DROP VIEW IF EXISTS meta.endpoint_transition_metrics;
DROP VIEW IF EXISTS meta.agenda_phase_metrics;
DROP VIEW IF EXISTS meta.ambient_cycle_metrics;
