-- migrate:up
-- Cognition cycle is Airflow-declared (gaius_cognition_cycle). Released
-- scheduled__ runs on 2026-09-08/09 proved the path. Retire the pg_cron
-- twin so Airflow is the only clock (thoughts brief is written in-cycle).

DO $$
DECLARE jid bigint;
BEGIN
  SELECT jobid INTO jid FROM cron.job WHERE jobname = 'cognition-periodic';
  IF jid IS NOT NULL THEN
    PERFORM cron.unschedule(jid);
  END IF;
END $$;

-- migrate:down
SELECT cron.schedule(
    'cognition-periodic',
    '43 0,4,8,12,16,20 * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('cognition_cycle', '{"trigger": "scheduled"}', 'pg_cron',
              NOW() + (random() * INTERVAL '45 minutes'))$$
);
