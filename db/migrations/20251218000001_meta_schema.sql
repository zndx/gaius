-- migrate:up

-- ============================================================================
-- MetaAgent Analytics Schema
-- ============================================================================
-- Provides materialized analytics views for Metabase dashboards covering:
-- - OpenLineage graph (provenance, data dependencies)
-- - Operations (flow runs, agent performance, GPU utilization)
-- - KB geometry (topology, document clusters)

CREATE SCHEMA IF NOT EXISTS meta;
COMMENT ON SCHEMA meta IS 'MetaAgent analytics tables for Metabase dashboards';

-- ============================================================================
-- Lineage Analytics
-- ============================================================================

-- Deduplicated dataset registry extracted from lineage_events
CREATE TABLE meta.dataset_catalog (
    dataset_id TEXT PRIMARY KEY,      -- namespace:name
    namespace TEXT NOT NULL,          -- gaius.kb, gaius.source, gaius.qdrant, etc.
    name TEXT NOT NULL,
    first_seen TIMESTAMPTZ,
    last_seen TIMESTAMPTZ,
    total_reads INTEGER DEFAULT 0,
    total_writes INTEGER DEFAULT 0
);

CREATE INDEX idx_meta_dataset_namespace ON meta.dataset_catalog(namespace);

-- Deduplicated job registry extracted from lineage_events
CREATE TABLE meta.job_catalog (
    job_id TEXT PRIMARY KEY,          -- namespace.name
    namespace TEXT NOT NULL,
    name TEXT NOT NULL,
    first_run TIMESTAMPTZ,
    last_run TIMESTAMPTZ,
    total_runs INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    avg_duration_ms DOUBLE PRECISION
);

CREATE INDEX idx_meta_job_namespace ON meta.job_catalog(namespace);

-- Flattened lineage edges: source -> target via job
CREATE TABLE meta.data_dependencies (
    id SERIAL PRIMARY KEY,
    source_dataset_id TEXT REFERENCES meta.dataset_catalog(dataset_id),
    target_dataset_id TEXT REFERENCES meta.dataset_catalog(dataset_id),
    via_job_id TEXT REFERENCES meta.job_catalog(job_id),
    first_observed TIMESTAMPTZ,
    last_observed TIMESTAMPTZ,
    occurrence_count INTEGER DEFAULT 1,
    UNIQUE(source_dataset_id, target_dataset_id, via_job_id)
);

CREATE INDEX idx_meta_deps_source ON meta.data_dependencies(source_dataset_id);
CREATE INDEX idx_meta_deps_target ON meta.data_dependencies(target_dataset_id);

-- ============================================================================
-- Operations Analytics
-- ============================================================================

