-- migrate:up
-- Event-sourced healing attempt log for audit trail and state reconstruction
-- Records every healing attempt as immutable event, enables state reconstruction from history

CREATE TABLE healing_events (
    id BIGSERIAL PRIMARY KEY,
    event_id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,

    -- Sequence tracking for state reconstruction
    sequence_id UUID NOT NULL,          -- Groups events for same healing sequence
    sequence_num INT NOT NULL,          -- Order within sequence (1, 2, 3...)

    -- Timing (immutable once set)
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,

    -- Event classification
    event_type VARCHAR(32) NOT NULL,    -- sequence_started, attempt_failed, etc.

    -- Context
    endpoint VARCHAR(64) NOT NULL,
    tier INT NOT NULL,                  -- 0, 1, or 2

    -- Event payload (structure varies by event_type)
    payload JSONB NOT NULL DEFAULT '{}',

    -- Links to existing tables
    aiops_event_id INT REFERENCES aiops_events(id),
    failure_mode_id VARCHAR(32) REFERENCES fmea_catalog(failure_mode_id),

    -- Unique constraint ensures no duplicate sequence events
    UNIQUE(sequence_id, sequence_num)
);

-- Event types documentation:
-- sequence_started: New healing sequence initiated
--   payload: {issue_type, check_name, severity, rpn_score, initial_context}
-- sequence_completed: Sequence finished (success, exhausted, or manual_required)
--   payload: {outcome, total_attempts, final_tier, total_duration_ms}
-- tier_entered: Entered a tier
--   payload: {from_tier, to_tier, reason: "initial"|"escalation"|"fmea_directed"}
-- tier_exhausted: Max attempts at tier reached, escalating
--   payload: {attempts_made, max_attempts, reason}
-- attempt_started: Beginning a healing attempt
--   payload: {attempt_num, action}
-- attempt_succeeded: Attempt completed successfully
--   payload: {attempt_num, action, duration_ms, reason}
-- attempt_failed: Attempt failed
--   payload: {attempt_num, action, duration_ms, reason, agent_reasoning?, remote_assessment?}
-- cooldown_started: Entered cooldown period
--   payload: {cooldown_until, cooldown_seconds, reason}
-- cooldown_cleared: Cooldown expired or cleared
--   payload: {}
-- circuit_breaker_tripped: Global circuit breaker activated
--   payload: {failure_count, threshold, cooldown_until}
-- circuit_breaker_reset: Circuit breaker reset
--   payload: {}

COMMENT ON TABLE healing_events IS 'Event-sourced audit log for self-healing attempts - append only';
COMMENT ON COLUMN healing_events.sequence_id IS 'Groups all events for one healing sequence (issue detection through resolution)';
COMMENT ON COLUMN healing_events.sequence_num IS 'Order within sequence, auto-incremented per sequence';
COMMENT ON COLUMN healing_events.event_type IS 'Event classification: sequence_started/completed, tier_entered/exhausted, attempt_started/succeeded/failed, cooldown_started/cleared, circuit_breaker_tripped/reset';
COMMENT ON COLUMN healing_events.payload IS 'Event-specific data varying by event_type';

-- Indexes for efficient queries
CREATE INDEX idx_healing_events_sequence ON healing_events(sequence_id, sequence_num);
CREATE INDEX idx_healing_events_endpoint ON healing_events(endpoint, created_at DESC);
CREATE INDEX idx_healing_events_type ON healing_events(event_type, created_at DESC);
CREATE INDEX idx_healing_events_aiops ON healing_events(aiops_event_id) WHERE aiops_event_id IS NOT NULL;
CREATE INDEX idx_healing_events_recent ON healing_events(created_at DESC);
CREATE INDEX idx_healing_events_fmea ON healing_events(failure_mode_id) WHERE failure_mode_id IS NOT NULL;

-- Composite index for finding active (incomplete) sequences
CREATE INDEX idx_healing_events_active ON healing_events(endpoint, sequence_id, created_at)
    WHERE event_type = 'sequence_started';

-- Extend health_loop_state for circuit breaker persistence
ALTER TABLE health_loop_state
ADD COLUMN IF NOT EXISTS circuit_breaker JSONB DEFAULT '{}'::jsonb;

COMMENT ON COLUMN health_loop_state.circuit_breaker IS 'Global circuit breaker state: {global_failures, global_cooldown_until}';

-- Grant permissions
GRANT ALL ON healing_events TO gaius;
GRANT USAGE, SELECT ON SEQUENCE healing_events_id_seq TO gaius;

-- migrate:down
DROP TABLE IF EXISTS healing_events;
ALTER TABLE health_loop_state DROP COLUMN IF EXISTS circuit_breaker;
