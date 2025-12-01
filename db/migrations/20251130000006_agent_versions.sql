-- migrate:up

-- Agent versions table for configuration management and rollback
CREATE TABLE agent_versions (
    version_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    config JSONB NOT NULL,
    -- Config structure:
    -- {
    --   "system_prompt": "...",
    --   "model": "Qwen/Qwen3-Coder-30B-A3B-Instruct",
    --   "temperature": 0.7,
    --   "max_tokens": 2048,
    --   "top_p": 0.9,
    --   "frequency_penalty": 0.0,
    --   "presence_penalty": 0.0,
    --   "task_type": "reasoning",
    --   "optillm_technique": "mcts",
    --   "description": "...",
    --   "tags": ["v2", "optimized"]
    -- }
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by TEXT DEFAULT 'system',
    parent_version TEXT REFERENCES agent_versions(version_id),
    is_active BOOLEAN DEFAULT FALSE,

    -- Performance metrics (updated after evaluations)
    metrics JSONB DEFAULT '{}',
    -- Metrics structure:
    -- {
    --   "accuracy": 0.85,
    --   "coherence": 0.90,
    --   "relevance": 0.88,
    --   "completeness": 0.82
    -- }
    evaluation_count INTEGER DEFAULT 0,
    avg_overall_score FLOAT DEFAULT 0.0,
    best_overall_score FLOAT DEFAULT 0.0,

    -- Notes
    change_notes TEXT DEFAULT ''
);

CREATE INDEX idx_agent_versions_agent ON agent_versions(agent_id);
CREATE INDEX idx_agent_versions_active ON agent_versions(agent_id, is_active) WHERE is_active = TRUE;
CREATE INDEX idx_agent_versions_created ON agent_versions(created_at DESC);
CREATE INDEX idx_agent_versions_score ON agent_versions(avg_overall_score DESC);
CREATE INDEX idx_agent_versions_parent ON agent_versions(parent_version) WHERE parent_version IS NOT NULL;

-- Ensure only one active version per agent
CREATE UNIQUE INDEX idx_agent_versions_single_active
ON agent_versions(agent_id)
WHERE is_active = TRUE;

-- Evaluation history for detailed tracking
CREATE TABLE agent_evaluations (
    id SERIAL PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES agent_versions(version_id),
    overall_score FLOAT NOT NULL,
    dimension_scores JSONB DEFAULT '{}',
    -- Dimension scores structure:
    -- {
    --   "accuracy": {"score": 0.85, "feedback": "..."},
    --   "coherence": {"score": 0.90, "feedback": "..."}
    -- }
    summary TEXT,
    strengths JSONB DEFAULT '[]',
    weaknesses JSONB DEFAULT '[]',
    improvement_suggestions JSONB DEFAULT '[]',

    -- Evaluation context
    task_prompt TEXT,
    agent_output TEXT,
    context TEXT,

    -- Metadata
    evaluator_model TEXT,
    tokens_used INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_agent_evaluations_version ON agent_evaluations(version_id);
CREATE INDEX idx_agent_evaluations_created ON agent_evaluations(created_at DESC);
CREATE INDEX idx_agent_evaluations_score ON agent_evaluations(overall_score DESC);

-- Optimization runs for tracking GEPA/APO experiments
CREATE TABLE optimization_runs (
    id SERIAL PRIMARY KEY,
    agent_id TEXT NOT NULL,
    strategy TEXT NOT NULL,  -- 'apo', 'gepa', 'hybrid'
    objectives JSONB NOT NULL,  -- ["accuracy", "coherence", "efficiency"]

    -- Configuration
    config JSONB DEFAULT '{}',
    -- {
    --   "population_size": 20,
    --   "generations": 10,
    --   "mutation_rate": 0.1,
    --   "crossover_rate": 0.3
    -- }

    -- Results
    status TEXT DEFAULT 'running',  -- 'running', 'completed', 'failed'
    generations_completed INTEGER DEFAULT 0,
    pareto_front JSONB DEFAULT '[]',
    -- [
    --   {"version_id": "...", "scores": {"accuracy": 0.85, "efficiency": 0.90}, "pareto_rank": 0},
    --   ...
    -- ]
    best_version_id TEXT REFERENCES agent_versions(version_id),

    -- Timing
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    -- Notes
    notes TEXT
);

CREATE INDEX idx_optimization_runs_agent ON optimization_runs(agent_id);
CREATE INDEX idx_optimization_runs_status ON optimization_runs(status);
CREATE INDEX idx_optimization_runs_started ON optimization_runs(started_at DESC);

-- View: Active agent configurations
CREATE VIEW active_agent_configs AS
SELECT
    agent_id,
    version_id,
    config,
    avg_overall_score,
    evaluation_count,
    created_at
FROM agent_versions
WHERE is_active = TRUE;

-- View: Agent version history with parent chain
CREATE VIEW agent_version_history AS
SELECT
    v.agent_id,
    v.version_id,
    v.parent_version,
    v.is_active,
    v.avg_overall_score,
    v.evaluation_count,
    v.created_at,
    v.change_notes,
    p.version_id as parent_exists
FROM agent_versions v
LEFT JOIN agent_versions p ON v.parent_version = p.version_id
ORDER BY v.agent_id, v.created_at DESC;

-- View: Best performing versions per agent
CREATE VIEW best_agent_versions AS
SELECT DISTINCT ON (agent_id)
    agent_id,
    version_id,
    avg_overall_score,
    evaluation_count,
    config
FROM agent_versions
WHERE evaluation_count >= 3  -- Minimum evaluations for reliability
ORDER BY agent_id, avg_overall_score DESC;

-- migrate:down

DROP VIEW IF EXISTS best_agent_versions;
DROP VIEW IF EXISTS agent_version_history;
DROP VIEW IF EXISTS active_agent_configs;
DROP TABLE IF EXISTS optimization_runs;
DROP TABLE IF EXISTS agent_evaluations;
DROP TABLE IF EXISTS agent_versions;
