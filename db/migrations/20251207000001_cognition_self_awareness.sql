-- migrate:up

-- Cognition Self-Awareness: Thought lineage, engine observations, and scheduled tasks
-- Enables recursive self-observation and engine auditing
--
-- NOTE: Semantic similarity search for thoughts is handled by Qdrant, not PostgreSQL.
-- This migration only adds metadata columns for lineage tracking.

-- ═══════════════════════════════════════════════════════════════════════════════
-- EXTEND cognition_thoughts: Add lineage tracking for thought chains
-- ═══════════════════════════════════════════════════════════════════════════════

-- Add thought lineage columns
ALTER TABLE cognition_thoughts
ADD COLUMN IF NOT EXISTS predecessor_id UUID REFERENCES cognition_thoughts(id),
ADD COLUMN IF NOT EXISTS generation INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS thought_chain_id UUID,
ADD COLUMN IF NOT EXISTS note_path TEXT,
ADD COLUMN IF NOT EXISTS content_hash TEXT;

-- Index for navigating thought chains
CREATE INDEX IF NOT EXISTS idx_thoughts_predecessor
    ON cognition_thoughts(predecessor_id)
    WHERE predecessor_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_thoughts_chain
    ON cognition_thoughts(thought_chain_id)
    WHERE thought_chain_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_thoughts_generation
    ON cognition_thoughts(generation DESC, created_at DESC)
    WHERE generation > 0;

-- Index for finding notes
CREATE INDEX IF NOT EXISTS idx_thoughts_note_path
    ON cognition_thoughts(note_path)
    WHERE note_path IS NOT NULL;

-- Index for content hash (exact duplicate detection - semantic similarity uses Qdrant)
CREATE INDEX IF NOT EXISTS idx_thoughts_content_hash
    ON cognition_thoughts(content_hash)
    WHERE content_hash IS NOT NULL;

