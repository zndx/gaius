-- migrate:up
-- Split agenda tracking into operations (routine) and incidents (problems)
--
-- agenda_operations: All workload executions for state recovery and resilient workflows
-- agenda_incidents: Only actual problems requiring attention (BLOCKED, FAILED, DEGRADED)

-- ============================================================================
-- Agenda Operations Table (Routine Tracking)
-- ============================================================================
-- Tracks all workload executions for:
-- - State recovery after normal restarts
-- - Resilient workflow patterns
-- - Operational metrics (via meta.* views)

CREATE TABLE agenda_operations (
    id SERIAL PRIMARY KEY,
    operation_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),

    -- Workload identity
    workload_id TEXT NOT NULL,              -- WorkloadRequest.workload_id
    workload_type agenda_type NOT NULL,     -- Reuse existing enum

    -- Phase tracking
    phases JSONB NOT NULL DEFAULT '[]',     -- [{name, required_capabilities, target_endpoints}]
    current_phase_index INT DEFAULT 0,

    -- Makespan tracking
    scheduler_plan_id TEXT,
    makespan_projection_ms INT,
    actual_duration_ms INT DEFAULT 0,
    makespan_variance_pct REAL DEFAULT 0.0,

    -- Status tracking (for active operations)
    status agenda_status NOT NULL DEFAULT 'scheduling',
    control_mode control_mode NOT NULL DEFAULT 'positive',

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    -- Endpoint transitions (for state recovery)
    endpoint_transitions JSONB DEFAULT '[]',

    -- Link to incident if escalated
    escalated_to_incident_id INT REFERENCES agenda_incidents(id)
);

COMMENT ON TABLE agenda_operations IS 'All workload executions for state recovery and operational metrics';
COMMENT ON COLUMN agenda_operations.workload_id IS 'WorkloadRequest.workload_id - correlates with orchestrator';
COMMENT ON COLUMN agenda_operations.escalated_to_incident_id IS 'Links to agenda_incidents if operation became an incident';

-- Indexes for operational queries
CREATE INDEX idx_agenda_ops_workload ON agenda_operations(workload_id);
CREATE INDEX idx_agenda_ops_type ON agenda_operations(workload_type, created_at DESC);
CREATE INDEX idx_agenda_ops_status ON agenda_operations(status) WHERE status NOT IN ('fulfilled', 'failed', 'degraded');
CREATE INDEX idx_agenda_ops_recent ON agenda_operations(created_at DESC);

-- ============================================================================
-- Migrate Existing Data
-- ============================================================================
-- Move FULFILLED and ON_TRACK records from agenda_incidents to agenda_operations

INSERT INTO agenda_operations (
    operation_id, workload_id, workload_type, phases, current_phase_index,
    scheduler_plan_id, makespan_projection_ms, actual_duration_ms, makespan_variance_pct,
    status, control_mode, created_at, started_at, completed_at, endpoint_transitions
)
SELECT
    incident_id as operation_id,
    agenda_id as workload_id,
    agenda_type as workload_type,
    phases,
    current_phase_index,
    scheduler_plan_id,
    makespan_projection_ms,
    actual_duration_ms,
    makespan_variance_pct,
    status,
    control_mode,
    created_at,
    baseline_departed_at as started_at,
    resolved_at as completed_at,
    endpoint_transitions
FROM agenda_incidents
WHERE status IN ('fulfilled', 'on_track', 'scheduling');

-- Delete migrated records from incidents table (keep only problems)
DELETE FROM agenda_incidents
WHERE status IN ('fulfilled', 'on_track', 'scheduling');

-- ============================================================================
-- Add Columns to agenda_incidents for Incident-Specific Data
-- ============================================================================

-- Add escalation reason (why did this become an incident?)
ALTER TABLE agenda_incidents
ADD COLUMN IF NOT EXISTS escalation_reason TEXT,
ADD COLUMN IF NOT EXISTS source_operation_id UUID,
ADD COLUMN IF NOT EXISTS acp_escalated BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS acp_escalated_at TIMESTAMPTZ;

