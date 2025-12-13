-- migrate:up
-- FMEA (Failure Mode and Effects Analysis) catalog and tracking
-- Extends AIOps with quantitative RPN-based risk assessment

-- FMEA failure mode catalog (static definitions)
CREATE TABLE fmea_catalog (
    failure_mode_id VARCHAR(32) PRIMARY KEY,  -- GPU_001, VLLM_002, MQ_003
    category VARCHAR(32) NOT NULL,             -- gpu, vllm, model_quality, evolution, emergent, resource, infra
    name VARCHAR(128) NOT NULL,
    description TEXT,

    -- Default S/O/D scores (1-10)
    base_severity INT NOT NULL CHECK (base_severity BETWEEN 1 AND 10),
    base_occurrence INT NOT NULL CHECK (base_occurrence BETWEEN 1 AND 10),
    base_detection INT NOT NULL CHECK (base_detection BETWEEN 1 AND 10),

    -- Detection configuration
    detection_method VARCHAR(64),              -- health_check, metric_threshold, anomaly, manual
    detection_query TEXT,                      -- SQL or metric query for detection
    detection_threshold JSONB DEFAULT '{}',

    -- Remediation
    recommended_actions TEXT[],                -- ['restart_endpoint', 'clear_cache', 'rollback']
    escalation_tier INT DEFAULT 0,             -- 0=auto, 1=agent, 2=approval

    -- Controls
    preventive_controls TEXT[],
    detective_controls TEXT[],
    mitigative_controls TEXT[],

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE fmea_catalog IS 'FMEA failure mode definitions with S/O/D scores';
COMMENT ON COLUMN fmea_catalog.failure_mode_id IS 'Unique ID: GPU_001, VLLM_002, MQ_003, etc.';
COMMENT ON COLUMN fmea_catalog.base_severity IS 'Severity score 1-10: impact on system availability';
COMMENT ON COLUMN fmea_catalog.base_occurrence IS 'Occurrence score 1-10: probability of recurrence';
COMMENT ON COLUMN fmea_catalog.base_detection IS 'Detection score 1-10: ability to detect before impact (1=certain, 10=none)';

-- Extend aiops_events with FMEA columns
ALTER TABLE aiops_events ADD COLUMN IF NOT EXISTS failure_mode_id VARCHAR(32) REFERENCES fmea_catalog(failure_mode_id);
ALTER TABLE aiops_events ADD COLUMN IF NOT EXISTS runtime_severity INT CHECK (runtime_severity BETWEEN 1 AND 10);
ALTER TABLE aiops_events ADD COLUMN IF NOT EXISTS runtime_occurrence INT CHECK (runtime_occurrence BETWEEN 1 AND 10);
ALTER TABLE aiops_events ADD COLUMN IF NOT EXISTS runtime_detection INT CHECK (runtime_detection BETWEEN 1 AND 10);
ALTER TABLE aiops_events ADD COLUMN IF NOT EXISTS rpn_score INT CHECK (rpn_score BETWEEN 1 AND 1000);

COMMENT ON COLUMN aiops_events.failure_mode_id IS 'Link to FMEA catalog entry';
COMMENT ON COLUMN aiops_events.rpn_score IS 'Risk Priority Number = S × O × D (1-1000)';

-- Extend mlops_events with FMEA columns
ALTER TABLE mlops_events ADD COLUMN IF NOT EXISTS failure_mode_id VARCHAR(32) REFERENCES fmea_catalog(failure_mode_id);
ALTER TABLE mlops_events ADD COLUMN IF NOT EXISTS runtime_severity INT CHECK (runtime_severity BETWEEN 1 AND 10);
ALTER TABLE mlops_events ADD COLUMN IF NOT EXISTS runtime_occurrence INT CHECK (runtime_occurrence BETWEEN 1 AND 10);
ALTER TABLE mlops_events ADD COLUMN IF NOT EXISTS runtime_detection INT CHECK (runtime_detection BETWEEN 1 AND 10);
ALTER TABLE mlops_events ADD COLUMN IF NOT EXISTS rpn_score INT CHECK (rpn_score BETWEEN 1 AND 1000);

-- FMEA occurrence history (for calculating dynamic O score)
CREATE TABLE fmea_occurrences (
    id SERIAL PRIMARY KEY,
    failure_mode_id VARCHAR(32) NOT NULL REFERENCES fmea_catalog(failure_mode_id),
    occurred_at TIMESTAMPTZ DEFAULT NOW(),
    endpoint VARCHAR(64),
    context JSONB DEFAULT '{}'
);

CREATE INDEX idx_fmea_occurrences_mode ON fmea_occurrences(failure_mode_id, occurred_at DESC);
CREATE INDEX idx_fmea_occurrences_recent ON fmea_occurrences(occurred_at DESC);

COMMENT ON TABLE fmea_occurrences IS 'History of failure mode occurrences for calculating O score';

-- FMEA remediation outcomes (for adaptive learning)
CREATE TABLE fmea_outcomes (
    id SERIAL PRIMARY KEY,
    failure_mode_id VARCHAR(32) NOT NULL REFERENCES fmea_catalog(failure_mode_id),
    aiops_event_id INT REFERENCES aiops_events(id),
    mlops_event_id INT REFERENCES mlops_events(id),

    -- RPN at time of remediation
    rpn_score INT NOT NULL,
    severity INT NOT NULL,
    occurrence INT NOT NULL,
    detection INT NOT NULL,

    -- Remediation details
    action_taken VARCHAR(128),
    tier_used INT,                            -- 0, 1, or 2

    -- Outcome
    success BOOLEAN NOT NULL,
    duration_ms INT,                          -- Time to remediate
    downtime_seconds INT,                     -- Actual system impact
    sla_breach BOOLEAN DEFAULT FALSE,

    -- Learning feedback
    detection_lead_time_seconds INT,          -- How early was it detected?
    detected_by VARCHAR(32),                  -- automation, user_report, monitoring

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_fmea_outcomes_mode ON fmea_outcomes(failure_mode_id, created_at DESC);
CREATE INDEX idx_fmea_outcomes_success ON fmea_outcomes(success, created_at DESC);

COMMENT ON TABLE fmea_outcomes IS 'Remediation outcomes for adaptive S/O/D learning';

-- Runtime S/O/D adjustments (learned from outcomes)
CREATE TABLE fmea_adjustments (
    id SERIAL PRIMARY KEY,
    failure_mode_id VARCHAR(32) NOT NULL REFERENCES fmea_catalog(failure_mode_id),

    -- Context for adjustment (nullable for global adjustments)
    endpoint VARCHAR(64),
    hour_of_day INT CHECK (hour_of_day BETWEEN 0 AND 23),  -- 0-23 for time-based patterns

    -- Adjusted scores (override base scores when context matches)
    adjusted_severity INT CHECK (adjusted_severity BETWEEN 1 AND 10),
    adjusted_occurrence INT CHECK (adjusted_occurrence BETWEEN 1 AND 10),
    adjusted_detection INT CHECK (adjusted_detection BETWEEN 1 AND 10),

    -- Confidence tracking
    sample_count INT DEFAULT 0,
    last_updated TIMESTAMPTZ DEFAULT NOW(),

    -- Unique constraint: one adjustment per context
    UNIQUE(failure_mode_id, endpoint, hour_of_day)
);

CREATE INDEX idx_fmea_adjustments_lookup ON fmea_adjustments(failure_mode_id, endpoint, hour_of_day);

COMMENT ON TABLE fmea_adjustments IS 'Context-specific S/O/D adjustments learned from outcomes';

-- FMEA approval queue (extends remediation_approvals with RPN context)
ALTER TABLE remediation_approvals ADD COLUMN IF NOT EXISTS failure_mode_id VARCHAR(32) REFERENCES fmea_catalog(failure_mode_id);
ALTER TABLE remediation_approvals ADD COLUMN IF NOT EXISTS rpn_score INT;
ALTER TABLE remediation_approvals ADD COLUMN IF NOT EXISTS rpn_breakdown JSONB;  -- {severity: 8, occurrence: 6, detection: 4}

-- Create index for RPN-based queries
CREATE INDEX idx_aiops_events_rpn ON aiops_events(rpn_score DESC) WHERE rpn_score IS NOT NULL;
CREATE INDEX idx_mlops_events_rpn ON mlops_events(rpn_score DESC) WHERE rpn_score IS NOT NULL;
CREATE INDEX idx_aiops_events_failure_mode ON aiops_events(failure_mode_id);
CREATE INDEX idx_mlops_events_failure_mode ON mlops_events(failure_mode_id);

-- Grant permissions to gaius user
GRANT ALL ON fmea_catalog TO gaius;
GRANT ALL ON fmea_occurrences TO gaius;
GRANT ALL ON fmea_outcomes TO gaius;
GRANT ALL ON fmea_adjustments TO gaius;
GRANT USAGE, SELECT ON SEQUENCE fmea_occurrences_id_seq TO gaius;
GRANT USAGE, SELECT ON SEQUENCE fmea_outcomes_id_seq TO gaius;
GRANT USAGE, SELECT ON SEQUENCE fmea_adjustments_id_seq TO gaius;

-- migrate:down
DROP INDEX IF EXISTS idx_mlops_events_failure_mode;
DROP INDEX IF EXISTS idx_aiops_events_failure_mode;
DROP INDEX IF EXISTS idx_mlops_events_rpn;
DROP INDEX IF EXISTS idx_aiops_events_rpn;
ALTER TABLE remediation_approvals DROP COLUMN IF EXISTS rpn_breakdown;
ALTER TABLE remediation_approvals DROP COLUMN IF EXISTS rpn_score;
ALTER TABLE remediation_approvals DROP COLUMN IF EXISTS failure_mode_id;
DROP TABLE IF EXISTS fmea_adjustments;
DROP TABLE IF EXISTS fmea_outcomes;
DROP TABLE IF EXISTS fmea_occurrences;
ALTER TABLE mlops_events DROP COLUMN IF EXISTS rpn_score;
ALTER TABLE mlops_events DROP COLUMN IF EXISTS runtime_detection;
ALTER TABLE mlops_events DROP COLUMN IF EXISTS runtime_occurrence;
ALTER TABLE mlops_events DROP COLUMN IF EXISTS runtime_severity;
ALTER TABLE mlops_events DROP COLUMN IF EXISTS failure_mode_id;
ALTER TABLE aiops_events DROP COLUMN IF EXISTS rpn_score;
ALTER TABLE aiops_events DROP COLUMN IF EXISTS runtime_detection;
ALTER TABLE aiops_events DROP COLUMN IF EXISTS runtime_occurrence;
ALTER TABLE aiops_events DROP COLUMN IF EXISTS runtime_severity;
ALTER TABLE aiops_events DROP COLUMN IF EXISTS failure_mode_id;
DROP TABLE IF EXISTS fmea_catalog;
