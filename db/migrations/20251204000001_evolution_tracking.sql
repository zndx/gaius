-- migrate:up

-- Add evaluation type to existing agent_evaluations
ALTER TABLE agent_evaluations
ADD COLUMN IF NOT EXISTS eval_type TEXT DEFAULT 'training'
    CHECK (eval_type IN ('training', 'held_out', 'real_world'));

ALTER TABLE agent_evaluations
ADD COLUMN IF NOT EXISTS task_category TEXT;

ALTER TABLE agent_evaluations
ADD COLUMN IF NOT EXISTS task_difficulty FLOAT;

CREATE INDEX IF NOT EXISTS idx_agent_evaluations_type
ON agent_evaluations(eval_type);

CREATE INDEX IF NOT EXISTS idx_agent_evaluations_category
ON agent_evaluations(task_category);

-- Held-out query pool (rolling window of recent queries not used for training)
CREATE TABLE held_out_queries (
    id SERIAL PRIMARY KEY,
    query_hash TEXT UNIQUE NOT NULL,  -- SHA256 of query for dedup
    input_prompt TEXT NOT NULL,
    expected_output TEXT,  -- Optional gold standard
    context TEXT,
    domain TEXT,
    category TEXT,
    difficulty FLOAT,

    -- Source tracking
    source_type TEXT NOT NULL,  -- 'swarm', 'research', 'manual'
    source_id TEXT,

    -- Lifecycle
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    use_count INTEGER DEFAULT 0,

    -- Exclude from training
    excluded_from_training BOOLEAN DEFAULT TRUE,
    exclusion_reason TEXT DEFAULT 'held_out_pool'
);

CREATE INDEX idx_held_out_domain ON held_out_queries(domain);
CREATE INDEX idx_held_out_category ON held_out_queries(category);
CREATE INDEX idx_held_out_created ON held_out_queries(created_at DESC);
CREATE INDEX idx_held_out_unused ON held_out_queries(last_used_at NULLS FIRST);

-- Evolution cycle history
CREATE TABLE evolution_cycles (
    id SERIAL PRIMARY KEY,
    agent_id TEXT NOT NULL,
    version_before TEXT REFERENCES agent_versions(version_id),
    version_after TEXT REFERENCES agent_versions(version_id),

    -- Cycle details
    strategy TEXT NOT NULL,  -- 'apo', 'gepa', 'hybrid'
    trigger_type TEXT NOT NULL,  -- 'idle', 'manual', 'scheduled'

    -- Results
    success BOOLEAN NOT NULL,
    improvement_percent FLOAT DEFAULT 0.0,
    baseline_score FLOAT,
    final_score FLOAT,

    -- Metrics
    training_examples_used INTEGER DEFAULT 0,
    held_out_examples_used INTEGER DEFAULT 0,
    candidates_evaluated INTEGER DEFAULT 0,

    -- Evaluation scores
    training_scores JSONB DEFAULT '{}',
    held_out_scores JSONB DEFAULT '{}',

    -- Timing
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,
    preempted BOOLEAN DEFAULT FALSE,

    -- Error tracking
    error TEXT
);

CREATE INDEX idx_evolution_cycles_agent ON evolution_cycles(agent_id);
CREATE INDEX idx_evolution_cycles_success ON evolution_cycles(success);
CREATE INDEX idx_evolution_cycles_started ON evolution_cycles(started_at DESC);
CREATE INDEX idx_evolution_cycles_improvement ON evolution_cycles(improvement_percent DESC);

-- Daily evaluation summaries
CREATE TABLE daily_eval_summaries (
    id SERIAL PRIMARY KEY,
    eval_date DATE NOT NULL,

    -- Aggregate metrics
    total_cycles INTEGER DEFAULT 0,
    successful_cycles INTEGER DEFAULT 0,
    total_improvement_percent FLOAT DEFAULT 0.0,

    -- Per-agent breakdown
    agent_summaries JSONB DEFAULT '{}',
    -- {
    --   "leader": {
    --     "cycles": 3,
    --     "improvement": 2.5,
    --     "training_score": 0.85,
    --     "held_out_score": 0.82,
    --     "score_delta": -0.03
    --   }
    -- }

    -- Held-out evaluation results
    held_out_results JSONB DEFAULT '{}',
    -- {
    --   "total_evals": 50,
    --   "avg_score": 0.83,
    --   "by_category": {"reasoning": 0.85, "synthesis": 0.80}
    -- }

    -- Trend indicators
    trend_direction TEXT,  -- 'improving', 'stable', 'declining'
    trend_confidence FLOAT,

    -- Notes
    notes TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(eval_date)
);

CREATE INDEX idx_daily_summaries_date ON daily_eval_summaries(eval_date DESC);

-- View: Recent evolution performance
CREATE VIEW evolution_performance AS
SELECT
    agent_id,
    COUNT(*) as total_cycles,
    COUNT(*) FILTER (WHERE success) as successful_cycles,
    AVG(improvement_percent) FILTER (WHERE success) as avg_improvement,
    MAX(improvement_percent) as best_improvement,
    AVG(EXTRACT(EPOCH FROM (completed_at - started_at)) * 1000) as avg_duration_ms,
    MAX(started_at) as last_cycle_at
FROM evolution_cycles
WHERE started_at > NOW() - INTERVAL '7 days'
GROUP BY agent_id;

-- View: Held-out vs training score comparison (overfitting detection)
CREATE VIEW eval_score_comparison AS
SELECT
    e.version_id,
    v.agent_id,
    AVG(e.overall_score) FILTER (WHERE e.eval_type = 'training') as training_score,
    AVG(e.overall_score) FILTER (WHERE e.eval_type = 'held_out') as held_out_score,
    COUNT(*) FILTER (WHERE e.eval_type = 'training') as training_count,
    COUNT(*) FILTER (WHERE e.eval_type = 'held_out') as held_out_count,
    -- Overfitting indicator: training much higher than held-out
    AVG(e.overall_score) FILTER (WHERE e.eval_type = 'training') -
    AVG(e.overall_score) FILTER (WHERE e.eval_type = 'held_out') as overfit_gap
FROM agent_evaluations e
JOIN agent_versions v ON e.version_id = v.version_id
GROUP BY e.version_id, v.agent_id
HAVING COUNT(*) FILTER (WHERE e.eval_type = 'held_out') > 0;

-- migrate:down

DROP VIEW IF EXISTS eval_score_comparison;
DROP VIEW IF EXISTS evolution_performance;
DROP TABLE IF EXISTS daily_eval_summaries;
DROP TABLE IF EXISTS evolution_cycles;
DROP TABLE IF EXISTS held_out_queries;

ALTER TABLE agent_evaluations DROP COLUMN IF EXISTS eval_type;
ALTER TABLE agent_evaluations DROP COLUMN IF EXISTS task_category;
ALTER TABLE agent_evaluations DROP COLUMN IF EXISTS task_difficulty;