-- ═══════════════════════════════════════════════════════════════════════════════
-- ENGINE OBSERVATIONS: Store observations from engine monitoring
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS engine_observations (
    id SERIAL PRIMARY KEY,

    -- Source classification
    source TEXT NOT NULL,           -- evolution, scheduler, orchestrator, swarm, gpu
    observation_type TEXT NOT NULL DEFAULT 'normal',  -- normal, anomaly, milestone

    -- Content
    metrics JSONB DEFAULT '{}',     -- Raw metrics captured
    anomalies TEXT[] DEFAULT '{}',  -- List of detected anomalies
    notes TEXT,                     -- Human-readable notes

    -- Linking
    related_thought_id UUID REFERENCES cognition_thoughts(id),
    related_cycle_id INTEGER,       -- Reference to evolution_cycles.id if applicable

    -- Timestamps
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for observation queries
CREATE INDEX IF NOT EXISTS idx_engine_obs_recent
    ON engine_observations(observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_engine_obs_source
    ON engine_observations(source, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_engine_obs_anomalies
    ON engine_observations(observed_at DESC)
    WHERE cardinality(anomalies) > 0;

CREATE INDEX IF NOT EXISTS idx_engine_obs_thought
    ON engine_observations(related_thought_id)
    WHERE related_thought_id IS NOT NULL;

-- ═══════════════════════════════════════════════════════════════════════════════
-- SCHEDULED TASKS: Generic task dispatch table for pg_cron and daemon
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id SERIAL PRIMARY KEY,

    -- Task specification
    task_type TEXT NOT NULL,        -- cognition_cycle, engine_audit, content_fetch, etc.
    payload JSONB DEFAULT '{}',     -- Task-specific parameters
    priority TEXT DEFAULT 'normal', -- critical, high, normal, low

    -- Scheduling
    scheduled_for TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source TEXT DEFAULT 'manual',   -- pg_cron, daemon, manual, delta_detection

    -- Execution tracking
    picked_up_at TIMESTAMPTZ,       -- When a worker claimed this task
    completed_at TIMESTAMPTZ,       -- When execution finished

    -- Results
    result JSONB,                   -- Task output
    error TEXT,                     -- Error message if failed

    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for pending task pickup (filter scheduled_for <= NOW() at query time)
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_pending
    ON scheduled_tasks(priority, scheduled_for)
    WHERE picked_up_at IS NULL;

-- Index for recent completed tasks
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_completed
    ON scheduled_tasks(completed_at DESC)
    WHERE completed_at IS NOT NULL;

-- ═══════════════════════════════════════════════════════════════════════════════
-- PG_CRON JOBS FOR COGNITION
-- ═══════════════════════════════════════════════════════════════════════════════

-- Schedule cognition cycle every 4 hours (at 0 minutes past the hour)
SELECT cron.schedule(
    'cognition-periodic',
    '0 */4 * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('cognition_cycle', '{"trigger": "scheduled"}', 'pg_cron', NOW())$$
);

-- Schedule engine audit every hour (at 30 minutes past the hour)
SELECT cron.schedule(
    'engine-audit-hourly',
    '30 * * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('engine_audit', '{}', 'pg_cron', NOW())$$
);

-- Archive stale thoughts weekly (Sunday 2 AM)
SELECT cron.schedule(
    'archive-stale-thoughts',
    '0 2 * * 0',
    $$SELECT archive_stale_thoughts(7)$$
);

-- Clean up old scheduled tasks weekly (Sunday 3 AM) - keep last 1000
SELECT cron.schedule(
    'cleanup-scheduled-tasks',
    '0 3 * * 0',
    $$DELETE FROM scheduled_tasks
      WHERE id NOT IN (
          SELECT id FROM scheduled_tasks
          ORDER BY created_at DESC
          LIMIT 1000
      )$$
);

-- ═══════════════════════════════════════════════════════════════════════════════
-- HELPER FUNCTIONS
-- ═══════════════════════════════════════════════════════════════════════════════

-- Get the latest thought in a chain
CREATE OR REPLACE FUNCTION get_chain_head(p_chain_id UUID)
RETURNS UUID AS $$
    SELECT id FROM cognition_thoughts
    WHERE thought_chain_id = p_chain_id
    ORDER BY generation DESC, created_at DESC
    LIMIT 1;
$$ LANGUAGE SQL STABLE;

-- Get the full thought chain as an array
CREATE OR REPLACE FUNCTION get_thought_chain(p_chain_id UUID)
RETURNS UUID[] AS $$
    SELECT array_agg(id ORDER BY generation, created_at)
    FROM cognition_thoughts
    WHERE thought_chain_id = p_chain_id;
$$ LANGUAGE SQL STABLE;

-- Pick up next pending task (atomic)
CREATE OR REPLACE FUNCTION pick_up_task(p_task_types TEXT[] DEFAULT NULL)
RETURNS scheduled_tasks AS $$
DECLARE
    v_task scheduled_tasks;
BEGIN
    UPDATE scheduled_tasks
    SET picked_up_at = NOW()
    WHERE id = (
        SELECT id FROM scheduled_tasks
        WHERE picked_up_at IS NULL
          AND scheduled_for <= NOW()
          AND (p_task_types IS NULL OR task_type = ANY(p_task_types))
        ORDER BY
            CASE priority
                WHEN 'critical' THEN 0
                WHEN 'high' THEN 1
                WHEN 'normal' THEN 2
                WHEN 'low' THEN 3
                ELSE 4
            END,
            scheduled_for
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING * INTO v_task;

    RETURN v_task;
END;
$$ LANGUAGE plpgsql;

-- Complete a task
CREATE OR REPLACE FUNCTION complete_task(
    p_task_id INTEGER,
    p_result JSONB DEFAULT NULL,
    p_error TEXT DEFAULT NULL
)
RETURNS BOOLEAN AS $$
BEGIN
    UPDATE scheduled_tasks
    SET completed_at = NOW(),
        result = p_result,
        error = p_error
    WHERE id = p_task_id;

    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- Detect objective delta: schedule tasks to reach desired state
CREATE OR REPLACE FUNCTION detect_cognition_delta(p_profile TEXT DEFAULT 'default')
RETURNS TABLE(task_type TEXT, reason TEXT) AS $$
DECLARE
    v_last_thought TIMESTAMPTZ;
    v_anomaly_count INTEGER;
BEGIN
    -- Check when cognition last ran
    SELECT MAX(created_at) INTO v_last_thought
    FROM cognition_thoughts
    WHERE profile_name = p_profile;

    -- If no thoughts in 6 hours, trigger cognition
    IF v_last_thought IS NULL OR v_last_thought < NOW() - INTERVAL '6 hours' THEN
        -- Only if not already scheduled
        IF NOT EXISTS (
            SELECT 1 FROM scheduled_tasks
            WHERE task_type = 'cognition_cycle'
              AND picked_up_at IS NULL
        ) THEN
            INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
            VALUES ('cognition_cycle', '{"trigger": "stale_cognition"}', 'delta_detection', NOW());

            RETURN QUERY SELECT 'cognition_cycle'::TEXT, 'No thoughts in 6+ hours'::TEXT;
        END IF;
    END IF;

    -- Check for recent anomalies that need audit
    SELECT COUNT(*) INTO v_anomaly_count
    FROM engine_observations
    WHERE cardinality(anomalies) > 0
      AND observed_at > NOW() - INTERVAL '1 hour'
      AND related_thought_id IS NULL;  -- Not yet processed

    IF v_anomaly_count > 0 THEN
        IF NOT EXISTS (
            SELECT 1 FROM scheduled_tasks
            WHERE task_type = 'engine_audit'
              AND picked_up_at IS NULL
        ) THEN
            INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for, priority)
            VALUES ('engine_audit',
                    jsonb_build_object('anomaly_count', v_anomaly_count),
                    'delta_detection',
                    NOW(),
                    'high');

            RETURN QUERY SELECT 'engine_audit'::TEXT,
                format('%s unprocessed anomalies', v_anomaly_count)::TEXT;
        END IF;
    END IF;

    RETURN;
END;
$$ LANGUAGE plpgsql;

-- Check if exact content hash already exists (for exact duplicate detection)
-- Semantic similarity is handled by Qdrant ThoughtMemory
CREATE OR REPLACE FUNCTION is_duplicate_thought(
    p_content_hash TEXT,
    p_profile TEXT DEFAULT 'default'
)
RETURNS BOOLEAN AS $$
    SELECT EXISTS (
        SELECT 1 FROM cognition_thoughts
        WHERE content_hash = p_content_hash
          AND profile_name = p_profile
          AND status = 'active'
    );
$$ LANGUAGE SQL STABLE;

-- Count how many times exact content has been generated (by hash)
-- For semantic similarity counting, use Qdrant ThoughtMemory.count_similar_recent()
CREATE OR REPLACE FUNCTION count_exact_duplicates(
    p_content_hash TEXT,
    p_profile TEXT DEFAULT 'default',
    p_days INTEGER DEFAULT 7
)
RETURNS INTEGER AS $$
    SELECT COUNT(*)::INTEGER
    FROM cognition_thoughts
    WHERE content_hash = p_content_hash
      AND profile_name = p_profile
      AND created_at > NOW() - (p_days || ' days')::INTERVAL;
$$ LANGUAGE SQL STABLE;

-- ═══════════════════════════════════════════════════════════════════════════════
-- COMMENTS
-- ═══════════════════════════════════════════════════════════════════════════════

COMMENT ON COLUMN cognition_thoughts.predecessor_id IS 'UUID of the thought that this thought builds upon';
COMMENT ON COLUMN cognition_thoughts.generation IS 'Depth in thought chain (0 = root thought)';
COMMENT ON COLUMN cognition_thoughts.thought_chain_id IS 'Groups related thoughts into chains';
COMMENT ON COLUMN cognition_thoughts.note_path IS 'Path to the markdown note in scratch/';
COMMENT ON COLUMN cognition_thoughts.content_hash IS 'SHA256 hash for exact duplicate detection (semantic similarity uses Qdrant)';

COMMENT ON TABLE engine_observations IS 'Observations from engine monitoring for cognition auditing';
COMMENT ON TABLE scheduled_tasks IS 'Generic task dispatch for pg_cron and daemon execution';

COMMENT ON FUNCTION pick_up_task IS 'Atomically claim a pending task for execution';
COMMENT ON FUNCTION detect_cognition_delta IS 'Schedule tasks to fill gaps between desired and actual state';
COMMENT ON FUNCTION is_duplicate_thought IS 'Check if exact content hash exists (semantic similarity uses Qdrant)';
COMMENT ON FUNCTION count_exact_duplicates IS 'Count exact hash matches (semantic similarity uses Qdrant)';

-- migrate:down
DROP FUNCTION IF EXISTS count_exact_duplicates;
DROP FUNCTION IF EXISTS is_duplicate_thought;
DROP FUNCTION IF EXISTS detect_cognition_delta;
DROP FUNCTION IF EXISTS complete_task;
DROP FUNCTION IF EXISTS pick_up_task;
DROP FUNCTION IF EXISTS get_thought_chain;
DROP FUNCTION IF EXISTS get_chain_head;
SELECT cron.unschedule('cleanup-scheduled-tasks');
SELECT cron.unschedule('archive-stale-thoughts');
SELECT cron.unschedule('engine-audit-hourly');
SELECT cron.unschedule('cognition-periodic');
DROP TABLE IF EXISTS scheduled_tasks;
DROP TABLE IF EXISTS engine_observations;
ALTER TABLE cognition_thoughts DROP COLUMN IF EXISTS content_hash;
ALTER TABLE cognition_thoughts DROP COLUMN IF EXISTS note_path;
ALTER TABLE cognition_thoughts DROP COLUMN IF EXISTS thought_chain_id;
ALTER TABLE cognition_thoughts DROP COLUMN IF EXISTS generation;
ALTER TABLE cognition_thoughts DROP COLUMN IF EXISTS predecessor_id;
