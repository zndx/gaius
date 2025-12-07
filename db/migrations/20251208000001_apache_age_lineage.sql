-- migrate:up

-- ============================================================================
-- Apache AGE Extension for Lineage Graph (Optional)
-- ============================================================================
-- NOTE: Apache AGE provides graph capabilities for lineage traversal.
-- If AGE is not installed, this section is skipped and lineage_events
-- table will still work for storing OpenLineage events.
-- Graph materialization will be disabled at runtime.

-- Try to enable Apache AGE extension (graceful if not available)
DO $$
BEGIN
    -- Check if AGE extension exists in pg_available_extensions
    IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'age') THEN
        CREATE EXTENSION IF NOT EXISTS age;
        RAISE NOTICE 'Apache AGE extension enabled';
    ELSE
        RAISE NOTICE 'Apache AGE not available - skipping graph setup';
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Could not enable AGE: %. Continuing without graph support.', SQLERRM;
END $$;

-- Create graph and labels only if AGE was successfully installed
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'age') THEN
        -- Load AGE into session
        EXECUTE 'LOAD ''age''';

        -- Set search path for AGE functions
        EXECUTE 'SET search_path = ag_catalog, "$user", public';

        -- Create the gaius_hx lineage graph
        PERFORM ag_catalog.create_graph('gaius_hx');

        -- Create vertex labels for OpenLineage entities
        PERFORM ag_catalog.create_vlabel('gaius_hx', 'Dataset');  -- Data sources/sinks
        PERFORM ag_catalog.create_vlabel('gaius_hx', 'Job');      -- Processing jobs
        PERFORM ag_catalog.create_vlabel('gaius_hx', 'Run');      -- Job executions

        -- Create edge labels for relationships
        PERFORM ag_catalog.create_elabel('gaius_hx', 'INPUT_TO');  -- Dataset -> Run
        PERFORM ag_catalog.create_elabel('gaius_hx', 'OUTPUTS');   -- Run -> Dataset
        PERFORM ag_catalog.create_elabel('gaius_hx', 'PARENT');    -- Run -> Run (parent relationship)
        PERFORM ag_catalog.create_elabel('gaius_hx', 'EXECUTES'); -- Job -> Run

        -- Reset search path
        EXECUTE 'SET search_path = "$user", public';

        RAISE NOTICE 'AGE graph gaius_hx created with vertex and edge labels';
    ELSE
        RAISE NOTICE 'Skipping graph creation - AGE not installed';
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Could not create AGE graph: %. Continuing without graph.', SQLERRM;
    -- Reset search path in case of error
    EXECUTE 'SET search_path = "$user", public';
END $$;

-- ============================================================================
-- OpenLineage Events Table (works without AGE)
-- ============================================================================
-- Stores raw OpenLineage events for audit and replay
-- Graph materialization happens asynchronously when AGE is available

