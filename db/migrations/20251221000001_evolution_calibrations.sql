-- migrate:up

-- Evolution calibration tracking
-- Calibrations use frontier models (Cerebras/XAI) to validate local model evaluations
-- This enables detection of local model drift and ensures training signal quality.

CREATE TABLE IF NOT EXISTS evolution_calibrations (
    id SERIAL PRIMARY KEY,

    -- What was calibrated
    agent_id TEXT NOT NULL,
    version_id TEXT REFERENCES agent_versions(version_id),
    objective_name TEXT NOT NULL,

    -- Calibration provider
    provider TEXT NOT NULL CHECK (provider IN ('cerebras', 'xai', 'anthropic')),
    model_id TEXT NOT NULL,

    -- Scores
    local_score FLOAT NOT NULL,
    calibration_score FLOAT NOT NULL,
    delta FLOAT GENERATED ALWAYS AS (calibration_score - local_score) STORED,

    -- Detailed breakdown (optional)
    local_breakdown JSONB DEFAULT '{}',
    calibration_breakdown JSONB DEFAULT '{}',

    -- Drift detection
    drift_detected BOOLEAN DEFAULT FALSE,
    drift_magnitude FLOAT,  -- abs(delta) when drift_detected

    -- Verification context
    objective_path TEXT,
    document_path TEXT,
    gate_results JSONB DEFAULT '[]',  -- [{gate, local_pass, calibration_pass}]

    -- Timing
    created_at TIMESTAMPTZ DEFAULT NOW(),
    latency_ms INTEGER,

    -- Cost tracking
    tokens_used INTEGER,
    cost_usd FLOAT
);

CREATE INDEX IF NOT EXISTS idx_calibrations_agent ON evolution_calibrations(agent_id);
CREATE INDEX IF NOT EXISTS idx_calibrations_objective ON evolution_calibrations(objective_name);
CREATE INDEX IF NOT EXISTS idx_calibrations_provider ON evolution_calibrations(provider);
CREATE INDEX IF NOT EXISTS idx_calibrations_drift ON evolution_calibrations(drift_detected) WHERE drift_detected;
CREATE INDEX IF NOT EXISTS idx_calibrations_created ON evolution_calibrations(created_at DESC);

-- Calibration summary per agent
CREATE TABLE IF NOT EXISTS calibration_summaries (
    id SERIAL PRIMARY KEY,
    agent_id TEXT NOT NULL,

    -- Aggregate stats
    total_calibrations INTEGER DEFAULT 0,
    drift_count INTEGER DEFAULT 0,
    avg_delta FLOAT DEFAULT 0.0,
    max_delta FLOAT DEFAULT 0.0,

    -- By provider
    cerebras_count INTEGER DEFAULT 0,
    xai_count INTEGER DEFAULT 0,

    -- Quality indicators
    local_calibrated BOOLEAN DEFAULT FALSE,  -- True if local model is well-calibrated
    confidence_score FLOAT DEFAULT 0.0,  -- 0-1, how much to trust local model

    -- Recommendations
    needs_recalibration BOOLEAN DEFAULT FALSE,
    last_recalibration_at TIMESTAMPTZ,

    -- Tracking
    window_start TIMESTAMPTZ DEFAULT NOW() - INTERVAL '7 days',
    window_end TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(agent_id)
);

CREATE INDEX IF NOT EXISTS idx_calibration_summaries_agent ON calibration_summaries(agent_id);

-- RASE objective verification runs
-- Links objectives to verification results with full lineage
CREATE TABLE IF NOT EXISTS objective_verifications (
    id SERIAL PRIMARY KEY,
    run_id TEXT UNIQUE NOT NULL,  -- UUID for this verification run

    -- Objective details
    objective_name TEXT NOT NULL,
    objective_path TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT 'kb',

    -- Target document
    document_path TEXT,
    document_hash TEXT,  -- SHA256 of document content

    -- Results
    verdict TEXT NOT NULL CHECK (verdict IN ('pass', 'fail', 'inconclusive', 'error')),
    accuracy FLOAT NOT NULL CHECK (accuracy >= 0.0 AND accuracy <= 1.0),
    reward FLOAT NOT NULL,

    -- Gate breakdown
    gates_total INTEGER NOT NULL,
    gates_passed INTEGER NOT NULL,
    gate_results JSONB NOT NULL DEFAULT '[]',
    -- [{name, level, passed, message, weight}]

    -- Digital thread
    thread_id TEXT NOT NULL,  -- Links to rase:// traceability

    -- Evidence
    evidence_path TEXT,  -- KB manifest path
    iceberg_table TEXT DEFAULT 'hx://rase.evidence',

    -- Training eligibility
    eligible_for_training BOOLEAN DEFAULT TRUE,
    calibration_id INTEGER REFERENCES evolution_calibrations(id),

    -- Timing
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,

    -- Metadata
    kb_root TEXT,
    kb_document_count INTEGER
);

