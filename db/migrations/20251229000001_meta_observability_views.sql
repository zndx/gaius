-- migrate:up

-- ============================================================================
-- MetaAgent Observability Views for Metabase
-- ============================================================================
-- Dashboard-ready views for:
-- - FMEA Risk Analysis (heatmap, trends, remediation effectiveness)
-- - Incident Lifecycle (MTTR, autonomous healing rates)
-- - Pipeline Health (funnel, backlog, health status)
-- - Lineage Sankey (pre-aggregated edges for visualization)

-- ============================================================================
-- Phase 1.1: FMEA Risk Analysis Views
-- ============================================================================

-- RPN Risk Heatmap: Current risk by failure mode
CREATE OR REPLACE VIEW meta.v_fmea_risk_heatmap AS
WITH recent_rpn AS (
    SELECT DISTINCT ON (failure_mode_id)
        failure_mode_id,
        rpn_score AS last_rpn,
        severity AS last_s,
        occurrence AS last_o,
        detection AS last_d,
        created_at AS last_occurrence_at
    FROM fmea_outcomes
    ORDER BY failure_mode_id, created_at DESC
),
occurrence_stats AS (
    SELECT
        failure_mode_id,
        COUNT(*) FILTER (WHERE occurred_at > NOW() - INTERVAL '24 hours') AS occurrences_24h,
        COUNT(*) FILTER (WHERE occurred_at > NOW() - INTERVAL '7 days') AS occurrences_7d,
        COUNT(*) AS total_occurrences
    FROM fmea_occurrences
    GROUP BY failure_mode_id
)
SELECT
    c.failure_mode_id,
    c.category,
    c.name,
    c.description,
    c.base_severity,
    c.base_occurrence,
    c.base_detection,
    c.base_severity * c.base_occurrence * c.base_detection AS base_rpn,
    COALESCE(r.last_rpn, c.base_severity * c.base_occurrence * c.base_detection) AS current_rpn,
    r.last_s AS current_severity,
    r.last_o AS current_occurrence,
    r.last_d AS current_detection,
    COALESCE(os.occurrences_24h, 0) AS occurrences_24h,
    COALESCE(os.occurrences_7d, 0) AS occurrences_7d,
    COALESCE(os.total_occurrences, 0) AS total_occurrences,
    r.last_occurrence_at,
    CASE
        WHEN COALESCE(r.last_rpn, c.base_severity * c.base_occurrence * c.base_detection) <= 100 THEN 'TIER_0'
        WHEN COALESCE(r.last_rpn, c.base_severity * c.base_occurrence * c.base_detection) <= 200 THEN 'TIER_1'
        WHEN COALESCE(r.last_rpn, c.base_severity * c.base_occurrence * c.base_detection) <= 400 THEN 'TIER_2'
        ELSE 'MANUAL'
    END AS risk_tier,
    c.escalation_tier,
    c.recommended_actions
FROM fmea_catalog c
LEFT JOIN recent_rpn r ON c.failure_mode_id = r.failure_mode_id
LEFT JOIN occurrence_stats os ON c.failure_mode_id = os.failure_mode_id;

COMMENT ON VIEW meta.v_fmea_risk_heatmap IS 'FMEA risk heatmap showing current RPN scores, occurrence stats, and risk tiers for Metabase';


-- RPN Trends: Hourly time-series for trend analysis
CREATE TABLE IF NOT EXISTS meta.fmea_rpn_timeseries (
    failure_mode_id VARCHAR(32) NOT NULL REFERENCES fmea_catalog(failure_mode_id),
    hour TIMESTAMPTZ NOT NULL,
    avg_rpn DOUBLE PRECISION,
    min_rpn INTEGER,
    max_rpn INTEGER,
    outcome_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    PRIMARY KEY (failure_mode_id, hour)
);

CREATE INDEX IF NOT EXISTS idx_fmea_rpn_ts_hour ON meta.fmea_rpn_timeseries(hour DESC);

COMMENT ON TABLE meta.fmea_rpn_timeseries IS 'Hourly RPN aggregates for FMEA trend analysis in Metabase';


