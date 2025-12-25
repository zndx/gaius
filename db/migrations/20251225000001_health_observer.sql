-- migrate:up
-- HealthObserver tables for GitHub issue tracking and external routing metrics
-- Supports the ACP-integrated health monitoring daemon

-- GitHub issue linkage for health incidents
-- Each incident (fingerprint) maps to one GitHub issue per repo
CREATE TABLE github_issues (
    id SERIAL PRIMARY KEY,

    -- Unique identifier for deduplication: "FAILURE_MODE_ID:endpoint"
    -- e.g., "GPU_001:reasoning" or "VLLM_001:global"
    fingerprint TEXT NOT NULL,

    -- GitHub metadata
    issue_number INTEGER NOT NULL,
    repo TEXT NOT NULL,  -- e.g., "zndx/gaius-internal"
    issue_url TEXT,      -- Full URL for convenience

    -- Link to healing sequence that created this issue
    -- Note: No FK constraint - sequence_id references healing_events but isn't unique there
    -- (healing_events has composite unique on sequence_id + sequence_num)
    sequence_id UUID,

    -- Lifecycle tracking
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    closed_at TIMESTAMPTZ,           -- Set when issue is closed
    last_updated_at TIMESTAMPTZ,     -- Last comment/update
    recurrence_count INTEGER DEFAULT 0,  -- How many times incident recurred

    -- Current state
    status TEXT DEFAULT 'open' CHECK (status IN ('open', 'closed', 'stale')),

    -- Unique constraint: one issue per fingerprint per repo
    UNIQUE(fingerprint, repo)
);

COMMENT ON TABLE github_issues IS 'Tracks GitHub issues created for health incidents';
COMMENT ON COLUMN github_issues.fingerprint IS 'Unique incident identifier: FAILURE_MODE_ID:endpoint';
COMMENT ON COLUMN github_issues.recurrence_count IS 'Number of times this incident recurred while issue was open';

-- Indexes for efficient lookups
CREATE INDEX idx_github_issues_fingerprint ON github_issues(fingerprint);
CREATE INDEX idx_github_issues_repo ON github_issues(repo);
CREATE INDEX idx_github_issues_sequence ON github_issues(sequence_id) WHERE sequence_id IS NOT NULL;
CREATE INDEX idx_github_issues_status ON github_issues(status, created_at DESC);

-- Task-type routing metrics for external API calls
-- Tracks which external provider was used for each task type
CREATE TABLE external_routing_metrics (
    id SERIAL PRIMARY KEY,

    -- Task classification
    task_type TEXT NOT NULL,  -- diagnosis, planning, code_gen, verification, documentation

    -- Provider used
    provider TEXT NOT NULL,   -- cerebras, xai, bytez, local

    -- Performance metrics
    latency_ms INTEGER,
    tokens_used INTEGER,

    -- Quality assessment (if available)
    quality_score REAL,       -- 0.0-1.0 from evaluation

    -- Fallback tracking
    fallback_chain TEXT[],    -- Providers tried before success: ['cerebras', 'xai']
    fallback_reason TEXT,     -- Why fallback was needed: 'budget_exceeded', 'timeout', etc.

    -- Context
    endpoint TEXT,            -- Which endpoint triggered this (if applicable)
    incident_fingerprint TEXT,-- If related to a health incident

    -- Timing
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

COMMENT ON TABLE external_routing_metrics IS 'Tracks external API routing decisions and performance';
COMMENT ON COLUMN external_routing_metrics.task_type IS 'Task category: diagnosis, planning, code_gen, verification, documentation';
COMMENT ON COLUMN external_routing_metrics.fallback_chain IS 'Array of providers tried before successful completion';

-- Indexes for analytics
CREATE INDEX idx_routing_task_type ON external_routing_metrics(task_type, created_at DESC);
CREATE INDEX idx_routing_provider ON external_routing_metrics(provider, created_at DESC);
CREATE INDEX idx_routing_recent ON external_routing_metrics(created_at DESC);
CREATE INDEX idx_routing_incident ON external_routing_metrics(incident_fingerprint)
    WHERE incident_fingerprint IS NOT NULL;

-- HealthObserver daemon state (singleton row)
-- Allows daemon to persist state across restarts
CREATE TABLE health_observer_state (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),  -- Singleton pattern

    -- Daemon lifecycle
    started_at TIMESTAMPTZ,
    stopped_at TIMESTAMPTZ,
    last_poll_at TIMESTAMPTZ,
    poll_count INTEGER DEFAULT 0,

    -- Active incidents (JSON for flexibility)
    -- Structure: {fingerprint: {started_at, rpn_score, healing_tier, sequence_id}}
    active_incidents JSONB DEFAULT '{}'::jsonb,

    -- ACP connection state
    acp_connected BOOLEAN DEFAULT FALSE,
    acp_session_id TEXT,
    acp_prompts_sent INTEGER DEFAULT 0,
    acp_prompts_succeeded INTEGER DEFAULT 0,

    -- Configuration snapshot (for debugging)
    config JSONB DEFAULT '{}'::jsonb,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE health_observer_state IS 'Singleton row tracking HealthObserver daemon state';

-- Trigger to update updated_at
CREATE OR REPLACE FUNCTION update_health_observer_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER health_observer_state_updated
    BEFORE UPDATE ON health_observer_state
    FOR EACH ROW
    EXECUTE FUNCTION update_health_observer_timestamp();

-- Insert singleton row
INSERT INTO health_observer_state (id) VALUES (1)
ON CONFLICT (id) DO NOTHING;

-- Extend healing_events with observer-specific event types
-- These complement the existing event types from 20251215000002_healing_events.sql
-- New types: 'observer_started', 'observer_stopped', 'github_issue_created',
--            'github_issue_updated', 'github_issue_closed', 'acp_prompt_sent', 'acp_escalation'

-- Grant permissions
GRANT ALL ON github_issues TO gaius;
GRANT USAGE, SELECT ON SEQUENCE github_issues_id_seq TO gaius;
GRANT ALL ON external_routing_metrics TO gaius;
GRANT USAGE, SELECT ON SEQUENCE external_routing_metrics_id_seq TO gaius;
GRANT ALL ON health_observer_state TO gaius;

-- migrate:down
DROP TRIGGER IF EXISTS health_observer_state_updated ON health_observer_state;
DROP FUNCTION IF EXISTS update_health_observer_timestamp();
DROP TABLE IF EXISTS health_observer_state;
DROP TABLE IF EXISTS external_routing_metrics;
DROP TABLE IF EXISTS github_issues;
