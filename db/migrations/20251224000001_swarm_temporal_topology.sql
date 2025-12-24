-- migrate:up
-- Temporal Topology Schema for Swarm Dynamics
--
-- Captures the evolution of semantic space over time, enabling:
-- 1. Drift detection: How consensus positions change
-- 2. Well depth: Entrenchment measurement (1/variance)
-- 3. NG-RC integration: Forward dynamics prediction
-- 4. Non-autonomous dynamics: dx/dt = f(x, KB(t))
--
-- Design Principles:
-- - Every swarm run is a snapshot of a living topology
-- - KB growth raises the floor of old potential wells
-- - Productive instability prevents ossification

-- ============================================================================
-- SWARM SNAPSHOTS: Point-in-time capture of swarm state
-- ============================================================================

CREATE TABLE IF NOT EXISTS meta.swarm_snapshots (
    snapshot_id SERIAL PRIMARY KEY,
    run_id UUID NOT NULL,                         -- Links to orchestrator workload
    domain TEXT NOT NULL,                          -- e.g., 'pension', 'kudu', 'csa'
    captured_at TIMESTAMPTZ DEFAULT NOW(),

    -- KB State at capture time (non-autonomous dynamics)
    kb_version TEXT,                               -- Git hash or timestamp
    kb_document_count INTEGER,                     -- Number of docs at snapshot
    kb_last_modified TIMESTAMPTZ,                  -- Most recent KB change

    -- Consensus metrics
    consensus_embedding FLOAT8[],                  -- 128-dim centroid of all agents
    consensus_variance FLOAT8,                     -- Variance around centroid
    consensus_grid_x INTEGER,                      -- Grid position of centroid
    consensus_grid_y INTEGER,

    -- Topological features (Betti numbers of agent positions)
    h0_count INTEGER,                              -- Connected components
    h1_count INTEGER,                              -- Loops (disagreement cycles)

    -- Information-theoretic metrics
    position_entropy FLOAT8,                       -- Entropy of grid positions
    feature_entropy FLOAT8,                        -- Entropy of CLT features

    -- Agent count
    n_agents INTEGER,

    -- Original query/context (for traceability)
    query_text TEXT,

    CONSTRAINT valid_grid_x CHECK (consensus_grid_x >= 0 AND consensus_grid_x <= 18),
    CONSTRAINT valid_grid_y CHECK (consensus_grid_y >= 0 AND consensus_grid_y <= 18)
);

CREATE INDEX idx_swarm_snapshots_domain ON meta.swarm_snapshots(domain);
CREATE INDEX idx_swarm_snapshots_captured ON meta.swarm_snapshots(captured_at DESC);
CREATE INDEX idx_swarm_snapshots_domain_time ON meta.swarm_snapshots(domain, captured_at DESC);

-- ============================================================================
-- AGENT POSITIONS: Individual agent state within each snapshot
-- ============================================================================

CREATE TABLE IF NOT EXISTS meta.swarm_agent_positions (
    id SERIAL PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES meta.swarm_snapshots(snapshot_id) ON DELETE CASCADE,

    -- Agent identity
    agent_role TEXT NOT NULL,                      -- e.g., 'synthesizer', 'critic'

    -- CLT embedding (128-dim projection from sparse features)
    embedding FLOAT8[],

    -- Grid position
    grid_x INTEGER,
    grid_y INTEGER,

    -- Sparse features (top-K from CLT extraction)
    -- Format: [{"idx": 1234, "activation": 0.85}, ...]
    top_features JSONB,

    -- Distance from consensus
    distance_from_consensus FLOAT8,

    -- Trace history (for temporal analysis within run)
    -- List of (x, y) positions during deliberation
    trace_history JSONB,

    CONSTRAINT valid_agent_grid_x CHECK (grid_x >= 0 AND grid_x <= 18),
    CONSTRAINT valid_agent_grid_y CHECK (grid_y >= 0 AND grid_y <= 18)
);

CREATE INDEX idx_agent_positions_snapshot ON meta.swarm_agent_positions(snapshot_id);
CREATE INDEX idx_agent_positions_role ON meta.swarm_agent_positions(agent_role);

