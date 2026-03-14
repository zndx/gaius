-- migrate:up

-- ============================================================================
-- Article Curation Progress Events (Structured Message Bus)
-- ============================================================================
-- Fine-grained progress events for ArticleCurationFlow steps, enabling real-time
-- TUI updates via PostgreSQL LISTEN/NOTIFY.
--
-- Step types for article curation:
-- select, research, acquire, draft, base, cards, complete, failed
--
-- Flow writes events here; engine LISTENs on 'article_curation_progress' channel.

CREATE TABLE meta.article_curation_progress (
    event_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    step TEXT NOT NULL,
    step_number INTEGER NOT NULL,
    total_steps INTEGER DEFAULT 9,
    progress REAL DEFAULT 0.0,
    message TEXT DEFAULT '',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Run-based queries (get all events for a run)
CREATE INDEX idx_article_curation_progress_run ON meta.article_curation_progress(run_id, event_id);
-- Recent events (for polling fallback)
CREATE INDEX idx_article_curation_progress_created ON meta.article_curation_progress(created_at DESC);

COMMENT ON TABLE meta.article_curation_progress IS 'Fine-grained ArticleCurationFlow progress events for TUI streaming';
COMMENT ON COLUMN meta.article_curation_progress.run_id IS 'Flow run ID (e.g., acf_20260202_050000)';
COMMENT ON COLUMN meta.article_curation_progress.step IS 'Step name (select, research, acquire, draft, base, cards, complete, failed)';
COMMENT ON COLUMN meta.article_curation_progress.step_number IS 'Current step number (1-9)';
COMMENT ON COLUMN meta.article_curation_progress.total_steps IS 'Total steps in pipeline (default 9)';
COMMENT ON COLUMN meta.article_curation_progress.progress IS 'Progress 0.0-1.0 for progress bar display';
COMMENT ON COLUMN meta.article_curation_progress.metadata IS 'Additional event data (slug, sources_count, cards_created, etc.)';

-- ============================================================================
-- LISTEN/NOTIFY Trigger for Real-Time Progress
-- ============================================================================
-- Fires on every INSERT, pushing events to connected clients immediately.
-- Channel: 'article_curation_progress'

CREATE OR REPLACE FUNCTION meta.notify_article_curation_progress() RETURNS TRIGGER AS $$
BEGIN
    -- Push notification for every new event
    PERFORM pg_notify(
        'article_curation_progress',
        json_build_object(
            'event_id', NEW.event_id,
            'run_id', NEW.run_id,
            'step', NEW.step,
            'step_number', NEW.step_number,
            'total_steps', NEW.total_steps,
            'progress', NEW.progress,
            'message', NEW.message,
            'metadata', NEW.metadata
        )::text
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER article_curation_progress_notify
    AFTER INSERT ON meta.article_curation_progress
    FOR EACH ROW
    EXECUTE FUNCTION meta.notify_article_curation_progress();

COMMENT ON FUNCTION meta.notify_article_curation_progress() IS
    'Push article curation progress events via pg_notify on insert';
COMMENT ON TRIGGER article_curation_progress_notify ON meta.article_curation_progress IS
    'Real-time progress streaming to TUI via LISTEN/NOTIFY';

-- ============================================================================
-- Cleanup Function (Prune old events)
-- ============================================================================

CREATE OR REPLACE FUNCTION meta.cleanup_article_curation_progress(
    retention_hours INTEGER DEFAULT 24
) RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM meta.article_curation_progress
    WHERE created_at < NOW() - (retention_hours || ' hours')::INTERVAL;

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION meta.cleanup_article_curation_progress(INTEGER) IS
    'Prune article curation progress events older than retention period';

-- migrate:down

DROP TRIGGER IF EXISTS article_curation_progress_notify ON meta.article_curation_progress;
DROP FUNCTION IF EXISTS meta.notify_article_curation_progress();
DROP FUNCTION IF EXISTS meta.cleanup_article_curation_progress(INTEGER);
DROP TABLE IF EXISTS meta.article_curation_progress;