-- Remediation Effectiveness: Success rates by strategy
CREATE OR REPLACE VIEW meta.v_fmea_remediation_effectiveness AS
SELECT
    o.failure_mode_id,
    c.category,
    c.name AS failure_name,
    o.action_taken,
    o.tier_used,
    COUNT(*) AS attempts,
    SUM(CASE WHEN o.success THEN 1 ELSE 0 END) AS successes,
    SUM(CASE WHEN NOT o.success THEN 1 ELSE 0 END) AS failures,
    ROUND(100.0 * SUM(CASE WHEN o.success THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS success_rate_pct,
    AVG(o.duration_ms) AS avg_duration_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY o.duration_ms) AS p95_duration_ms,
    AVG(o.downtime_seconds) AS avg_downtime_seconds,
    SUM(CASE WHEN o.sla_breach THEN 1 ELSE 0 END) AS sla_breaches
FROM fmea_outcomes o
JOIN fmea_catalog c ON o.failure_mode_id = c.failure_mode_id
WHERE o.created_at > NOW() - INTERVAL '30 days'
GROUP BY o.failure_mode_id, c.category, c.name, o.action_taken, o.tier_used;

COMMENT ON VIEW meta.v_fmea_remediation_effectiveness IS 'Remediation strategy effectiveness metrics for FMEA in Metabase';


-- ============================================================================
-- Phase 1.2: Incident Lifecycle Views
-- ============================================================================

-- Incident Lifecycle: Detection to resolution
CREATE OR REPLACE VIEW meta.v_incident_lifecycle AS
WITH sequence_bounds AS (
    SELECT
        sequence_id,
        MIN(created_at) FILTER (WHERE event_type = 'sequence_started') AS started_at,
        MAX(created_at) FILTER (WHERE event_type = 'sequence_completed') AS completed_at,
        MAX(CASE WHEN event_type = 'sequence_completed' THEN (payload->>'outcome')::TEXT END) AS outcome,
        MAX(CASE WHEN event_type = 'sequence_completed' THEN tier END) AS final_tier,
        MAX(endpoint) AS endpoint,
        MAX(failure_mode_id) AS failure_mode_id,
        COUNT(*) AS event_count
    FROM healing_events
    WHERE created_at > NOW() - INTERVAL '30 days'
    GROUP BY sequence_id
)
SELECT
    s.sequence_id,
    s.started_at,
    s.completed_at,
    s.outcome,
    s.final_tier,
    s.endpoint,
    s.failure_mode_id,
    c.category,
    c.name AS failure_name,
    s.event_count,
    EXTRACT(EPOCH FROM (s.completed_at - s.started_at)) * 1000 AS duration_ms,
    CASE
        WHEN s.completed_at IS NULL THEN 'active'
        WHEN s.outcome = 'success' THEN 'resolved'
        WHEN s.outcome = 'failure' THEN 'failed'
        ELSE 'escalated'
    END AS status,
    CASE WHEN s.final_tier <= 2 THEN TRUE ELSE FALSE END AS auto_resolved
FROM sequence_bounds s
LEFT JOIN fmea_catalog c ON s.failure_mode_id = c.failure_mode_id;

COMMENT ON VIEW meta.v_incident_lifecycle IS 'Incident lifecycle from detection to resolution for Metabase';


-- MTTR Metrics: By failure mode and tier
CREATE OR REPLACE VIEW meta.v_mttr_metrics AS
SELECT
    c.category,
    i.failure_mode_id,
    c.name AS failure_name,
    i.final_tier,
    COUNT(*) AS incident_count,
    COUNT(*) FILTER (WHERE i.status = 'resolved') AS resolved_count,
    COUNT(*) FILTER (WHERE i.status = 'active') AS active_count,
    AVG(i.duration_ms) FILTER (WHERE i.status = 'resolved') AS avg_mttr_ms,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY i.duration_ms) FILTER (WHERE i.status = 'resolved') AS p50_mttr_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY i.duration_ms) FILTER (WHERE i.status = 'resolved') AS p95_mttr_ms,
    MIN(i.duration_ms) FILTER (WHERE i.status = 'resolved') AS min_mttr_ms,
    MAX(i.duration_ms) FILTER (WHERE i.status = 'resolved') AS max_mttr_ms