CREATE TABLE IF NOT EXISTS lineage_events (
    id SERIAL PRIMARY KEY,
    event_type TEXT NOT NULL DEFAULT 'RunEvent',
    event_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id UUID NOT NULL,
    job_namespace TEXT NOT NULL,
    job_name TEXT NOT NULL,
    run_state TEXT CHECK (run_state IN ('START', 'RUNNING', 'COMPLETE', 'FAIL', 'ABORT')),
    inputs JSONB DEFAULT '[]'::jsonb,
    outputs JSONB DEFAULT '[]'::jsonb,
    facets JSONB DEFAULT '{}'::jsonb,
    parent_run_id UUID,  -- For nested runs
    processed BOOLEAN DEFAULT FALSE,  -- Whether materialized to graph
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for lineage queries
CREATE INDEX idx_lineage_run ON lineage_events(run_id);
CREATE INDEX idx_lineage_job ON lineage_events(job_namespace, job_name);
CREATE INDEX idx_lineage_time ON lineage_events(event_time DESC);
CREATE INDEX idx_lineage_unprocessed ON lineage_events(created_at) WHERE NOT processed;
CREATE INDEX idx_lineage_parent ON lineage_events(parent_run_id) WHERE parent_run_id IS NOT NULL;

-- GIN index for JSONB queries on inputs/outputs
CREATE INDEX idx_lineage_inputs ON lineage_events USING GIN (inputs);
CREATE INDEX idx_lineage_outputs ON lineage_events USING GIN (outputs);

COMMENT ON TABLE lineage_events IS 'OpenLineage standard events for data lineage tracking';
COMMENT ON COLUMN lineage_events.job_namespace IS 'Job namespace (e.g., gaius.fetch, gaius.summarize)';
COMMENT ON COLUMN lineage_events.job_name IS 'Job name (e.g., arxiv, batch)';
COMMENT ON COLUMN lineage_events.inputs IS 'Array of input datasets [{namespace, name, facets}]';
COMMENT ON COLUMN lineage_events.outputs IS 'Array of output datasets [{namespace, name, facets}]';

-- ============================================================================
-- Iceberg Configuration Table
-- ============================================================================
-- PyIceberg SQL catalog will create its own tables (iceberg_tables, etc.)
-- This table stores our configuration and preferences

CREATE TABLE IF NOT EXISTS iceberg_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Default configuration for gaius_hx
INSERT INTO iceberg_config (key, value, description) VALUES
    ('warehouse', 's3://zndx-gaius/hx/', 'S3/MinIO warehouse path'),
    ('namespace', 'raw', 'Default Iceberg namespace'),
    ('catalog_name', 'gaius_hx', 'PyIceberg catalog name'),
    ('use_minio', 'true', 'Use MinIO as primary storage'),
    ('filesystem_fallback', '.iceberg', 'Filesystem warehouse relative to KB root')
ON CONFLICT (key) DO NOTHING;

-- ============================================================================
-- Content Items Extension
-- ============================================================================
-- Add columns to track Iceberg storage and summarization status

ALTER TABLE content_items
ADD COLUMN IF NOT EXISTS iceberg_id TEXT,
ADD COLUMN IF NOT EXISTS iceberg_snapshot_id BIGINT,
ADD COLUMN IF NOT EXISTS summarized_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS summary_kb_path TEXT,
ADD COLUMN IF NOT EXISTS summary_excluded BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS exclusion_reason TEXT;

-- Index for finding content that needs summarization
CREATE INDEX IF NOT EXISTS idx_content_unsummarized
    ON content_items(fetched_at DESC)
    WHERE summarized_at IS NULL
      AND processed_at IS NOT NULL
      AND NOT COALESCE(summary_excluded, FALSE);

-- Index for finding excluded content (lineage tracking)
CREATE INDEX IF NOT EXISTS idx_content_excluded
    ON content_items(source_id, fetched_at DESC)
    WHERE summary_excluded = TRUE;

COMMENT ON COLUMN content_items.iceberg_id IS 'UUID of record in Iceberg raw_content table';
COMMENT ON COLUMN content_items.iceberg_snapshot_id IS 'Iceberg snapshot ID when content was written';
COMMENT ON COLUMN content_items.summarized_at IS 'When this content was summarized to KB';
COMMENT ON COLUMN content_items.summary_kb_path IS 'KB path where summary was written';
COMMENT ON COLUMN content_items.summary_excluded IS 'Whether content was excluded from summarization';
COMMENT ON COLUMN content_items.exclusion_reason IS 'Why content was excluded (quality, relevance, etc.)';

-- ============================================================================
-- Summary Lineage Table
-- ============================================================================
-- Links KB summaries back to their raw content sources

CREATE TABLE IF NOT EXISTS summary_lineage (
    id SERIAL PRIMARY KEY,
    kb_path TEXT NOT NULL UNIQUE,

    -- Iceberg source
    iceberg_table TEXT DEFAULT 'gaius_hx.raw_content',
    iceberg_record_id TEXT,
    iceberg_snapshot_id BIGINT,

    -- Content item reference
    content_item_id INTEGER REFERENCES content_items(id),

    -- Summarization metadata
    model_used TEXT,
    quality_score FLOAT CHECK (quality_score >= 0 AND quality_score <= 1),
    tokens_input INTEGER,
    tokens_output INTEGER,

    -- OpenLineage reference
    lineage_run_id UUID,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for lineage queries
CREATE INDEX idx_summary_content ON summary_lineage(content_item_id);
CREATE INDEX idx_summary_run ON summary_lineage(lineage_run_id);
CREATE INDEX idx_summary_model ON summary_lineage(model_used);
CREATE INDEX idx_summary_quality ON summary_lineage(quality_score DESC);

COMMENT ON TABLE summary_lineage IS 'Links KB summaries to raw Iceberg content for provenance';

-- ============================================================================
-- Helper Functions
-- ============================================================================

-- Function to check if AGE is available
CREATE OR REPLACE FUNCTION age_available() RETURNS BOOLEAN AS $$
BEGIN
    PERFORM 1 FROM pg_extension WHERE extname = 'age';
    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- Function to get lineage for a KB path
CREATE OR REPLACE FUNCTION get_kb_lineage(p_kb_path TEXT)
RETURNS TABLE (
    kb_path TEXT,
    source_title TEXT,
    source_url TEXT,
    source_type TEXT,
    iceberg_id TEXT,
    quality_score FLOAT,
    summarized_at TIMESTAMPTZ,
    lineage_run_id UUID
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        sl.kb_path,
        ci.title,
        ci.url,
        s.source_type,
        sl.iceberg_record_id,
        sl.quality_score,
        ci.summarized_at,
        sl.lineage_run_id
    FROM summary_lineage sl
    JOIN content_items ci ON sl.content_item_id = ci.id
    JOIN sources s ON ci.source_id = s.id
    WHERE sl.kb_path = p_kb_path;
END;
$$ LANGUAGE plpgsql;

-- Function to record a lineage event
CREATE OR REPLACE FUNCTION record_lineage_event(
    p_run_id UUID,
    p_job_namespace TEXT,
    p_job_name TEXT,
    p_run_state TEXT,
    p_inputs JSONB DEFAULT '[]'::jsonb,
    p_outputs JSONB DEFAULT '[]'::jsonb,
    p_facets JSONB DEFAULT '{}'::jsonb,
    p_parent_run_id UUID DEFAULT NULL
) RETURNS INTEGER AS $$
DECLARE
    v_event_id INTEGER;
BEGIN
    INSERT INTO lineage_events (
        run_id, job_namespace, job_name, run_state,
        inputs, outputs, facets, parent_run_id
    ) VALUES (
        p_run_id, p_job_namespace, p_job_name, p_run_state,
        p_inputs, p_outputs, p_facets, p_parent_run_id
    ) RETURNING id INTO v_event_id;

    RETURN v_event_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Scheduled Task Type for Summarization
-- ============================================================================
-- Add summarize_batch to scheduled_tasks if the table exists

DO $$
BEGIN
    -- Check if scheduled_tasks table exists
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'scheduled_tasks') THEN
        -- Check if task_type has a check constraint we need to update
        -- For now, just ensure the table can accept 'summarize_batch' as a type
        NULL;
    END IF;
END $$;

-- migrate:down

-- Drop functions
DROP FUNCTION IF EXISTS get_kb_lineage(TEXT);
DROP FUNCTION IF EXISTS record_lineage_event(UUID, TEXT, TEXT, TEXT, JSONB, JSONB, JSONB, UUID);
DROP FUNCTION IF EXISTS age_available();

-- Drop summary_lineage table
DROP TABLE IF EXISTS summary_lineage;

-- Remove columns from content_items
ALTER TABLE content_items
DROP COLUMN IF EXISTS iceberg_id,
DROP COLUMN IF EXISTS iceberg_snapshot_id,
DROP COLUMN IF EXISTS summarized_at,
DROP COLUMN IF EXISTS summary_kb_path,
DROP COLUMN IF EXISTS summary_excluded,
DROP COLUMN IF EXISTS exclusion_reason;

-- Drop indexes (will be dropped with tables, but explicit for clarity)
DROP INDEX IF EXISTS idx_content_unsummarized;
DROP INDEX IF EXISTS idx_content_excluded;

-- Drop iceberg_config
DROP TABLE IF EXISTS iceberg_config;

-- Drop lineage_events
DROP TABLE IF EXISTS lineage_events;

-- Drop AGE graph (if AGE is available)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'age') THEN
        SET search_path = ag_catalog, "$user", public;
        PERFORM drop_graph('gaius_hx', true);
        SET search_path = "$user", public;
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Could not drop AGE graph: %', SQLERRM;
END $$;

-- Drop AGE extension
DROP EXTENSION IF EXISTS age CASCADE;