COMMENT ON COLUMN agenda_incidents.escalation_reason IS 'Why this operation became an incident (e.g., "control_degraded", "makespan_exceeded", "phase_blocked")';
COMMENT ON COLUMN agenda_incidents.source_operation_id IS 'Links back to agenda_operations if escalated from there';
COMMENT ON COLUMN agenda_incidents.acp_escalated IS 'Whether this incident was escalated to ACP for intervention';

-- ============================================================================
-- Active Operations View
-- ============================================================================

CREATE OR REPLACE VIEW active_operations AS
SELECT
    ao.operation_id,
    ao.workload_id,
    ao.workload_type::text as workload_type,
    ao.status::text as status,
    ao.control_mode::text as control_mode,
    ao.current_phase_index,
    ao.phases->ao.current_phase_index->>'name' as current_phase_name,
    ao.makespan_projection_ms,
    ao.actual_duration_ms,
    ao.makespan_variance_pct,
    ao.created_at,
    ao.started_at,
    NOW() - ao.created_at as elapsed,
    ao.escalated_to_incident_id IS NOT NULL as is_escalated
FROM agenda_operations ao
WHERE ao.status NOT IN ('fulfilled', 'failed', 'degraded');

COMMENT ON VIEW active_operations IS 'Currently active workload operations';

-- ============================================================================
-- Update active_agendas to only show actual incidents
-- ============================================================================

-- Must DROP first because we're adding new columns (escalation_reason, acp_escalated)
DROP VIEW IF EXISTS active_agendas;
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
    ai.escalation_reason,
    ai.acp_escalated,
    NOW() - ai.created_at as elapsed
FROM agenda_incidents ai
WHERE ai.status NOT IN ('fulfilled', 'failed', 'degraded');

-- ============================================================================
-- Update Meta Views to Use agenda_operations for Metrics
-- ============================================================================

-- Must DROP these views because we're changing column structure
DROP VIEW IF EXISTS meta.ambient_cycle_metrics;
DROP VIEW IF EXISTS meta.agenda_resolution_daily;
DROP VIEW IF EXISTS meta.recent_agendas_summary;
DROP VIEW IF EXISTS meta.control_mode_health;

CREATE VIEW meta.ambient_cycle_metrics AS
SELECT
    date_trunc('hour', ao.created_at) AS hour,
    ao.workload_type::text AS agenda_type,
    ao.status::text AS status,
    ao.control_mode::text AS control_mode,
    COUNT(*) AS cycle_count,
    AVG(ao.actual_duration_ms)::integer AS avg_duration_ms,
    AVG(ao.makespan_variance_pct)::real AS avg_variance_pct,
    SUM(CASE WHEN ao.status = 'fulfilled' THEN 1 ELSE 0 END)::integer AS fulfilled_count,
    SUM(CASE WHEN ao.status = 'degraded' THEN 1 ELSE 0 END)::integer AS degraded_count,
    SUM(CASE WHEN ao.status = 'failed' THEN 1 ELSE 0 END)::integer AS failed_count,
    SUM(CASE WHEN ao.control_mode != 'positive' THEN 1 ELSE 0 END)::integer AS non_positive_count,
    SUM(CASE WHEN ao.escalated_to_incident_id IS NOT NULL THEN 1 ELSE 0 END)::integer AS escalated_count
FROM agenda_operations ao
GROUP BY 1, 2, 3, 4
ORDER BY 1 DESC;

COMMENT ON VIEW meta.ambient_cycle_metrics IS 'Hourly aggregate metrics from agenda_operations for Metabase dashboards';

