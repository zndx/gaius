-- migrate:up
-- Clock: Gaius pg_cron dispatches gpu_metrics_settle (Iceberg verify +
-- Kudu DROP RANGE). Signals :5455 pg_cron runs the same honesty SQL.
-- Metaflow/Airflow analog closed hours first.

SELECT cron.unschedule('gpu-metrics-settle')
WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'gpu-metrics-settle');

SELECT cron.schedule(
    'gpu-metrics-settle',
    '5 * * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      SELECT 'gpu_metrics_settle', '{}'::jsonb, 'pg_cron', NOW()
      WHERE NOT EXISTS (
        SELECT 1 FROM scheduled_tasks
         WHERE task_type = 'gpu_metrics_settle'
           AND picked_up_at IS NULL
           AND completed_at IS NULL
      )$$
);

-- migrate:down
SELECT cron.unschedule('gpu-metrics-settle')
WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'gpu-metrics-settle');
