-- migrate:up
-- Agenda-Centric Incident Model for HealthObserver
-- Tracks OR-Tools makespan fulfillment and positive control transitions

-- Agenda types (workload categories)
CREATE TYPE agenda_type AS ENUM (
    'ambient_cycle',  -- Ambient workload service maintenance
    'swarm',          -- Multi-agent swarm analysis
    'evolution',      -- Agent evolution/optimization
    'inference',      -- Direct inference request
    'flow'            -- Metaflow pipeline execution
);

-- Agenda status (lifecycle states)
CREATE TYPE agenda_status AS ENUM (
    'scheduling',     -- Waiting for OR-Tools plan
    'on_track',       -- Within makespan tolerance
    'delayed',        -- Behind makespan, still recoverable
    'blocked',        -- Cannot proceed without intervention
    'fulfilled',      -- Completed under positive control
    'failed',         -- Could not fulfill, gave up
    'degraded'        -- Completed but via failure/restart path
);

-- Control mode (how transitions occurred)
CREATE TYPE control_mode AS ENUM (
    'positive',           -- Intentional orchestrated transition
    'failure_recovery',   -- Endpoint failed, recovered automatically
    'restart_recovery'    -- Engine restart caused transition
);

-- Main agenda incidents table
CREATE TABLE agenda_incidents (
    id SERIAL PRIMARY KEY,
    incident_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),

    -- Agenda identity
    agenda_id TEXT NOT NULL,                    -- WorkloadRequest.workload_id
    agenda_type agenda_type NOT NULL,

    -- Phase tracking
    phases JSONB NOT NULL,                      -- [{name, required_capabilities, target_endpoints}]
    current_phase_index INT DEFAULT 0,

    -- Makespan tracking (OR-Tools integration)
    scheduler_plan_id TEXT,
    makespan_projection_ms INT,                 -- What OR-Tools projected
    actual_duration_ms INT DEFAULT 0,           -- What actually happened
    makespan_variance_pct REAL DEFAULT 0.0,     -- (actual - projected) / projected

    -- Status
    status agenda_status NOT NULL DEFAULT 'scheduling',
    control_mode control_mode NOT NULL DEFAULT 'positive',

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    baseline_departed_at TIMESTAMPTZ,
    baseline_restored_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,

    -- Severity (computed from makespan variance + control mode)
    severity_score INT DEFAULT 0,

    -- Diagnostic links
    endpoint_transitions JSONB DEFAULT '[]',    -- [{endpoint, from_state, to_state, timestamp, control}]
    healing_event_ids JSONB DEFAULT '[]'        -- Links to healing_events for drill-down
);

COMMENT ON TABLE agenda_incidents IS 'Agenda-centric incident tracking - success = makespan fulfillment + positive control';
COMMENT ON COLUMN agenda_incidents.agenda_id IS 'WorkloadRequest.workload_id - correlates with orchestrator';
COMMENT ON COLUMN agenda_incidents.phases IS 'Ordered capability phases: [{name, required_capabilities, target_endpoints}]';
COMMENT ON COLUMN agenda_incidents.control_mode IS 'How transitions occurred: positive (planned), failure_recovery, restart_recovery';
COMMENT ON COLUMN agenda_incidents.makespan_variance_pct IS 'Deviation from OR-Tools projection: (actual - projected) / projected';

-- Indexes for active incident tracking
CREATE INDEX idx_agenda_incidents_status ON agenda_incidents(status)
    WHERE status NOT IN ('fulfilled', 'failed', 'degraded');
CREATE INDEX idx_agenda_incidents_agenda ON agenda_incidents(agenda_id);
CREATE INDEX idx_agenda_incidents_type ON agenda_incidents(agenda_type, created_at DESC);
CREATE INDEX idx_agenda_incidents_recent ON agenda_incidents(created_at DESC);

-- Phase event tracking table
CREATE TABLE agenda_phase_events (
    id BIGSERIAL PRIMARY KEY,
    event_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    agenda_incident_id INT REFERENCES agenda_incidents(id) ON DELETE CASCADE,

    -- Phase context
    phase_index INT NOT NULL,
    phase_name TEXT NOT NULL,

    -- Event details
    event_type TEXT NOT NULL,                   -- phase_started, phase_completed, transition_started, etc.
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Makespan tracking
    projected_duration_ms INT,
    actual_duration_ms INT,

    -- Control mode for this transition
    control_mode control_mode NOT NULL DEFAULT 'positive',

    -- Endpoint details (for transition events)
    endpoint TEXT,
    endpoint_from_state TEXT,
    endpoint_to_state TEXT,

    -- Diagnostic payload
    payload JSONB NOT NULL DEFAULT '{}'
);