-- Materialized view of all flow executions
CREATE TABLE meta.flow_runs (
    run_id UUID PRIMARY KEY,
    flow_type TEXT NOT NULL,          -- arxiv_docling, meta_sync, etc.
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,
    status TEXT,                      -- running, completed, failed
    inputs_count INTEGER DEFAULT 0,
    outputs_count INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_meta_flow_runs_type ON meta.flow_runs(flow_type, started_at DESC);
CREATE INDEX idx_meta_flow_runs_status ON meta.flow_runs(status);

-- Denormalized daily agent metrics
CREATE TABLE meta.agent_performance (
    agent_id TEXT NOT NULL,
    date DATE NOT NULL,
    active_version_id TEXT,
    evaluations_count INTEGER DEFAULT 0,
    avg_overall_score DOUBLE PRECISION,
    evolution_cycles INTEGER DEFAULT 0,
    improvement_percent DOUBLE PRECISION,
    PRIMARY KEY (agent_id, date)
);

CREATE INDEX idx_meta_agent_perf_date ON meta.agent_performance(date DESC);

-- Time-series GPU metrics (sampled)
CREATE TABLE meta.gpu_utilization (
    timestamp TIMESTAMPTZ NOT NULL,
    gpu_index INTEGER NOT NULL,
    memory_used_mb INTEGER,
    memory_total_mb INTEGER,
    utilization_percent DOUBLE PRECISION,
    temperature_c INTEGER,
    active_endpoint TEXT,
    PRIMARY KEY (timestamp, gpu_index)
);

-- Partition by time for efficient queries
CREATE INDEX idx_meta_gpu_time ON meta.gpu_utilization(timestamp DESC);

-- Hourly inference throughput aggregates
CREATE TABLE meta.inference_throughput (
    hour TIMESTAMPTZ NOT NULL,
    model TEXT NOT NULL,
    requests_count INTEGER DEFAULT 0,
    tokens_generated BIGINT DEFAULT 0,
    avg_latency_ms DOUBLE PRECISION,
    p95_latency_ms DOUBLE PRECISION,
    PRIMARY KEY (hour, model)
);

-- ============================================================================
-- KB Topology Analytics
-- ============================================================================

-- Time-series topology evolution (from grid_snapshots)
CREATE TABLE meta.kb_topology (
    snapshot_id INTEGER PRIMARY KEY,
    computed_at TIMESTAMPTZ,
    n_documents INTEGER,
    coverage DOUBLE PRECISION,        -- Grid coverage (0-1)
    h0_count INTEGER,                 -- Connected components (Betti-0)
    h1_count INTEGER,                 -- Loops (Betti-1)
    h2_count INTEGER,                 -- Voids (Betti-2)
    entropy DOUBLE PRECISION,         -- Persistence entropy
    avg_curvature DOUBLE PRECISION,
    avg_complexity DOUBLE PRECISION
);

CREATE INDEX idx_meta_kb_topology_time ON meta.kb_topology(computed_at DESC);

-- Pre-computed cluster assignments (from HDBSCAN on grid_points)
CREATE TABLE meta.document_clusters (
    id SERIAL PRIMARY KEY,
    snapshot_id INTEGER REFERENCES meta.kb_topology(snapshot_id),
    cluster_id INTEGER,
    centroid_x INTEGER,
    centroid_y INTEGER,
    document_count INTEGER,
    dominant_domain TEXT,
    topic_keywords TEXT[],
    avg_persistence DOUBLE PRECISION
);

CREATE INDEX idx_meta_clusters_snapshot ON meta.document_clusters(snapshot_id);

-- Named semantic regions (auto-generated or user-labeled)
CREATE TABLE meta.semantic_regions (
    region_id SERIAL PRIMARY KEY,
    name TEXT,
    grid_bounds JSONB,                -- {x_min, x_max, y_min, y_max}
    document_paths TEXT[],
    dominant_topics TEXT[],
    boundary_curvature DOUBLE PRECISION,
    computed_at TIMESTAMPTZ
);

-- ============================================================================
-- NiFi Flow Tracking
-- ============================================================================

-- Track projected Metaflow flows in NiFi
CREATE TABLE meta.nifi_flows (
    id SERIAL PRIMARY KEY,
    flow_id TEXT NOT NULL UNIQUE,
    flow_name TEXT NOT NULL,
    process_group_id TEXT,
    metaflow_name TEXT,               -- Source Metaflow class name
    processor_count INTEGER DEFAULT 0,
    connection_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'projected',  -- projected, active, archived
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_meta_nifi_flows_status ON meta.nifi_flows(status);

-- ============================================================================
-- Sync Tracking
-- ============================================================================

-- Track sync watermarks for incremental updates
CREATE TABLE meta.sync_watermarks (
    sync_type TEXT PRIMARY KEY,       -- lineage, operations, topology
    last_sync_at TIMESTAMPTZ,
    last_event_id BIGINT,
    records_synced INTEGER DEFAULT 0
);

INSERT INTO meta.sync_watermarks (sync_type) VALUES
    ('lineage'),
    ('operations'),
    ('topology')
ON CONFLICT DO NOTHING;

-- migrate:down
DROP SCHEMA IF EXISTS meta CASCADE;
