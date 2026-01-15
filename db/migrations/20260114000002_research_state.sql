-- migrate:up

-- ============================================================================
-- Research State Table for Engine-Coordinated Multi-Pass
-- ============================================================================
-- Stores research session state for engine coordination via LISTEN/NOTIFY.
-- Enables multi-pass research without in-flow recursion by persisting:
-- - Session identity and query
-- - Pass progress and convergence state
-- - Serialized ConvergenceTracker for resumption
--
-- Flow lifecycle:
-- 1. Flow starts, creates/updates session state
-- 2. Flow completes pass, saves state, emits pg_notify
-- 3. Engine FlowEventListener checks state → triggers next pass if needed

CREATE TABLE meta.research_state (
    session_id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    pass_number INTEGER NOT NULL DEFAULT 0,
    converged BOOLEAN NOT NULL DEFAULT FALSE,
    convergence_reason TEXT DEFAULT '',
    q_value REAL DEFAULT 0.5,
    reward_components JSONB DEFAULT '{}',
    timing JSONB DEFAULT '{}',
    tracker_state JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_meta_research_state_updated ON meta.research_state(updated_at DESC);
CREATE INDEX idx_meta_research_state_converged ON meta.research_state(converged, updated_at DESC);

COMMENT ON TABLE meta.research_state IS 'Research session state for engine-coordinated multi-pass';
COMMENT ON COLUMN meta.research_state.session_id IS 'Unique session ID (e.g., res_20260114_070504)';
COMMENT ON COLUMN meta.research_state.query IS 'Research query string';
COMMENT ON COLUMN meta.research_state.pass_number IS 'Current pass number (1-indexed)';
COMMENT ON COLUMN meta.research_state.converged IS 'True if research has converged';
COMMENT ON COLUMN meta.research_state.convergence_reason IS 'Reason for convergence (e.g., drift_converged:0.05)';
COMMENT ON COLUMN meta.research_state.tracker_state IS 'Serialized ConvergenceTracker state';

-- migrate:down

DROP TABLE IF EXISTS meta.research_state;