CREATE INDEX IF NOT EXISTS idx_verifications_objective ON objective_verifications(objective_name);
CREATE INDEX IF NOT EXISTS idx_verifications_run ON objective_verifications(run_id);
CREATE INDEX IF NOT EXISTS idx_verifications_verdict ON objective_verifications(verdict);
CREATE INDEX IF NOT EXISTS idx_verifications_created ON objective_verifications(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_verifications_eligible ON objective_verifications(eligible_for_training) WHERE eligible_for_training;

-- View: Calibration health per agent
CREATE OR REPLACE VIEW calibration_health AS
SELECT
    agent_id,
    COUNT(*) as total_calibrations,
    COUNT(*) FILTER (WHERE drift_detected) as drift_count,
    AVG(delta) as avg_delta,
    MAX(ABS(delta)) as max_abs_delta,
    AVG(local_score) as avg_local_score,
    AVG(calibration_score) as avg_calibration_score,
    -- Correlation between local and calibration scores
    CORR(local_score, calibration_score) as score_correlation,
    -- Are we systematically over/under scoring?
    CASE
        WHEN AVG(delta) > 0.1 THEN 'under_scoring'
        WHEN AVG(delta) < -0.1 THEN 'over_scoring'
        ELSE 'calibrated'
    END as calibration_status,
    MAX(created_at) as last_calibration
FROM evolution_calibrations
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY agent_id;

-- View: Objective verification summary
CREATE OR REPLACE VIEW objective_verification_summary AS
SELECT
    objective_name,
    domain,
    COUNT(*) as total_runs,
    COUNT(*) FILTER (WHERE verdict = 'pass') as pass_count,
    COUNT(*) FILTER (WHERE verdict = 'fail') as fail_count,
    AVG(accuracy) as avg_accuracy,
    AVG(reward) as avg_reward,
    AVG(duration_ms) as avg_duration_ms,
    MAX(started_at) as last_run
FROM objective_verifications
GROUP BY objective_name, domain;

-- Function: Record calibration and update summary
CREATE OR REPLACE FUNCTION update_calibration_summary()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO calibration_summaries (agent_id, total_calibrations, drift_count, avg_delta, max_delta)
    VALUES (NEW.agent_id, 1,
            CASE WHEN NEW.drift_detected THEN 1 ELSE 0 END,
            NEW.delta,
            ABS(NEW.delta))
    ON CONFLICT (agent_id) DO UPDATE SET
        total_calibrations = calibration_summaries.total_calibrations + 1,
        drift_count = calibration_summaries.drift_count +
            CASE WHEN NEW.drift_detected THEN 1 ELSE 0 END,
        avg_delta = (calibration_summaries.avg_delta * calibration_summaries.total_calibrations + NEW.delta) /
            (calibration_summaries.total_calibrations + 1),
        max_delta = GREATEST(calibration_summaries.max_delta, ABS(NEW.delta)),
        needs_recalibration = CASE
            WHEN ABS(NEW.delta) > 0.15 THEN TRUE
            ELSE calibration_summaries.needs_recalibration
        END,
        updated_at = NOW();

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_update_calibration_summary
AFTER INSERT ON evolution_calibrations
FOR EACH ROW
EXECUTE FUNCTION update_calibration_summary();

-- migrate:down

DROP TRIGGER IF EXISTS trg_update_calibration_summary ON evolution_calibrations;
DROP FUNCTION IF EXISTS update_calibration_summary();
DROP VIEW IF EXISTS objective_verification_summary;
DROP VIEW IF EXISTS calibration_health;
DROP TABLE IF EXISTS objective_verifications;
DROP TABLE IF EXISTS calibration_summaries;
DROP TABLE IF EXISTS evolution_calibrations;