-- Event types documentation:
-- agenda_started: Agenda created, waiting for OR-Tools schedule
--   payload: {agenda_type, phases, requested_capabilities}
-- scheduling_complete: OR-Tools plan received
--   payload: {scheduler_plan_id, makespan_projection_ms}
-- baseline_departed: Left baseline configuration
--   payload: {baseline_endpoints, target_endpoints}
-- phase_started: Began a capability phase
--   payload: {required_capabilities, target_endpoints}
-- phase_completed: Completed a capability phase
--   payload: {duration_ms, variance_pct}
-- transition_started: Endpoint transition initiated
--   payload: {command, timeout_ms}
-- transition_completed: Endpoint transition finished
--   payload: {duration_ms, success}
-- baseline_restored: Returned to baseline configuration
--   payload: {control_mode, duration_ms}
-- agenda_fulfilled: All phases completed under positive control
--   payload: {total_duration_ms, makespan_variance_pct}
-- agenda_failed: Could not complete, giving up
--   payload: {reason, failed_at_phase, last_error}
-- agenda_degraded: Completed but via non-positive control path
--   payload: {control_mode, recovery_events}
-- control_degraded: Control mode changed from positive
--   payload: {from_mode, to_mode, trigger_event}

COMMENT ON TABLE agenda_phase_events IS 'Event-sourced log of agenda phase transitions';
COMMENT ON COLUMN agenda_phase_events.control_mode IS 'Control mode at time of event - may differ from agenda-level';

-- Indexes for event queries
CREATE INDEX idx_agenda_phase_events_incident ON agenda_phase_events(agenda_incident_id, phase_index);
CREATE INDEX idx_agenda_phase_events_type ON agenda_phase_events(event_type, created_at DESC);
CREATE INDEX idx_agenda_phase_events_recent ON agenda_phase_events(created_at DESC);
CREATE INDEX idx_agenda_phase_events_endpoint ON agenda_phase_events(endpoint, created_at DESC)
    WHERE endpoint IS NOT NULL;

-- View for active agendas with current phase info
CREATE VIEW active_agendas AS
SELECT
    ai.incident_id,
    ai.agenda_id,
    ai.agenda_type::text as agenda_type,
    ai.status::text as status,
    ai.control_mode::text as control_mode,
    ai.current_phase_index,
    ai.phases->ai.current_phase_index->>'name' as current_phase_name,
    ai.makespan_projection_ms,
    ai.actual_duration_ms,
    ai.makespan_variance_pct,
    ai.severity_score,
    ai.created_at,
    ai.baseline_departed_at,
    NOW() - ai.created_at as elapsed
FROM agenda_incidents ai
WHERE ai.status NOT IN ('fulfilled', 'failed', 'degraded');

COMMENT ON VIEW active_agendas IS 'Currently active agendas with progress info';

-- View for agenda health summary
CREATE VIEW agenda_health_summary AS
SELECT
    agenda_type::text as agenda_type,
    status::text as status,
    control_mode::text as control_mode,
    COUNT(*) as count,
    AVG(makespan_variance_pct) as avg_variance_pct,
    AVG(severity_score) as avg_severity,
    MAX(created_at) as latest
FROM agenda_incidents
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY agenda_type, status, control_mode
ORDER BY agenda_type, status;

COMMENT ON VIEW agenda_health_summary IS 'Aggregate stats by agenda type and status';

-- Grant permissions
GRANT ALL ON agenda_incidents TO gaius;
GRANT USAGE, SELECT ON SEQUENCE agenda_incidents_id_seq TO gaius;
GRANT ALL ON agenda_phase_events TO gaius;
GRANT USAGE, SELECT ON SEQUENCE agenda_phase_events_id_seq TO gaius;
GRANT SELECT ON active_agendas TO gaius;
GRANT SELECT ON agenda_health_summary TO gaius;

-- migrate:down
DROP VIEW IF EXISTS agenda_health_summary;
DROP VIEW IF EXISTS active_agendas;
DROP TABLE IF EXISTS agenda_phase_events;
DROP TABLE IF EXISTS agenda_incidents;
DROP TYPE IF EXISTS control_mode;
DROP TYPE IF EXISTS agenda_status;
DROP TYPE IF EXISTS agenda_type;