FROM meta.v_incident_lifecycle i
LEFT JOIN fmea_catalog c ON i.failure_mode_id = c.failure_mode_id
WHERE i.started_at > NOW() - INTERVAL '30 days'
GROUP BY c.category, i.failure_mode_id, c.name, i.final_tier;

COMMENT ON VIEW meta.v_mttr_metrics IS 'Mean Time To Resolve metrics by failure mode and tier for Metabase';


-- Self-Healing Summary: Daily autonomous resolution stats
CREATE OR REPLACE VIEW meta.v_autonomous_healing_summary AS
SELECT
    date_trunc('day', started_at) AS day,
    COUNT(*) AS total_incidents,
    COUNT(*) FILTER (WHERE status = 'resolved') AS resolved,
    COUNT(*) FILTER (WHERE status = 'active') AS active,
    COUNT(*) FILTER (WHERE status = 'escalated' OR status = 'failed') AS escalated,
    COUNT(*) FILTER (WHERE auto_resolved) AS auto_resolved,
    ROUND(100.0 * COUNT(*) FILTER (WHERE auto_resolved) / NULLIF(COUNT(*), 0), 1) AS auto_rate_pct,
    AVG(duration_ms) FILTER (WHERE status = 'resolved') AS avg_resolution_ms,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_ms) FILTER (WHERE status = 'resolved') AS p50_resolution_ms
FROM meta.v_incident_lifecycle
WHERE started_at > NOW() - INTERVAL '30 days'
GROUP BY date_trunc('day', started_at)
ORDER BY day DESC;

COMMENT ON VIEW meta.v_autonomous_healing_summary IS 'Daily autonomous healing summary for Metabase dashboards';


-- ============================================================================
-- Phase 1.3: Pipeline Health Views
-- ============================================================================

-- Enhanced Pipeline Health: With health status
CREATE OR REPLACE VIEW meta.v_pipeline_health AS
SELECT
    ps.stage,
    ps.pending,
    ps.completed_1h,
    ps.backlog_warn,
    ps.backlog_critical,
    CASE
        WHEN ps.pending >= ps.backlog_critical THEN 'critical'
        WHEN ps.pending >= ps.backlog_warn THEN 'warning'
        ELSE 'healthy'
    END AS health_status,
    CASE
        WHEN ps.pending >= ps.backlog_critical THEN 3
        WHEN ps.pending >= ps.backlog_warn THEN 2
        ELSE 1
    END AS health_level,
    ROUND(100.0 * ps.completed_1h / NULLIF(ps.pending + ps.completed_1h, 0), 1) AS throughput_pct
FROM v_pipeline_status ps;

COMMENT ON VIEW meta.v_pipeline_health IS 'Pipeline health status with severity levels for Metabase';


-- Pipeline Conversion Funnel: Daily yields
CREATE OR REPLACE VIEW meta.v_pipeline_funnel AS
SELECT
    date_trunc('day', fetched_at) AS day,
    COUNT(*) AS fetched,
    COUNT(*) FILTER (WHERE heuristic_score IS NOT NULL) AS scored_heuristic,
    COUNT(*) FILTER (WHERE heuristic_score >= 30) AS passed_heuristic,
    COUNT(*) FILTER (WHERE llm_quality_score IS NOT NULL) AS scored_llm,
    COUNT(*) FILTER (WHERE llm_quality_score >= 50) AS passed_llm,
    COUNT(*) FILTER (WHERE processed_at IS NOT NULL) AS written_to_kb,
    COUNT(*) FILTER (WHERE summary_excluded = TRUE) AS excluded,
    -- Yield percentages
    ROUND(100.0 * COUNT(*) FILTER (WHERE heuristic_score >= 30) / NULLIF(COUNT(*), 0), 1) AS heuristic_yield_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE llm_quality_score >= 50) / NULLIF(COUNT(*) FILTER (WHERE heuristic_score >= 30), 0), 1) AS llm_yield_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE processed_at IS NOT NULL) / NULLIF(COUNT(*), 0), 1) AS total_yield_pct
FROM content_items
WHERE fetched_at > NOW() - INTERVAL '30 days'
GROUP BY date_trunc('day', fetched_at)
ORDER BY day DESC;

COMMENT ON VIEW meta.v_pipeline_funnel IS 'Content pipeline conversion funnel with daily yields for Metabase';


