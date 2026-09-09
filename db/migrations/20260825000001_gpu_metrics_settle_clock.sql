-- migrate:up
-- Clock: Gaius pg_cron dispatches gpu_metrics_settle (Iceberg verify +
-- Kudu DROP RANGE). Signals :5455 pg_cron runs the same honesty SQL.
-- Metaflow/Airflow analog closed hours first.

-- Catch-up: 20260828000002 already retired this clock. Do not resurrect it.
DO $$
DECLARE jid bigint;
BEGIN
  SELECT jobid INTO jid FROM cron.job WHERE jobname = 'gpu-metrics-settle';
  IF jid IS NOT NULL THEN
    PERFORM cron.unschedule(jid);
  END IF;
END $$;

-- migrate:down
SELECT cron.unschedule('gpu-metrics-settle')
WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'gpu-metrics-settle');
