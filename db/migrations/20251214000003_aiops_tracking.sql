-- migrate:up
-- AIOps/MLOps event tracking for autonomous health loop
-- Supports hybrid severity-based autonomy: auto-remediate low severity, require approval for high

-- Severity levels for health events
CREATE TYPE aiops_severity AS ENUM ('low', 'medium', 'high', 'critical');

-- Status tracking for remediation workflow
CREATE TYPE aiops_status AS ENUM (
    'detected',           -- Issue detected, not yet acted upon
    'auto_remediated',    -- System automatically fixed (low/medium severity)
    'pending_approval',   -- Waiting for user approval (high/critical)
    'approved',           -- User approved remediation
    'rejected',           -- User rejected remediation
    'failed',             -- Remediation attempted but failed
    'resolved'            -- Issue resolved (manually or automatically)
);

-- AIOps events: Infrastructure health (endpoints, GPUs, memory)
CREATE TABLE aiops_events (
    id SERIAL PRIMARY KEY,
    event_id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Event classification
    category VARCHAR(64) NOT NULL,        -- stuck_state, gpu_error, memory_pressure, endpoint_failure
    severity aiops_severity NOT NULL,
    status aiops_status NOT NULL DEFAULT 'detected',

    -- Context
    endpoint VARCHAR(64),                 -- Affected endpoint (reasoning, coding, etc.)
    description TEXT NOT NULL,
    context JSONB DEFAULT '{}',           -- elapsed_seconds, error_message, metrics

    -- Remediation tracking
    remediation_action VARCHAR(255),      -- restart_endpoint, clear_cuda_cache, etc.
    remediation_result JSONB,             -- success, error details, duration

    -- Approval workflow
    approved_by VARCHAR(64),              -- 'system' for auto, user email for manual
    approved_at TIMESTAMPTZ,

    -- Resolution
    resolved_at TIMESTAMPTZ
);

COMMENT ON TABLE aiops_events IS 'Infrastructure health events with remediation tracking';
COMMENT ON COLUMN aiops_events.category IS 'Event type: stuck_state, gpu_error, memory_pressure, endpoint_failure';
COMMENT ON COLUMN aiops_events.approved_by IS 'system for auto-remediation, user identifier for manual approval';

-- MLOps events: Model lifecycle (evolution, drift, promotion)
CREATE TABLE mlops_events (
    id SERIAL PRIMARY KEY,
    event_id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Event classification
    category VARCHAR(64) NOT NULL,        -- model_degradation, training_failure, drift_detected, promotion
    severity aiops_severity NOT NULL,
    status aiops_status NOT NULL DEFAULT 'detected',

    -- Context
    agent_id VARCHAR(64),                 -- leader, worker, critic, etc.
    model_version VARCHAR(128),           -- Version being affected
    description TEXT NOT NULL,
    metrics JSONB DEFAULT '{}',           -- accuracy, loss, held_out_score, etc.

    -- Remediation tracking
    remediation_action VARCHAR(255),      -- rollback, retrain, promote, etc.
    remediation_result JSONB,

    -- Resolution
    resolved_at TIMESTAMPTZ
);

COMMENT ON TABLE mlops_events IS 'Model lifecycle events for evolution and deployment tracking';
COMMENT ON COLUMN mlops_events.agent_id IS 'Agent being affected: leader, worker, critic, etc.';

-- Approval queue for high-severity actions requiring user confirmation
CREATE TABLE remediation_approvals (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Link to source event
    event_type VARCHAR(16) NOT NULL,      -- aiops | mlops
    event_id INTEGER NOT NULL,            -- FK to aiops_events.id or mlops_events.id

    -- Action details
    action_command VARCHAR(255) NOT NULL, -- The slash command to execute
    description TEXT NOT NULL,            -- Human-readable description
    severity aiops_severity NOT NULL,

    -- Approval workflow
    expires_at TIMESTAMPTZ NOT NULL,      -- Auto-reject after expiry
    status VARCHAR(32) DEFAULT 'pending', -- pending, approved, rejected, expired
    approved_by VARCHAR(64),
    approved_at TIMESTAMPTZ,
    rejection_reason TEXT
);

COMMENT ON TABLE remediation_approvals IS 'Queue for high-severity actions requiring user approval';
COMMENT ON COLUMN remediation_approvals.expires_at IS 'Auto-reject if not acted upon by this time';

-- Health loop state tracking (for resume after restart)
CREATE TABLE health_loop_state (
    id SERIAL PRIMARY KEY,
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Loop configuration
    check_interval_seconds INTEGER DEFAULT 30,
    stuck_starting_timeout_seconds INTEGER DEFAULT 300,
    stuck_stopping_timeout_seconds INTEGER DEFAULT 120,

    -- Last check timestamps per endpoint
    endpoint_last_check JSONB DEFAULT '{}',  -- {endpoint: timestamp}

    -- Stuck detection state
    stuck_detections JSONB DEFAULT '{}',     -- {endpoint: {detected_at, elapsed}}

    -- Statistics
    total_auto_remediations INTEGER DEFAULT 0,
    total_pending_approvals INTEGER DEFAULT 0,
    last_remediation_at TIMESTAMPTZ
);

COMMENT ON TABLE health_loop_state IS 'Persistent state for autonomous health loop';

-- Insert default health loop configuration
INSERT INTO health_loop_state (check_interval_seconds, stuck_starting_timeout_seconds, stuck_stopping_timeout_seconds)
VALUES (30, 300, 120);

-- Indexes for efficient queries
CREATE INDEX idx_aiops_events_status ON aiops_events(status, created_at DESC);
CREATE INDEX idx_aiops_events_severity ON aiops_events(severity, status);
CREATE INDEX idx_aiops_events_endpoint ON aiops_events(endpoint, created_at DESC);
CREATE INDEX idx_aiops_events_category ON aiops_events(category, created_at DESC);

CREATE INDEX idx_mlops_events_agent ON mlops_events(agent_id, created_at DESC);
CREATE INDEX idx_mlops_events_status ON mlops_events(status, created_at DESC);
CREATE INDEX idx_mlops_events_category ON mlops_events(category, created_at DESC);

CREATE INDEX idx_approvals_pending ON remediation_approvals(status, expires_at)
    WHERE status = 'pending';
CREATE INDEX idx_approvals_event ON remediation_approvals(event_type, event_id);

-- migrate:down
DROP TABLE IF EXISTS health_loop_state;
DROP TABLE IF EXISTS remediation_approvals;
DROP TABLE IF EXISTS mlops_events;
DROP TABLE IF EXISTS aiops_events;
DROP TYPE IF EXISTS aiops_status;
DROP TYPE IF EXISTS aiops_severity;