-- ============================================================================
-- Phase 1.4: Lineage Sankey Aggregation
-- ============================================================================

-- Pre-aggregated lineage for Sankey charts
CREATE TABLE IF NOT EXISTS meta.lineage_sankey_agg (
    time_window TEXT NOT NULL,  -- 'hourly', 'daily', 'weekly'
    window_start TIMESTAMPTZ NOT NULL,
    source_namespace TEXT NOT NULL,
    source_name TEXT NOT NULL,
    target_namespace TEXT NOT NULL,
    target_name TEXT NOT NULL,
    via_job TEXT NOT NULL DEFAULT '',  -- Empty string for direct edges
    flow_count INTEGER DEFAULT 1,
    bytes_transferred BIGINT DEFAULT 0,
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (time_window, window_start, source_namespace, source_name, target_namespace, target_name, via_job)
);

CREATE INDEX IF NOT EXISTS idx_sankey_window ON meta.lineage_sankey_agg(time_window, window_start DESC);

COMMENT ON TABLE meta.lineage_sankey_agg IS 'Pre-aggregated lineage edges for Sankey visualization in Metabase v52+';


-- ============================================================================
-- Phase 1.5: GPU Minute Stats (24h retention, streaming aggregation)
-- ============================================================================

-- Minute-level GPU stats for 24h retention
CREATE TABLE IF NOT EXISTS meta.gpu_minute_stats (
    minute TIMESTAMPTZ NOT NULL,
    gpu_index SMALLINT NOT NULL,
    samples INTEGER DEFAULT 0,
    memory_min_mb REAL,
    memory_max_mb REAL,
    memory_avg_mb REAL,
    util_min_pct REAL,
    util_max_pct REAL,
    util_avg_pct REAL,
    temp_max_c REAL,
    power_avg_w REAL,
    PRIMARY KEY (minute, gpu_index)
);

CREATE INDEX IF NOT EXISTS idx_gpu_minute_time ON meta.gpu_minute_stats(minute DESC);

COMMENT ON TABLE meta.gpu_minute_stats IS 'Minute-level GPU stats with 24h retention for Metabase time series';


-- Hourly GPU rollups (30 day retention)
CREATE TABLE IF NOT EXISTS meta.gpu_hourly_stats (
    hour TIMESTAMPTZ NOT NULL,
    gpu_index SMALLINT NOT NULL,
    samples INTEGER DEFAULT 0,
    memory_min_mb REAL,
    memory_max_mb REAL,
    memory_avg_mb REAL,
    util_min_pct REAL,
    util_max_pct REAL,
    util_avg_pct REAL,
    temp_max_c REAL,
    power_avg_w REAL,
    PRIMARY KEY (hour, gpu_index)
);

CREATE INDEX IF NOT EXISTS idx_gpu_hourly_time ON meta.gpu_hourly_stats(hour DESC);

COMMENT ON TABLE meta.gpu_hourly_stats IS 'Hourly GPU rollups with 30-day retention for Metabase time series';


-- ============================================================================
-- Phase 1.6: Inference Hourly Stats
-- ============================================================================

-- Update existing inference_throughput table or create if needed
-- (Using separate table with better schema for percentiles)
CREATE TABLE IF NOT EXISTS meta.inference_hourly (
    hour TIMESTAMPTZ NOT NULL,
    model VARCHAR(128) NOT NULL,
    endpoint VARCHAR(64) NOT NULL DEFAULT '',  -- Empty string for unknown endpoint
    request_count INTEGER DEFAULT 0,
    tokens_total BIGINT DEFAULT 0,
    tokens_avg REAL,
    latency_min_ms REAL,
    latency_max_ms REAL,
    latency_p50_ms REAL,
    latency_p95_ms REAL,
    latency_p99_ms REAL,
    errors_count INTEGER DEFAULT 0,
    PRIMARY KEY (hour, model, endpoint)
);

CREATE INDEX IF NOT EXISTS idx_inference_hourly_time ON meta.inference_hourly(hour DESC);

COMMENT ON TABLE meta.inference_hourly IS 'Hourly inference metrics with percentiles for Metabase time series';


-- ============================================================================
-- Phase 1.7: Alert Thresholds
-- ============================================================================