CREATE VIEW meta.agenda_resolution_daily AS
SELECT
    date_trunc('day', ao.completed_at) AS day,
    ao.workload_type::text AS agenda_type,
    COUNT(*) AS total_completed,
    SUM(CASE WHEN ao.status = 'fulfilled' THEN 1 ELSE 0 END)::integer AS fulfilled_count,
    SUM(CASE WHEN ao.status = 'degraded' THEN 1 ELSE 0 END)::integer AS degraded_count,
    SUM(CASE WHEN ao.status = 'failed' THEN 1 ELSE 0 END)::integer AS failed_count,
    AVG(ao.actual_duration_ms)::integer AS avg_completion_time_ms,
    AVG(ao.makespan_variance_pct)::real AS avg_makespan_variance_pct,
    -- Calculate fulfillment rate
    CASE
        WHEN COUNT(*) > 0
        THEN (SUM(CASE WHEN ao.status = 'fulfilled' THEN 1 ELSE 0 END)::real / COUNT(*)::real)
        ELSE 0
    END AS fulfillment_rate,
    -- Escalation rate (how many became incidents)
    CASE
        WHEN COUNT(*) > 0
        THEN (SUM(CASE WHEN ao.escalated_to_incident_id IS NOT NULL THEN 1 ELSE 0 END)::real / COUNT(*)::real)
        ELSE 0
    END AS escalation_rate
FROM agenda_operations ao
WHERE ao.completed_at IS NOT NULL
GROUP BY 1, 2
ORDER BY 1 DESC;

COMMENT ON VIEW meta.agenda_resolution_daily IS 'Daily operation completion metrics with fulfillment and escalation rates';

CREATE VIEW meta.recent_agendas_summary AS
SELECT
    ao.workload_id as agenda_id,
    ao.workload_type::text AS agenda_type,
    ao.status::text AS status,
    ao.control_mode::text AS control_mode,
    ao.current_phase_index,
    ao.phases->ao.current_phase_index->>'name' AS current_phase_name,
    ao.makespan_projection_ms,
    ao.actual_duration_ms,
    ao.makespan_variance_pct,
    0 AS severity_score,  -- Operations don't have severity
    ao.created_at,
    ao.completed_at as resolved_at,
    EXTRACT(EPOCH FROM (COALESCE(ao.completed_at, NOW()) - ao.created_at))::integer AS elapsed_seconds,
    jsonb_array_length(ao.endpoint_transitions) AS transition_count,
    ao.escalated_to_incident_id IS NOT NULL as is_escalated
FROM agenda_operations ao
WHERE ao.created_at > NOW() - INTERVAL '24 hours'
ORDER BY ao.created_at DESC;

COMMENT ON VIEW meta.recent_agendas_summary IS 'Last 24 hours of operations for Metabase real-time dashboard';

CREATE VIEW meta.control_mode_health AS
SELECT
    date_trunc('day', ao.created_at) AS day,
    COUNT(*) AS total_operations,
    SUM(CASE WHEN ao.control_mode = 'positive' THEN 1 ELSE 0 END)::integer AS positive_control_count,
    SUM(CASE WHEN ao.control_mode = 'failure_recovery' THEN 1 ELSE 0 END)::integer AS failure_recovery_count,
    SUM(CASE WHEN ao.control_mode = 'restart_recovery' THEN 1 ELSE 0 END)::integer AS restart_recovery_count,
    -- Calculate positive control rate
    CASE
        WHEN COUNT(*) > 0
        THEN (SUM(CASE WHEN ao.control_mode = 'positive' THEN 1 ELSE 0 END)::real / COUNT(*)::real)
        ELSE 0
    END AS positive_control_rate,
    -- Escalation rate
    SUM(CASE WHEN ao.escalated_to_incident_id IS NOT NULL THEN 1 ELSE 0 END)::integer AS escalation_count
FROM agenda_operations ao
WHERE ao.created_at > NOW() - INTERVAL '7 days'
GROUP BY 1
ORDER BY 1 DESC;

COMMENT ON VIEW meta.control_mode_health IS 'Daily control mode health from operations, showing positive vs recovery transitions';

