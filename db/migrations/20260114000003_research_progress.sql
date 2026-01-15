-- migrate:up

-- ============================================================================
-- Research Progress Events (Structured Message Bus)
-- ============================================================================
-- Fine-grained progress events for ResearchFlow steps, enabling real-time
-- TUI updates via PostgreSQL LISTEN/NOTIFY instead of stdout parsing.
--
-- Event types match ResearchFlowEvent.Type proto enum:
-- 1=queued, 2=memories_retrieving, 3=memories_retrieved, 4=pass_started,
-- 5=pass_search, 6=pass_swarm, 7=pass_grok, 8=pass_evaluate,
-- 9=pass_qupdate, 10=pass_completed, 11=converged, 12=final_synthesis,
-- 13=kb_write, 14=completed, 15=failed
--
-- Flow writes events here; engine LISTENs on 'research_progress' channel.

CREATE TABLE meta.research_progress (
    event_id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    event_type INTEGER NOT NULL,
    event_name TEXT NOT NULL,
    pass_number INTEGER DEFAULT 0,
    progress REAL DEFAULT 0.0,
    message TEXT DEFAULT '',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Session-based queries (get all events for a session)
CREATE INDEX idx_research_progress_session ON meta.research_progress(session_id, event_id);
-- Recent events (for polling fallback)
CREATE INDEX idx_research_progress_created ON meta.research_progress(created_at DESC);
-- Cleanup (prune old events)
CREATE INDEX idx_research_progress_session_created ON meta.research_progress(session_id, created_at DESC);

COMMENT ON TABLE meta.research_progress IS 'Fine-grained ResearchFlow progress events for TUI streaming';
COMMENT ON COLUMN meta.research_progress.session_id IS 'Research session ID (e.g., res_20260114_070504)';
COMMENT ON COLUMN meta.research_progress.event_type IS 'Event type enum (matches ResearchFlowEvent.Type proto)';
COMMENT ON COLUMN meta.research_progress.event_name IS 'Human-readable event name (e.g., pass_search, converged)';
COMMENT ON COLUMN meta.research_progress.pass_number IS 'Current pass number (1-indexed, 0 for non-pass events)';
COMMENT ON COLUMN meta.research_progress.progress IS 'Progress 0.0-1.0 for progress bar display';
COMMENT ON COLUMN meta.research_progress.metadata IS 'Additional event data (q_value, sources_count, etc.)';

-- ============================================================================
-- LISTEN/NOTIFY Trigger for Real-Time Progress
-- ============================================================================
-- Fires on every INSERT, pushing events to connected clients immediately.
-- Channel: 'research_progress'

CREATE OR REPLACE FUNCTION meta.notify_research_progress() RETURNS TRIGGER AS $$
BEGIN
    -- Push notification for every new event
    PERFORM pg_notify(
        'research_progress',
        json_build_object(
            'event_id', NEW.event_id,
            'session_id', NEW.session_id,
            'event_type', NEW.event_type,
            'event_name', NEW.event_name,
            'pass_number', NEW.pass_number,
            'progress', NEW.progress,
            'message', NEW.message,
            'metadata', NEW.metadata
        )::text
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER research_progress_notify
    AFTER INSERT ON meta.research_progress
    FOR EACH ROW
    EXECUTE FUNCTION meta.notify_research_progress();

COMMENT ON FUNCTION meta.notify_research_progress() IS
    'Push research progress events via pg_notify on insert';
COMMENT ON TRIGGER research_progress_notify ON meta.research_progress IS
    'Real-time progress streaming to TUI via LISTEN/NOTIFY';

-- ============================================================================
-- Cleanup Function (Prune old events)
-- ============================================================================
-- Call periodically to remove events older than retention period.

CREATE OR REPLACE FUNCTION meta.cleanup_research_progress(
    retention_hours INTEGER DEFAULT 24
) RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM meta.research_progress
    WHERE created_at < NOW() - (retention_hours || ' hours')::INTERVAL;

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION meta.cleanup_research_progress(INTEGER) IS
    'Prune research progress events older than retention period';

-- migrate:down

DROP TRIGGER IF EXISTS research_progress_notify ON meta.research_progress;
DROP FUNCTION IF EXISTS meta.notify_research_progress();
DROP FUNCTION IF EXISTS meta.cleanup_research_progress(INTEGER);
DROP TABLE IF EXISTS meta.research_progress;
