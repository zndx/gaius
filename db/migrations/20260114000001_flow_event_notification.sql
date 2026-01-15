-- migrate:up

-- ============================================================================
-- Flow Event Notification System
-- ============================================================================
-- Implements PostgreSQL LISTEN/NOTIFY for event-driven flow coordination.
-- Replaces polling-based approach with immediate push notifications when
-- flows complete or fail.
--
-- Architecture:
-- - Trigger fires on status change to 'completed' or 'failed'
-- - pg_notify sends JSON payload to 'flow_events' channel
-- - FlowEventListener in engine receives notifications (~5-10ms latency)
-- - Audit table provides event history for debugging

-- Audit table for flow completion events
CREATE TABLE meta.flow_events (
    event_id SERIAL PRIMARY KEY,
    run_id UUID NOT NULL,
    flow_type TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB DEFAULT '{}',
    CONSTRAINT fk_flow_events_run_id
        FOREIGN KEY (run_id)
        REFERENCES meta.flow_runs(run_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_meta_flow_events_run_id ON meta.flow_events(run_id);
CREATE INDEX idx_meta_flow_events_status ON meta.flow_events(status);
CREATE INDEX idx_meta_flow_events_created_at ON meta.flow_events(created_at DESC);
CREATE INDEX idx_meta_flow_events_flow_type ON meta.flow_events(flow_type, created_at DESC);

COMMENT ON TABLE meta.flow_events IS 'Audit trail for flow completion events (LISTEN/NOTIFY)';
COMMENT ON COLUMN meta.flow_events.run_id IS 'References meta.flow_runs';
COMMENT ON COLUMN meta.flow_events.flow_type IS 'Type of flow (ResearchFlow, ArxivDoclingFlow, etc.)';
COMMENT ON COLUMN meta.flow_events.status IS 'Terminal status: completed or failed';

-- Notification trigger function
-- Fires pg_notify on 'flow_events' channel when status changes to terminal state
CREATE OR REPLACE FUNCTION meta.notify_flow_event() RETURNS TRIGGER AS $$
BEGIN
    -- Only notify on status changes to completed/failed
    IF NEW.status IN ('completed', 'failed') AND
       (OLD.status IS NULL OR OLD.status != NEW.status) THEN

        -- Send notification to channel
        PERFORM pg_notify(
            'flow_events',
            json_build_object(
                'run_id', NEW.run_id::text,
                'flow_type', NEW.flow_type,
                'status', NEW.status,
                'started_at', COALESCE(NEW.started_at::text, ''),
                'completed_at', COALESCE(NEW.completed_at::text, ''),
                'duration_ms', COALESCE(NEW.duration_ms, 0)
            )::text
        );

        -- Insert audit record
        INSERT INTO meta.flow_events (
            run_id, flow_type, status, started_at, completed_at, duration_ms
        ) VALUES (
            NEW.run_id, NEW.flow_type, NEW.status,
            NEW.started_at, NEW.completed_at, NEW.duration_ms
        );
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION meta.notify_flow_event() IS
    'Trigger function for flow completion LISTEN/NOTIFY';

-- Attach trigger to meta.flow_runs
CREATE TRIGGER meta_flow_runs_notify
    AFTER UPDATE ON meta.flow_runs
    FOR EACH ROW
    EXECUTE FUNCTION meta.notify_flow_event();

COMMENT ON TRIGGER meta_flow_runs_notify ON meta.flow_runs IS
    'Fires pg_notify when flow status changes to completed/failed';

-- Add updated_at column to flow_runs if not exists (for fallback polling)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'meta'
        AND table_name = 'flow_runs'
        AND column_name = 'updated_at'
    ) THEN
        ALTER TABLE meta.flow_runs
        ADD COLUMN updated_at TIMESTAMPTZ DEFAULT NOW();

        CREATE INDEX idx_meta_flow_runs_updated_at
        ON meta.flow_runs(updated_at DESC);
    END IF;
END $$;

-- Update timestamp trigger for fallback polling support
CREATE OR REPLACE FUNCTION meta.update_flow_runs_timestamp() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER meta_flow_runs_update_timestamp
    BEFORE UPDATE ON meta.flow_runs
    FOR EACH ROW
    EXECUTE FUNCTION meta.update_flow_runs_timestamp();

-- migrate:down

DROP TRIGGER IF EXISTS meta_flow_runs_notify ON meta.flow_runs;
DROP TRIGGER IF EXISTS meta_flow_runs_update_timestamp ON meta.flow_runs;
DROP FUNCTION IF EXISTS meta.notify_flow_event();
DROP FUNCTION IF EXISTS meta.update_flow_runs_timestamp();
DROP TABLE IF EXISTS meta.flow_events;

-- Remove updated_at column if we added it
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'meta'
        AND table_name = 'flow_runs'
        AND column_name = 'updated_at'
    ) THEN
        ALTER TABLE meta.flow_runs DROP COLUMN IF EXISTS updated_at;
    END IF;
END $$;
