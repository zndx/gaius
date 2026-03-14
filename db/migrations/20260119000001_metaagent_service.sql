-- migrate:up
-- MetaAgent Service: Pooled budget, Metabase sync, and audit infrastructure
--
-- Adds tables for:
-- - Pooled budget tracking across Grok/Cerebras with advisory locks
-- - Metabase sync run history
-- - Weekly audit results and recommendations
-- - Quality assessments for synthetic data ("textbook quality" metrics)

-- ============================================================================
-- POOLED BUDGET TRACKING
-- ============================================================================
-- Shared budget pool across Grok/Cerebras for all tasks (audits, calibration, etc.)
-- Uses PostgreSQL advisory locks for atomic budget acquisition

CREATE TABLE meta.audit_budget_pool (
    pool_id TEXT PRIMARY KEY,
    weekly_limit INTEGER NOT NULL DEFAULT 50,
    weekly_used INTEGER NOT NULL DEFAULT 0,
    grok_calls INTEGER NOT NULL DEFAULT 0,
    cerebras_calls INTEGER NOT NULL DEFAULT 0,
    week_start DATE NOT NULL DEFAULT date_trunc('week', CURRENT_DATE)::DATE,
    last_reset TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE meta.audit_budget_pool IS 'Shared weekly budget pool for remote LLM calls (Grok + Cerebras)';
COMMENT ON COLUMN meta.audit_budget_pool.pool_id IS 'Pool identifier (e.g., weekly_audit)';
COMMENT ON COLUMN meta.audit_budget_pool.weekly_limit IS 'Maximum calls per week across all providers';
COMMENT ON COLUMN meta.audit_budget_pool.weekly_used IS 'Total calls used this week (Grok + Cerebras)';

-- Trigger to auto-reset budget on week change
CREATE OR REPLACE FUNCTION meta.check_reset_weekly_budget()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.week_start != date_trunc('week', CURRENT_DATE)::DATE THEN
        NEW.weekly_used := 0;
        NEW.grok_calls := 0;
        NEW.cerebras_calls := 0;
        NEW.week_start := date_trunc('week', CURRENT_DATE)::DATE;
        NEW.last_reset := NOW();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_reset_weekly_budget
    BEFORE UPDATE ON meta.audit_budget_pool
    FOR EACH ROW
    EXECUTE FUNCTION meta.check_reset_weekly_budget();

-- Initialize default budget pool
INSERT INTO meta.audit_budget_pool (pool_id, weekly_limit)
VALUES ('weekly_audit', 50)
ON CONFLICT (pool_id) DO NOTHING;

-- ============================================================================
-- METABASE SYNC HISTORY
-- ============================================================================

CREATE TABLE meta.metabase_sync_runs (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running',  -- running, completed, failed
    full_refresh BOOLEAN NOT NULL DEFAULT FALSE,
    models_synced INTEGER DEFAULT 0,
    models_failed INTEGER DEFAULT 0,
    dashboards_synced INTEGER DEFAULT 0,
    dashboards_failed INTEGER DEFAULT 0,
    error_message TEXT,
    duration_ms INTEGER GENERATED ALWAYS AS (
        CAST(EXTRACT(EPOCH FROM (completed_at - started_at)) * 1000 AS INTEGER)
    ) STORED
);

CREATE INDEX idx_meta_metabase_sync_status ON meta.metabase_sync_runs(status);
CREATE INDEX idx_meta_metabase_sync_time ON meta.metabase_sync_runs(started_at DESC);

COMMENT ON TABLE meta.metabase_sync_runs IS 'History of Metabase model/dashboard sync operations';

-- ============================================================================
-- WEEKLY AUDIT HISTORY
-- ============================================================================

CREATE TABLE meta.metaagent_audits (
    id SERIAL PRIMARY KEY,
    audit_id UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    scope TEXT NOT NULL DEFAULT 'full',  -- full, lineage, operations, topology
    status TEXT NOT NULL DEFAULT 'running',  -- running, completed, failed
    summary TEXT,
    findings JSONB DEFAULT '[]',
    tokens_used INTEGER DEFAULT 0,
    provider TEXT,  -- cerebras, xai, local
    kb_path TEXT,
    duration_ms INTEGER GENERATED ALWAYS AS (
        CAST(EXTRACT(EPOCH FROM (completed_at - started_at)) * 1000 AS INTEGER)
    ) STORED,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_meta_audits_time ON meta.metaagent_audits(started_at DESC);
CREATE INDEX idx_meta_audits_scope ON meta.metaagent_audits(scope);

COMMENT ON TABLE meta.metaagent_audits IS 'Weekly MetaAgent audit results with LLM analysis';

-- ============================================================================
-- AUDIT RECOMMENDATIONS (Self-Improvement Loop)
-- ============================================================================

CREATE TABLE meta.audit_recommendations (
    id SERIAL PRIMARY KEY,
    audit_id UUID REFERENCES meta.metaagent_audits(audit_id) ON DELETE CASCADE,
    category TEXT NOT NULL,  -- monitoring, mcp_introspection, quality, pipeline
    severity TEXT NOT NULL,  -- critical, high, medium, low
    title TEXT NOT NULL,
    description TEXT,
    suggested_implementation TEXT,
    affected_component TEXT,  -- agent, flow, dashboard, endpoint
    status TEXT DEFAULT 'pending',  -- pending, accepted, rejected, implemented, verified
    accepted_at TIMESTAMPTZ,
    implemented_at TIMESTAMPTZ,
    verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_meta_recommendations_audit ON meta.audit_recommendations(audit_id);
CREATE INDEX idx_meta_recommendations_status ON meta.audit_recommendations(status);
CREATE INDEX idx_meta_recommendations_severity ON meta.audit_recommendations(severity);

COMMENT ON TABLE meta.audit_recommendations IS 'Actionable recommendations from audits for Atropos RL';

-- ============================================================================
-- QUALITY ASSESSMENTS ("Textbook Quality" Metrics)
-- ============================================================================
-- Tracks coherence, coverage, novelty scores for synthetic data quality
-- weighted_reward >= 0.85 indicates "textbook quality" content

CREATE TABLE meta.quality_assessments (
    id SERIAL PRIMARY KEY,
    source_type TEXT NOT NULL,  -- kb, hx, exchange, reasoning_trace
    source_id TEXT NOT NULL,    -- Path or ID of the source document/trace
    coherence_score REAL CHECK (coherence_score >= 0 AND coherence_score <= 1),
    coverage_score REAL CHECK (coverage_score >= 0 AND coverage_score <= 1),
    novelty_score REAL CHECK (novelty_score >= 0 AND novelty_score <= 1),
    weighted_reward REAL GENERATED ALWAYS AS (
        0.4 * COALESCE(coherence_score, 0) +
        0.35 * COALESCE(coverage_score, 0) +
        0.25 * COALESCE(novelty_score, 0)
    ) STORED,
    is_textbook_quality BOOLEAN GENERATED ALWAYS AS (
        (0.4 * COALESCE(coherence_score, 0) +
         0.35 * COALESCE(coverage_score, 0) +
         0.25 * COALESCE(novelty_score, 0)) >= 0.85
    ) STORED,
    evaluator_type TEXT NOT NULL,  -- local, cerebras, xai
    evaluation_model TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_meta_quality_source ON meta.quality_assessments(source_type, source_id);
CREATE INDEX idx_meta_quality_reward ON meta.quality_assessments(weighted_reward DESC);
CREATE INDEX idx_meta_quality_textbook ON meta.quality_assessments(is_textbook_quality) WHERE is_textbook_quality = TRUE;

COMMENT ON TABLE meta.quality_assessments IS 'Quality scores for synthetic data (textbook quality = weighted_reward >= 0.85)';
COMMENT ON COLUMN meta.quality_assessments.weighted_reward IS '0.4*coherence + 0.35*coverage + 0.25*novelty';

-- ============================================================================
-- METABASE MODEL REGISTRY
-- ============================================================================
-- Tracks Metabase models created by MetaAgent for sync management

CREATE TABLE meta.metabase_models (
    id SERIAL PRIMARY KEY,
    card_id INTEGER NOT NULL UNIQUE,  -- Metabase card ID
    name TEXT NOT NULL,
    source_table TEXT NOT NULL,       -- meta.* table/view being synced
    description TEXT,
    display_type TEXT DEFAULT 'table',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_synced_at TIMESTAMPTZ,
    sync_status TEXT DEFAULT 'active',  -- active, stale, error
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_meta_metabase_models_name ON meta.metabase_models(name);

COMMENT ON TABLE meta.metabase_models IS 'Registry of Metabase models synced from meta.* schema';

-- ============================================================================
-- VIEWS FOR METABASE DASHBOARDS
-- ============================================================================

-- Budget status view for dashboard
CREATE OR REPLACE VIEW meta.v_budget_status AS
SELECT
    pool_id,
    weekly_limit,
    weekly_used,
    weekly_limit - weekly_used AS weekly_remaining,
    grok_calls,
    cerebras_calls,
    ROUND(weekly_used::NUMERIC / NULLIF(weekly_limit, 0) * 100, 1) AS usage_pct,
    week_start,
    last_reset,
    CASE
        WHEN weekly_used >= weekly_limit THEN 'exhausted'
        WHEN weekly_used >= weekly_limit * 0.8 THEN 'low'
        WHEN weekly_used >= weekly_limit * 0.5 THEN 'moderate'
        ELSE 'healthy'
    END AS budget_health
FROM meta.audit_budget_pool;

COMMENT ON VIEW meta.v_budget_status IS 'Current pooled budget status for Metabase dashboard';

-- Quality summary view
CREATE OR REPLACE VIEW meta.v_quality_summary AS
SELECT
    source_type,
    COUNT(*) AS total_assessments,
    COUNT(*) FILTER (WHERE is_textbook_quality) AS textbook_quality_count,
    ROUND(AVG(coherence_score)::NUMERIC, 3) AS avg_coherence,
    ROUND(AVG(coverage_score)::NUMERIC, 3) AS avg_coverage,
    ROUND(AVG(novelty_score)::NUMERIC, 3) AS avg_novelty,
    ROUND(AVG(weighted_reward)::NUMERIC, 3) AS avg_weighted_reward,
    ROUND(
        COUNT(*) FILTER (WHERE is_textbook_quality)::NUMERIC /
        NULLIF(COUNT(*), 0) * 100, 1
    ) AS textbook_quality_pct
FROM meta.quality_assessments
GROUP BY source_type;

COMMENT ON VIEW meta.v_quality_summary IS 'Aggregated quality metrics by source type';

-- Recommendation funnel view
CREATE OR REPLACE VIEW meta.v_recommendation_funnel AS
SELECT
    status,
    COUNT(*) AS count,
    array_agg(DISTINCT category) AS categories,
    array_agg(DISTINCT severity) AS severities
FROM meta.audit_recommendations
GROUP BY status
ORDER BY
    CASE status
        WHEN 'pending' THEN 1
        WHEN 'accepted' THEN 2
        WHEN 'implemented' THEN 3
        WHEN 'verified' THEN 4
        WHEN 'rejected' THEN 5
    END;

COMMENT ON VIEW meta.v_recommendation_funnel IS 'Recommendation status funnel for self-improvement tracking';

-- Recent audits view
CREATE OR REPLACE VIEW meta.v_recent_audits AS
SELECT
    a.audit_id,
    a.started_at,
    a.completed_at,
    a.scope,
    a.status,
    a.provider,
    a.tokens_used,
    a.duration_ms,
    a.kb_path,
    COALESCE(jsonb_array_length(a.findings), 0) AS findings_count,
    (SELECT COUNT(*) FROM meta.audit_recommendations r WHERE r.audit_id = a.audit_id) AS recommendations_count
FROM meta.metaagent_audits a
ORDER BY a.started_at DESC
LIMIT 20;

COMMENT ON VIEW meta.v_recent_audits IS 'Recent audit runs with finding/recommendation counts';

-- ============================================================================
-- GRANTS
-- ============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON meta.audit_budget_pool TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON meta.metabase_sync_runs TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON meta.metaagent_audits TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON meta.audit_recommendations TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON meta.quality_assessments TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON meta.metabase_models TO gaius;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA meta TO gaius;
GRANT SELECT ON meta.v_budget_status TO gaius;
GRANT SELECT ON meta.v_quality_summary TO gaius;
GRANT SELECT ON meta.v_recommendation_funnel TO gaius;
GRANT SELECT ON meta.v_recent_audits TO gaius;

-- ============================================================================
-- PG_CRON JOBS
-- ============================================================================

-- Weekly audit trigger (Monday 5 AM UTC)
SELECT cron.schedule(
    'metaagent-weekly-audit',
    '0 5 * * 1',
    $$
    INSERT INTO scheduled_tasks (task_type, payload)
    VALUES ('metaagent_audit', '{"scope": "full", "use_remote_llm": true}')
    $$
);

-- Hourly Metabase sync (every hour on the hour)
SELECT cron.schedule(
    'metabase-hourly-sync',
    '0 * * * *',
    $$
    INSERT INTO scheduled_tasks (task_type, payload)
    VALUES ('metabase_sync', '{"full_refresh": false}')
    $$
);

-- Weekly budget reset (Sunday midnight UTC)
-- Note: The trigger handles auto-reset, but this ensures clean state
SELECT cron.schedule(
    'budget-weekly-reset',
    '0 0 * * 0',
    $$
    UPDATE meta.audit_budget_pool SET
        weekly_used = 0,
        grok_calls = 0,
        cerebras_calls = 0,
        week_start = date_trunc('week', CURRENT_DATE)::DATE,
        last_reset = NOW()
    WHERE week_start != date_trunc('week', CURRENT_DATE)::DATE
    $$
);

-- migrate:down

-- Remove cron jobs
SELECT cron.unschedule('metaagent-weekly-audit');
SELECT cron.unschedule('metabase-hourly-sync');
SELECT cron.unschedule('budget-weekly-reset');

-- Drop views
DROP VIEW IF EXISTS meta.v_recent_audits;
DROP VIEW IF EXISTS meta.v_recommendation_funnel;
DROP VIEW IF EXISTS meta.v_quality_summary;
DROP VIEW IF EXISTS meta.v_budget_status;

-- Drop tables
DROP TABLE IF EXISTS meta.metabase_models;
DROP TABLE IF EXISTS meta.quality_assessments;
DROP TABLE IF EXISTS meta.audit_recommendations;
DROP TABLE IF EXISTS meta.metaagent_audits;
DROP TABLE IF EXISTS meta.metabase_sync_runs;

-- Drop trigger and function
DROP TRIGGER IF EXISTS trg_reset_weekly_budget ON meta.audit_budget_pool;
DROP FUNCTION IF EXISTS meta.check_reset_weekly_budget();

DROP TABLE IF EXISTS meta.audit_budget_pool;