-- ============================================================================
-- TOPOLOGY DRIFT: Track how consensus positions change over time
-- ============================================================================

CREATE TABLE IF NOT EXISTS meta.topology_drift (
    id SERIAL PRIMARY KEY,
    domain TEXT NOT NULL,
    computed_at TIMESTAMPTZ DEFAULT NOW(),

    -- Time window analyzed
    time_window_hours INTEGER DEFAULT 24,
    n_snapshots INTEGER,                           -- Snapshots in window

    -- Drift velocity (how fast consensus is moving)
    -- This is dx/dt in phase space
    centroid_drift_velocity FLOAT8[],              -- 128-dim velocity vector
    drift_magnitude FLOAT8,                        -- |dx/dt|
    drift_direction_grid_x FLOAT8,                 -- Projected grid direction
    drift_direction_grid_y FLOAT8,

    -- Well depth (entrenchment measure)
    -- High = deep well = stable but potentially stuck
    -- Low = shallow well = flexible but noisy
    well_depth FLOAT8,                             -- 1 / variance

    -- Stability metrics
    lyapunov_exponent FLOAT8,                      -- Negative = stable, positive = chaotic
    mean_variance FLOAT8,                          -- Average variance over window
    variance_trend FLOAT8,                         -- Is variance increasing or decreasing?

    -- KB dynamics (non-autonomous term)
    kb_growth_rate FLOAT8,                         -- Docs added per hour
    kb_modification_rate FLOAT8,                   -- Edits per hour

    -- Anomaly detection
    drift_anomaly_score FLOAT8,                    -- Z-score of drift magnitude
    is_bifurcation BOOLEAN DEFAULT FALSE           -- Detected splitting/merging
);

CREATE INDEX idx_topology_drift_domain ON meta.topology_drift(domain);
CREATE INDEX idx_topology_drift_time ON meta.topology_drift(computed_at DESC);

-- ============================================================================
-- NG-RC MODELS: Learned dynamics for forward prediction
-- ============================================================================
-- "NG-RC doesn't just learn, it generates forward dynamics"
-- These models learn: dx/dt = f(x, KB(t))
-- Enabling prediction without LLM calls