-- ============================================================================
-- Incident-Specific Views (for ACP/Health Dashboard)
-- ============================================================================

CREATE OR REPLACE VIEW meta.active_incidents AS
SELECT
    ai.incident_id,
    ai.agenda_id,
    ai.agenda_type::text as agenda_type,
    ai.status::text as status,
    ai.control_mode::text as control_mode,
    ai.escalation_reason,
    ai.severity_score,
    ai.acp_escalated,
    ai.acp_escalated_at,
    ai.created_at,
    NOW() - ai.created_at as age,
    ai.phases->ai.current_phase_index->>'name' as blocked_at_phase
FROM agenda_incidents ai
WHERE ai.status NOT IN ('fulfilled', 'failed', 'degraded')
ORDER BY ai.severity_score DESC, ai.created_at ASC;

COMMENT ON VIEW meta.active_incidents IS 'Currently active incidents requiring attention - for ACP/Health dashboard';

CREATE OR REPLACE VIEW meta.incident_summary AS
SELECT
    date_trunc('day', ai.created_at) AS day,
    ai.agenda_type::text AS agenda_type,
    ai.escalation_reason,
    COUNT(*) AS incident_count,
    SUM(CASE WHEN ai.acp_escalated THEN 1 ELSE 0 END)::integer AS acp_escalated_count,
    AVG(ai.severity_score)::integer AS avg_severity,
    AVG(EXTRACT(EPOCH FROM (COALESCE(ai.resolved_at, NOW()) - ai.created_at)))::integer AS avg_resolution_seconds
FROM agenda_incidents ai
WHERE ai.created_at > NOW() - INTERVAL '30 days'
GROUP BY 1, 2, 3
ORDER BY 1 DESC, incident_count DESC;

COMMENT ON VIEW meta.incident_summary IS 'Daily incident summary by type and escalation reason';

-- Grant permissions
GRANT ALL ON agenda_operations TO gaius;
GRANT USAGE, SELECT ON SEQUENCE agenda_operations_id_seq TO gaius;
GRANT SELECT ON active_operations TO gaius;
GRANT SELECT ON meta.active_incidents TO gaius;
GRANT SELECT ON meta.incident_summary TO gaius;

-- migrate:down
DROP VIEW IF EXISTS meta.incident_summary;
DROP VIEW IF EXISTS meta.active_incidents;
DROP VIEW IF EXISTS meta.control_mode_health;
DROP VIEW IF EXISTS meta.recent_agendas_summary;
DROP VIEW IF EXISTS meta.agenda_resolution_daily;
DROP VIEW IF EXISTS meta.ambient_cycle_metrics;
DROP VIEW IF EXISTS active_operations;

-- Restore original active_agendas view
CREATE OR REPLACE VIEW active_agendas AS
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

-- Remove added columns from agenda_incidents
ALTER TABLE agenda_incidents
DROP COLUMN IF EXISTS escalation_reason,
DROP COLUMN IF EXISTS source_operation_id,
DROP COLUMN IF EXISTS acp_escalated,
DROP COLUMN IF EXISTS acp_escalated_at;

-- Move data back to agenda_incidents
INSERT INTO agenda_incidents (
    incident_id, agenda_id, agenda_type, phases, current_phase_index,
    scheduler_plan_id, makespan_projection_ms, actual_duration_ms, makespan_variance_pct,
    status, control_mode, created_at, baseline_departed_at, resolved_at, endpoint_transitions
)
SELECT
    operation_id as incident_id,
    workload_id as agenda_id,
    workload_type as agenda_type,
    phases,
    current_phase_index,
    scheduler_plan_id,
    makespan_projection_ms,
    actual_duration_ms,
    makespan_variance_pct,
    status,
    control_mode,
    created_at,
    started_at as baseline_departed_at,
    completed_at as resolved_at,
    endpoint_transitions
FROM agenda_operations;

DROP TABLE IF EXISTS agenda_operations;