CREATE TABLE IF NOT EXISTS meta.alert_thresholds (
    metric_name VARCHAR(64) PRIMARY KEY,
    category VARCHAR(32) NOT NULL,
    description TEXT,
    warning_threshold DOUBLE PRECISION,
    critical_threshold DOUBLE PRECISION,
    comparison VARCHAR(8) DEFAULT '>=',  -- '>=', '<=', '=', '!='
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Seed default thresholds
INSERT INTO meta.alert_thresholds (metric_name, category, description, warning_threshold, critical_threshold, comparison) VALUES
    ('rpn_score', 'fmea', 'Risk Priority Number threshold', 200, 400, '>='),
    ('occurrences_24h', 'fmea', 'Failure occurrences in last 24h', 3, 10, '>='),
    ('heuristic_backlog', 'pipeline', 'Content items pending heuristic triage', 200, 500, '>='),
    ('llm_backlog', 'pipeline', 'Content items pending LLM triage', 50, 200, '>='),
    ('kb_backlog', 'pipeline', 'Content items pending KB write', 20, 100, '>='),
    ('stuck_tasks', 'pipeline', 'Tasks stuck in running state', 1, 5, '>='),
    ('auto_resolution_rate', 'healing', 'Autonomous healing success rate', 70, 50, '<='),
    ('gpu_memory_pct', 'resources', 'GPU memory utilization percent', 85, 95, '>='),
    ('gpu_temp_c', 'resources', 'GPU temperature in Celsius', 75, 85, '>='),
    ('latency_p95_ms', 'inference', 'Inference latency P95', 2000, 5000, '>=')
ON CONFLICT (metric_name) DO NOTHING;

COMMENT ON TABLE meta.alert_thresholds IS 'Alert thresholds for Metabase dashboard alerts';


-- ============================================================================
-- Phase 1.8: MetaAgent Query Cache
-- ============================================================================

CREATE TABLE IF NOT EXISTS meta.metaagent_queries (
    query_hash TEXT PRIMARY KEY,
    query_text TEXT NOT NULL,
    domains TEXT[],
    answer TEXT,
    dot_graph TEXT,
    evidence JSONB DEFAULT '[]',
    duration_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    cache_hits INTEGER DEFAULT 0,
    last_hit_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_metaagent_queries_expires ON meta.metaagent_queries(expires_at);

COMMENT ON TABLE meta.metaagent_queries IS 'MetaAgent query result cache for expensive analytics queries';


-- ============================================================================
-- Grant permissions
-- ============================================================================

GRANT SELECT ON ALL TABLES IN SCHEMA meta TO gaius;
GRANT INSERT, UPDATE, DELETE ON meta.fmea_rpn_timeseries TO gaius;
GRANT INSERT, UPDATE, DELETE ON meta.lineage_sankey_agg TO gaius;
GRANT INSERT, UPDATE, DELETE ON meta.gpu_minute_stats TO gaius;
GRANT INSERT, UPDATE, DELETE ON meta.gpu_hourly_stats TO gaius;
GRANT INSERT, UPDATE, DELETE ON meta.inference_hourly TO gaius;
GRANT INSERT, UPDATE, DELETE ON meta.alert_thresholds TO gaius;
GRANT INSERT, UPDATE, DELETE ON meta.metaagent_queries TO gaius;


-- migrate:down

DROP TABLE IF EXISTS meta.metaagent_queries;
DROP TABLE IF EXISTS meta.alert_thresholds;
DROP TABLE IF EXISTS meta.inference_hourly;
DROP TABLE IF EXISTS meta.gpu_hourly_stats;
DROP TABLE IF EXISTS meta.gpu_minute_stats;
DROP TABLE IF EXISTS meta.lineage_sankey_agg;
DROP TABLE IF EXISTS meta.fmea_rpn_timeseries;

DROP VIEW IF EXISTS meta.v_pipeline_funnel;
DROP VIEW IF EXISTS meta.v_pipeline_health;
DROP VIEW IF EXISTS meta.v_autonomous_healing_summary;
DROP VIEW IF EXISTS meta.v_mttr_metrics;
DROP VIEW IF EXISTS meta.v_incident_lifecycle;
DROP VIEW IF EXISTS meta.v_fmea_remediation_effectiveness;
DROP VIEW IF EXISTS meta.v_fmea_risk_heatmap;
