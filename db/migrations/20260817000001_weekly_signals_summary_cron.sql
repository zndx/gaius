-- migrate:up
-- Weekly Signals Summary: S2S remotes + commits/notes → scratch wWW-summary.
-- Airflow will schedule Metaflow when available; pg_cron is the listener now.
-- Monday 15:00 UTC = 09:00 America/Denver (MDT).

CREATE TABLE IF NOT EXISTS meta.weekly_signals_summary_state (
    key TEXT PRIMARY KEY,
    last_run_at TIMESTAMPTZ,
    last_iso_week TEXT,
    last_path TEXT,
    run_count INTEGER DEFAULT 0
);

INSERT INTO meta.weekly_signals_summary_state (key, last_run_at, run_count)
VALUES ('weekly_signals_summary', NULL, 0)
ON CONFLICT (key) DO NOTHING;

-- One insert per ISO week (the week that just ended when Monday fires).
CREATE OR REPLACE FUNCTION meta.should_run_weekly_signals_summary()
RETURNS BOOLEAN AS $$
DECLARE
    v_last_week TEXT;
    v_prev_week TEXT;
BEGIN
    SELECT last_iso_week INTO v_last_week
    FROM meta.weekly_signals_summary_state
    WHERE key = 'weekly_signals_summary';

    v_prev_week := to_char(date_trunc('week', NOW() AT TIME ZONE 'UTC') - interval '7 days', 'IYYY-"W"IW');

    IF v_last_week IS NULL THEN
        RETURN TRUE;
    END IF;

    RETURN v_last_week <> v_prev_week;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION meta.mark_weekly_signals_summary_started(
    p_iso_week TEXT DEFAULT NULL,
    p_path TEXT DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    UPDATE meta.weekly_signals_summary_state
    SET last_run_at = NOW(),
        run_count = run_count + 1,
        last_iso_week = COALESCE(p_iso_week, last_iso_week),
        last_path = COALESCE(p_path, last_path)
    WHERE key = 'weekly_signals_summary';
END;
$$ LANGUAGE plpgsql;

SELECT cron.unschedule('weekly-signals-summary')
WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'weekly-signals-summary');

SELECT cron.schedule(
    'weekly-signals-summary',
    '0 15 * * 1',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      SELECT 'weekly_signals_summary', '{"previous": true}'::jsonb, 'pg_cron', NOW()
      WHERE meta.should_run_weekly_signals_summary()
        AND NOT EXISTS (
          SELECT 1 FROM scheduled_tasks
          WHERE task_type = 'weekly_signals_summary'
            AND picked_up_at IS NULL
            AND completed_at IS NULL
        )$$
);

GRANT SELECT, INSERT, UPDATE ON meta.weekly_signals_summary_state TO gaius;
GRANT EXECUTE ON FUNCTION meta.should_run_weekly_signals_summary() TO gaius;
GRANT EXECUTE ON FUNCTION meta.mark_weekly_signals_summary_started(TEXT, TEXT) TO gaius;

COMMENT ON TABLE meta.weekly_signals_summary_state IS
'Clock for weekly Signals Summary (S2S remotes). One zettel per ISO week.';

-- migrate:down

SELECT cron.unschedule('weekly-signals-summary')
WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'weekly-signals-summary');

DROP FUNCTION IF EXISTS meta.mark_weekly_signals_summary_started(TEXT, TEXT);
DROP FUNCTION IF EXISTS meta.should_run_weekly_signals_summary();
DROP TABLE IF EXISTS meta.weekly_signals_summary_state;
