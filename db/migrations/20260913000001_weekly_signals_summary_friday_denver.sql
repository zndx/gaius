-- migrate:up
-- Weekly Signals Summary: Friday 06:00 America/Denver (early morning).
-- Airflow is the active clock (catalog cron + timezone). pg_cron is the SoR
-- twin: same payload/gate, UTC encoding of 06:00 Denver (12:00 MDT / 13:00 MST),
-- kept INACTIVE while Airflow orders Metaflow/task via Signals.
-- previous=false: Friday morning summarizes the current ISO week so far.

CREATE OR REPLACE FUNCTION meta.should_run_weekly_signals_summary()
RETURNS BOOLEAN AS $$
DECLARE
    v_last_week TEXT;
    v_this_week TEXT;
BEGIN
    SELECT last_iso_week INTO v_last_week
    FROM meta.weekly_signals_summary_state
    WHERE key = 'weekly_signals_summary';

    v_this_week := to_char((NOW() AT TIME ZONE 'America/Denver')::date, 'IYYY-"W"IW');

    IF v_last_week IS NULL THEN
        RETURN TRUE;
    END IF;

    RETURN v_last_week <> v_this_week;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE jid bigint;
BEGIN
  SELECT jobid INTO jid FROM cron.job WHERE jobname = 'weekly-signals-summary';
  IF jid IS NOT NULL THEN
    PERFORM cron.unschedule(jid);
  END IF;
  PERFORM cron.schedule(
    'weekly-signals-summary',
    '0 12,13 * * 5',
    $job$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      SELECT 'weekly_signals_summary', '{"previous": false}'::jsonb, 'pg_cron', NOW()
      WHERE meta.should_run_weekly_signals_summary()
        AND EXTRACT(HOUR FROM NOW() AT TIME ZONE 'America/Denver') = 6
        AND NOT EXISTS (
          SELECT 1 FROM scheduled_tasks
          WHERE task_type = 'weekly_signals_summary'
            AND picked_up_at IS NULL
            AND completed_at IS NULL
        )$job$
  );
  UPDATE cron.job SET active = false WHERE jobname = 'weekly-signals-summary';
END $$;

COMMENT ON TABLE meta.weekly_signals_summary_state IS
'Clock for weekly Signals Summary (S2S remotes). One zettel per ISO week; Friday 06:00 America/Denver.';

-- migrate:down

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

DO $$
DECLARE jid bigint;
BEGIN
  SELECT jobid INTO jid FROM cron.job WHERE jobname = 'weekly-signals-summary';
  IF jid IS NOT NULL THEN
    PERFORM cron.unschedule(jid);
  END IF;
  PERFORM cron.schedule(
    'weekly-signals-summary',
    '0 15 * * 1',
    $job$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      SELECT 'weekly_signals_summary', '{"previous": true}'::jsonb, 'pg_cron', NOW()
      WHERE meta.should_run_weekly_signals_summary()
        AND NOT EXISTS (
          SELECT 1 FROM scheduled_tasks
          WHERE task_type = 'weekly_signals_summary'
            AND picked_up_at IS NULL
            AND completed_at IS NULL
        )$job$
  );
  UPDATE cron.job SET active = false WHERE jobname = 'weekly-signals-summary';
END $$;
