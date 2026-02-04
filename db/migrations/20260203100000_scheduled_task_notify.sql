-- Scheduled Task NOTIFY Trigger
-- ==============================
-- Enables LISTEN/NOTIFY for real-time task processing when engine is running.
--
-- When pg_cron inserts a task, this trigger fires NOTIFY on 'scheduled_task_ready'.
-- The engine's ScheduledTaskProcessor listens on this channel and picks up tasks.

-- ============================================================================
-- NOTIFY Trigger Function
-- ============================================================================

CREATE OR REPLACE FUNCTION notify_scheduled_task()
RETURNS TRIGGER AS $$
BEGIN
    -- Send notification with task_type and id for efficient pickup
    PERFORM pg_notify(
        'scheduled_task_ready',
        json_build_object(
            'id', NEW.id,
            'task_type', NEW.task_type,
            'scheduled_for', NEW.scheduled_for
        )::text
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Trigger on INSERT
-- ============================================================================

DROP TRIGGER IF EXISTS scheduled_task_notify_trigger ON scheduled_tasks;

CREATE TRIGGER scheduled_task_notify_trigger
    AFTER INSERT ON scheduled_tasks
    FOR EACH ROW
    EXECUTE FUNCTION notify_scheduled_task();

-- ============================================================================
-- Comments
-- ============================================================================

COMMENT ON FUNCTION notify_scheduled_task() IS
'Sends pg_notify on scheduled_task_ready channel when new task is inserted.
Engine listens on this channel to process tasks in real-time.';

COMMENT ON TRIGGER scheduled_task_notify_trigger ON scheduled_tasks IS
'Fires NOTIFY for real-time task processing by engine.
Falls back to polling if engine is down during INSERT.';
