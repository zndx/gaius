-- migrate:up
-- Thin TUI Architecture: State management tables for instant startup
-- Supports TUI/CLI/MCP unified state with idempotent operations

-- Create grid_snapshots table if it doesn't exist
CREATE TABLE IF NOT EXISTS grid_snapshots (
    id SERIAL PRIMARY KEY,
    kb_root TEXT NOT NULL,
    snapshot_data JSONB NOT NULL DEFAULT '{}',
    document_count INT DEFAULT 0,
    cluster_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_grid_snapshots_kb_root
    ON grid_snapshots(kb_root);

-- Add generation tracking to grid_snapshots for sync protocol
ALTER TABLE grid_snapshots ADD COLUMN IF NOT EXISTS generation BIGINT DEFAULT 0;
ALTER TABLE grid_snapshots ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- Create index for generation-based queries
CREATE INDEX IF NOT EXISTS idx_grid_snapshots_generation
    ON grid_snapshots(kb_root, generation DESC);

-- Current state cache: fast reads for instant TUI startup
-- Denormalized JSON for <50ms load time
CREATE TABLE IF NOT EXISTS current_state (
    kb_root TEXT PRIMARY KEY,
    snapshot_id INT REFERENCES grid_snapshots(id) ON DELETE SET NULL,
    generation BIGINT DEFAULT 0,
    state_json JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE current_state IS 'Cached grid state for instant TUI startup. Denormalized for fast reads.';
COMMENT ON COLUMN current_state.generation IS 'Monotonic counter for sync protocol. Only update if incoming > current.';
COMMENT ON COLUMN current_state.state_json IS 'Complete GridState as JSON: documents, clusters, allocations, tda, geometry.';

-- UI preferences: per-client settings that survive restarts
CREATE TABLE IF NOT EXISTS ui_preferences (
    client_id TEXT PRIMARY KEY,
    cursor_x INT DEFAULT 9,
    cursor_y INT DEFAULT 9,
    view_mode TEXT DEFAULT 'go',
    overlay_mode TEXT DEFAULT 'none',
    iso_mode TEXT DEFAULT 'curvature',
    center_panel_mode TEXT DEFAULT 'graph',
    left_panel_visible BOOLEAN DEFAULT TRUE,
    right_panel_visible BOOLEAN DEFAULT TRUE,
    domain TEXT,
    preferences_json JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE ui_preferences IS 'Per-client UI state. TUI/CLI/MCP each have their own preferences.';

-- State changes audit log for idempotency debugging and history
CREATE TABLE IF NOT EXISTS state_changes (
    id SERIAL PRIMARY KEY,
    kb_root TEXT NOT NULL,
    client_id TEXT,
    change_type TEXT NOT NULL,
    generation BIGINT,
    change_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_state_changes_kb_root
    ON state_changes(kb_root, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_state_changes_client
    ON state_changes(client_id, created_at DESC);

COMMENT ON TABLE state_changes IS 'Audit log of all state mutations for debugging idempotency issues.';
COMMENT ON COLUMN state_changes.change_type IS 'Type: init, reindex, cursor_move, domain_change, preference_update, prune';

-- Command history: unified across TUI/CLI/MCP
CREATE TABLE IF NOT EXISTS command_history (
    id SERIAL PRIMARY KEY,
    client_id TEXT NOT NULL,
    kb_root TEXT,
    command TEXT NOT NULL,
    args_json JSONB,
    success BOOLEAN,
    offline BOOLEAN DEFAULT FALSE,
    result_json JSONB,
    duration_ms INT,
    executed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_command_history_client
    ON command_history(client_id, executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_command_history_kb
    ON command_history(kb_root, executed_at DESC);

COMMENT ON TABLE command_history IS 'Unified command history across all entry points.';
COMMENT ON COLUMN command_history.offline IS 'True if command was attempted while Engine unavailable.';

-- Function to update generation atomically
CREATE OR REPLACE FUNCTION update_current_state(
    p_kb_root TEXT,
    p_snapshot_id INT,
    p_state_json JSONB
) RETURNS BIGINT AS $$
DECLARE
    new_gen BIGINT;
BEGIN
    -- Get next generation (atomic)
    INSERT INTO current_state (kb_root, snapshot_id, generation, state_json)
    VALUES (p_kb_root, p_snapshot_id, 1, p_state_json)
    ON CONFLICT (kb_root) DO UPDATE SET
        snapshot_id = EXCLUDED.snapshot_id,
        generation = current_state.generation + 1,
        state_json = EXCLUDED.state_json,
        updated_at = NOW()
    RETURNING generation INTO new_gen;

    RETURN new_gen;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_current_state IS 'Atomically update state with incremented generation. Returns new generation.';

-- Function for idempotent state update (only if generation is higher)
CREATE OR REPLACE FUNCTION upsert_current_state_if_newer(
    p_kb_root TEXT,
    p_snapshot_id INT,
    p_generation BIGINT,
    p_state_json JSONB
) RETURNS BOOLEAN AS $$
DECLARE
    updated BOOLEAN;
BEGIN
    INSERT INTO current_state (kb_root, snapshot_id, generation, state_json)
    VALUES (p_kb_root, p_snapshot_id, p_generation, p_state_json)
    ON CONFLICT (kb_root) DO UPDATE SET
        snapshot_id = EXCLUDED.snapshot_id,
        generation = EXCLUDED.generation,
        state_json = EXCLUDED.state_json,
        updated_at = NOW()
    WHERE current_state.generation < EXCLUDED.generation;

    GET DIAGNOSTICS updated = ROW_COUNT;
    RETURN updated > 0;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION upsert_current_state_if_newer IS 'Idempotent update: only applies if incoming generation > current.';

-- migrate:down
DROP FUNCTION IF EXISTS upsert_current_state_if_newer;
DROP FUNCTION IF EXISTS update_current_state;
DROP INDEX IF EXISTS idx_command_history_kb;
DROP INDEX IF EXISTS idx_command_history_client;
DROP TABLE IF EXISTS command_history;
DROP INDEX IF EXISTS idx_state_changes_client;
DROP INDEX IF EXISTS idx_state_changes_kb_root;
DROP TABLE IF EXISTS state_changes;
DROP TABLE IF EXISTS ui_preferences;
DROP TABLE IF EXISTS current_state;
DROP INDEX IF EXISTS idx_grid_snapshots_generation;
ALTER TABLE grid_snapshots DROP COLUMN IF EXISTS updated_at;
ALTER TABLE grid_snapshots DROP COLUMN IF EXISTS generation;
DROP INDEX IF EXISTS idx_grid_snapshots_kb_root;
DROP TABLE IF EXISTS grid_snapshots;
