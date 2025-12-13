-- migrate:up
-- KB Sync: Filesystem to S3 sync state tracking
-- Supports multi-target sync with lineage integration

-- Sync targets (Minio local, AWS S3, etc.)
CREATE TABLE kb_sync_targets (
    id SERIAL PRIMARY KEY,
    name VARCHAR(64) UNIQUE NOT NULL,
    target_type VARCHAR(32) NOT NULL,  -- "minio" | "s3"
    endpoint VARCHAR(255) NOT NULL,
    bucket VARCHAR(255) NOT NULL,
    region VARCHAR(64),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    config JSONB DEFAULT '{}'
);

COMMENT ON TABLE kb_sync_targets IS 'S3-compatible sync targets for KB replication';
COMMENT ON COLUMN kb_sync_targets.target_type IS 'minio for local, s3 for AWS';
COMMENT ON COLUMN kb_sync_targets.config IS 'Extra config: secure, prefix, storage_class';

-- Per-file sync state
CREATE TABLE kb_sync_state (
    id SERIAL PRIMARY KEY,
    target_id INTEGER REFERENCES kb_sync_targets(id) ON DELETE CASCADE,
    file_path VARCHAR(1024) NOT NULL,
    content_hash VARCHAR(64) NOT NULL,  -- SHA-256
    size_bytes BIGINT NOT NULL,
    local_mtime TIMESTAMPTZ NOT NULL,
    remote_etag VARCHAR(64),
    synced_at TIMESTAMPTZ,
    sync_status VARCHAR(32) NOT NULL,   -- pending|synced|failed
    error_message TEXT,
    UNIQUE(target_id, file_path)
);

COMMENT ON TABLE kb_sync_state IS 'Per-file sync state for incremental sync';
COMMENT ON COLUMN kb_sync_state.content_hash IS 'SHA-256 hash of file content';
COMMENT ON COLUMN kb_sync_state.remote_etag IS 'S3/Minio ETag after upload';

-- Sync run history
CREATE TABLE kb_sync_runs (
    id SERIAL PRIMARY KEY,
    target_id INTEGER REFERENCES kb_sync_targets(id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(32) NOT NULL,        -- running|completed|failed|interrupted
    files_scanned INTEGER DEFAULT 0,
    files_uploaded INTEGER DEFAULT 0,
    files_skipped INTEGER DEFAULT 0,
    files_failed INTEGER DEFAULT 0,
    bytes_uploaded BIGINT DEFAULT 0,
    orphans_found INTEGER DEFAULT 0,
    resume_token VARCHAR(255),          -- Last processed path for resume
    error_message TEXT,
    config_snapshot JSONB               -- Frozen config at run time
);

COMMENT ON TABLE kb_sync_runs IS 'Audit trail of sync operations';
COMMENT ON COLUMN kb_sync_runs.resume_token IS 'Checkpoint for resuming interrupted syncs';

-- Indexes for efficient queries
CREATE INDEX idx_sync_state_target ON kb_sync_state(target_id, sync_status);
CREATE INDEX idx_sync_state_path ON kb_sync_state(file_path);
CREATE INDEX idx_sync_runs_target ON kb_sync_runs(target_id, started_at DESC);

-- Default Minio target (local development)
INSERT INTO kb_sync_targets (name, target_type, endpoint, bucket, config)
VALUES ('minio-local', 'minio', 'localhost:9010', 'gaius-kb', '{"secure": false}');

-- migrate:down
DROP TABLE IF EXISTS kb_sync_runs;
DROP TABLE IF EXISTS kb_sync_state;
DROP TABLE IF EXISTS kb_sync_targets;
