-- migrate:up
-- Retire the gpu_metrics settle clock: the product-generic tier_settle (signal)
-- supersedes it (signal_tier0 now carries the DCGM families), and the gpu_metrics
-- loop was fail-closing. gpu_metrics_tier1 stays as read-only history; only the
-- schedule is removed. Runs after 20260825000001 so a fresh deploy nets retired.

SELECT cron.unschedule('gpu-metrics-settle')
WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'gpu-metrics-settle');

-- migrate:down
-- Restore the gpu_metrics settle clock (see 20260825000001).
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