CREATE TABLE IF NOT EXISTS meta.ngrc_models (
    id SERIAL PRIMARY KEY,
    domain TEXT NOT NULL,

    -- Training metadata
    trained_at TIMESTAMPTZ DEFAULT NOW(),
    n_training_snapshots INTEGER,
    training_time_span_hours FLOAT8,

    -- Model architecture
    reservoir_size INTEGER DEFAULT 500,
    spectral_radius FLOAT8 DEFAULT 0.9,
    input_scaling FLOAT8 DEFAULT 0.1,
    leaking_rate FLOAT8 DEFAULT 0.3,

    -- Model weights (serialized numpy arrays)
    -- W_in: (reservoir_size, 128) - input weights
    -- W_res: (reservoir_size, reservoir_size) - reservoir weights
    -- W_out: (128, reservoir_size) - output weights
    model_weights BYTEA,

    -- KB parameterization (for non-autonomous dynamics)
    -- Maps KB state to flow field modulation
    kb_modulation_weights BYTEA,

    -- Validation metrics
    validation_mse FLOAT8,                         -- Mean squared error on held-out
    forecast_horizon_steps INTEGER,                -- Reliable prediction horizon
    stability_radius FLOAT8,                       -- Region of valid prediction

    -- Active flag (only one model active per domain)
    is_active BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_ngrc_models_domain ON meta.ngrc_models(domain);

-- Partial unique index: only one active model per domain
CREATE UNIQUE INDEX idx_ngrc_models_active_domain ON meta.ngrc_models(domain)
    WHERE is_active = TRUE;

-- ============================================================================
-- ATTRACTOR REGISTRY: Named stable states in semantic space
-- ============================================================================
-- "Pension" means something different in 1950 vs 2024
-- Track how named concepts drift over time

CREATE TABLE IF NOT EXISTS meta.semantic_attractors (
    id SERIAL PRIMARY KEY,
    domain TEXT NOT NULL,

    -- Attractor identity
    name TEXT NOT NULL,                            -- e.g., "defined_benefit_consensus"
    description TEXT,

    -- Current position
    current_embedding FLOAT8[],
    current_grid_x INTEGER,
    current_grid_y INTEGER,
    last_observed TIMESTAMPTZ DEFAULT NOW(),

    -- Historical positions (time series)
    -- Format: [{"ts": "2024-12-24T...", "embedding": [...], "grid": [x, y]}, ...]
    position_history JSONB,

    -- Stability metrics
    mean_well_depth FLOAT8,
    total_drift_distance FLOAT8,                   -- Cumulative movement

    -- Lifecycle
    first_observed TIMESTAMPTZ DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    merged_into_id INTEGER REFERENCES meta.semantic_attractors(id),
    split_from_id INTEGER REFERENCES meta.semantic_attractors(id)
);

CREATE INDEX idx_attractors_domain ON meta.semantic_attractors(domain);
CREATE INDEX idx_attractors_name ON meta.semantic_attractors(name);

-- ============================================================================
-- GRANTS
-- ============================================================================

GRANT SELECT, INSERT, UPDATE ON meta.swarm_snapshots TO gaius;
GRANT SELECT, INSERT, UPDATE ON meta.swarm_agent_positions TO gaius;
GRANT SELECT, INSERT, UPDATE ON meta.topology_drift TO gaius;
GRANT SELECT, INSERT, UPDATE ON meta.ngrc_models TO gaius;
GRANT SELECT, INSERT, UPDATE ON meta.semantic_attractors TO gaius;

GRANT USAGE, SELECT ON SEQUENCE meta.swarm_snapshots_snapshot_id_seq TO gaius;
GRANT USAGE, SELECT ON SEQUENCE meta.swarm_agent_positions_id_seq TO gaius;
GRANT USAGE, SELECT ON SEQUENCE meta.topology_drift_id_seq TO gaius;
GRANT USAGE, SELECT ON SEQUENCE meta.ngrc_models_id_seq TO gaius;
GRANT USAGE, SELECT ON SEQUENCE meta.semantic_attractors_id_seq TO gaius;

-- ============================================================================
-- COMMENT DOCUMENTATION
-- ============================================================================

COMMENT ON TABLE meta.swarm_snapshots IS
'Point-in-time capture of swarm state. Each run is a snapshot of a living topology.';

COMMENT ON TABLE meta.swarm_agent_positions IS
'Individual agent positions within a swarm snapshot. Captures CLT embeddings and grid positions.';

COMMENT ON TABLE meta.topology_drift IS
'Tracks how consensus positions change over time. Enables drift detection and well-depth measurement.';

COMMENT ON TABLE meta.ngrc_models IS
'NG-RC models that learn dx/dt = f(x, KB(t)). Enables forward dynamics prediction without LLM calls.';

COMMENT ON TABLE meta.semantic_attractors IS
'Named stable states in semantic space. Tracks ontological drift as meanings evolve.';

COMMENT ON COLUMN meta.topology_drift.well_depth IS
'1/variance - measures entrenchment. High = deep well = stable but potentially stuck.';

COMMENT ON COLUMN meta.topology_drift.lyapunov_exponent IS
'Negative = stable attractor, positive = chaotic/unstable, near-zero = edge of chaos.';

COMMENT ON COLUMN meta.ngrc_models.kb_modulation_weights IS
'Maps KB state to flow field modulation for non-autonomous dynamics: dx/dt = f(x, KB(t))';

-- migrate:down
DROP TABLE IF EXISTS meta.semantic_attractors CASCADE;
DROP TABLE IF EXISTS meta.ngrc_models CASCADE;
DROP TABLE IF EXISTS meta.topology_drift CASCADE;
DROP TABLE IF EXISTS meta.swarm_agent_positions CASCADE;
DROP TABLE IF EXISTS meta.swarm_snapshots CASCADE;
