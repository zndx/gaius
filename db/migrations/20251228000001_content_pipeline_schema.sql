-- migrate:up

-- Add triage columns to content_items for autonomous pipeline processing
-- These columns enable the two-stage triage: heuristic → LLM → KB creation
ALTER TABLE content_items
ADD COLUMN IF NOT EXISTS heuristic_score INTEGER,
ADD COLUMN IF NOT EXISTS llm_quality_score INTEGER,
ADD COLUMN IF NOT EXISTS content_hash TEXT,
ADD COLUMN IF NOT EXISTS summary_excluded BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS exclusion_reason TEXT;

-- Indexes for efficient triage processing
-- Items needing heuristic scoring (never scored)
CREATE INDEX IF NOT EXISTS idx_content_heuristic_null ON content_items(fetched_at DESC)
    WHERE heuristic_score IS NULL;

-- Items that passed heuristic but need LLM scoring
CREATE INDEX IF NOT EXISTS idx_content_llm_pending ON content_items(heuristic_score DESC)
    WHERE llm_quality_score IS NULL AND NOT COALESCE(summary_excluded, false);

-- Content hash for duplicate detection
CREATE INDEX IF NOT EXISTS idx_content_hash ON content_items(content_hash)
    WHERE content_hash IS NOT NULL;

-- Items ready for KB write (high quality, not processed)
CREATE INDEX IF NOT EXISTS idx_content_kb_pending ON content_items(llm_quality_score DESC)
    WHERE llm_quality_score >= 50
      AND processed_at IS NULL
      AND NOT COALESCE(summary_excluded, false);

-- Triage lineage table for tracking assessment history
CREATE TABLE IF NOT EXISTS triage_assessments (
    id SERIAL PRIMARY KEY,
    content_item_id INTEGER REFERENCES content_items(id) ON DELETE CASCADE,
    assessment_type TEXT NOT NULL CHECK (assessment_type IN ('heuristic', 'llm')),
    score INTEGER NOT NULL CHECK (score >= 0 AND score <= 100),
    details JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_triage_assessments_item ON triage_assessments(content_item_id);
CREATE INDEX IF NOT EXISTS idx_triage_assessments_type ON triage_assessments(assessment_type);

-- Pipeline monitoring view - shows backlog at each stage
CREATE OR REPLACE VIEW v_pipeline_status AS
SELECT
    'fetch' as stage,
    COUNT(*) FILTER (WHERE status = 'pending') as pending,
    COUNT(*) FILTER (WHERE status = 'completed' AND completed_at > NOW() - interval '1 hour') as completed_1h,
    0 as backlog_warn,
    100 as backlog_critical
FROM fetch_jobs
UNION ALL
SELECT 'heuristic_triage',
    COUNT(*) FILTER (WHERE heuristic_score IS NULL),
    COUNT(*) FILTER (WHERE heuristic_score IS NOT NULL AND fetched_at > NOW() - interval '1 hour'),
    200,
    500
FROM content_items
UNION ALL
SELECT 'llm_triage',
    COUNT(*) FILTER (WHERE heuristic_score >= 30 AND llm_quality_score IS NULL AND NOT COALESCE(summary_excluded, false)),
    COUNT(*) FILTER (WHERE llm_quality_score IS NOT NULL AND fetched_at > NOW() - interval '1 hour'),
    100,
    300
FROM content_items
UNION ALL
SELECT 'kb_write',
    COUNT(*) FILTER (WHERE llm_quality_score >= 50 AND processed_at IS NULL AND NOT COALESCE(summary_excluded, false)),
    COUNT(*) FILTER (WHERE processed_at IS NOT NULL AND processed_at > NOW() - interval '1 hour'),
    50,
    150
FROM content_items;

-- Task watchdog view - monitors scheduled_tasks for stuck/stale tasks
CREATE OR REPLACE VIEW v_task_watchdog AS
SELECT
    task_type,
    COUNT(*) FILTER (WHERE picked_up_at IS NULL AND scheduled_for < NOW() - interval '30 minutes') as stale_pending,
    COUNT(*) FILTER (WHERE picked_up_at IS NOT NULL AND completed_at IS NULL AND picked_up_at < NOW() - interval '10 minutes') as stuck_running,
    COUNT(*) FILTER (WHERE completed_at > NOW() - interval '1 hour') as completed_1h,
    COUNT(*) FILTER (WHERE error IS NOT NULL AND completed_at > NOW() - interval '24 hours') as failed_24h
FROM scheduled_tasks
GROUP BY task_type;

-- Pipeline throughput summary for the last 24 hours
CREATE OR REPLACE VIEW v_pipeline_throughput AS
WITH hourly AS (
    SELECT
        date_trunc('hour', fetched_at) as hour,
        COUNT(*) as fetched,
        COUNT(*) FILTER (WHERE heuristic_score IS NOT NULL) as heuristic_scored,
        COUNT(*) FILTER (WHERE llm_quality_score IS NOT NULL) as llm_scored,
        COUNT(*) FILTER (WHERE processed_at IS NOT NULL) as written_to_kb,
        COUNT(*) FILTER (WHERE summary_excluded = true) as excluded
    FROM content_items
    WHERE fetched_at > NOW() - interval '24 hours'
    GROUP BY date_trunc('hour', fetched_at)
)
SELECT
    hour,
    fetched,
    heuristic_scored,
    llm_scored,
    written_to_kb,
    excluded,
    ROUND(100.0 * heuristic_scored / NULLIF(fetched, 0), 1) as heuristic_rate,
    ROUND(100.0 * written_to_kb / NULLIF(llm_scored, 0), 1) as kb_conversion_rate
FROM hourly
ORDER BY hour DESC;

-- migrate:down

DROP VIEW IF EXISTS v_pipeline_throughput;
DROP VIEW IF EXISTS v_task_watchdog;
DROP VIEW IF EXISTS v_pipeline_status;
DROP TABLE IF EXISTS triage_assessments;
ALTER TABLE content_items DROP COLUMN IF EXISTS exclusion_reason;
ALTER TABLE content_items DROP COLUMN IF EXISTS summary_excluded;
ALTER TABLE content_items DROP COLUMN IF EXISTS content_hash;
ALTER TABLE content_items DROP COLUMN IF EXISTS llm_quality_score;
ALTER TABLE content_items DROP COLUMN IF EXISTS heuristic_score;
DROP INDEX IF EXISTS idx_content_kb_pending;
DROP INDEX IF EXISTS idx_content_hash;
DROP INDEX IF EXISTS idx_content_llm_pending;
DROP INDEX IF EXISTS idx_content_heuristic_null;
