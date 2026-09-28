-- migrate:up

-- One row per workload. scheduled_tasks cleanup must not be the only memory
-- of an Airflow success: the newest thousand rows are hours of per-minute jobs.
CREATE TABLE IF NOT EXISTS meta.airflow_workload_ticks (
    task_type text PRIMARY KEY,
    completed_at timestamptz NOT NULL,
    dag_id text NOT NULL DEFAULT '',
    dag_run_id text NOT NULL DEFAULT '',
    outcome text NOT NULL DEFAULT ''
);

SELECT cron.unschedule(jobid)
  FROM cron.job
 WHERE jobname = 'cleanup-scheduled-tasks';

-- Keep the short tail, and also the newest successful row of every class.
SELECT cron.schedule(
    'cleanup-scheduled-tasks',
    '0 3 * * 0',
    $$DELETE FROM scheduled_tasks
      WHERE id NOT IN (
          SELECT id FROM scheduled_tasks
          ORDER BY created_at DESC
          LIMIT 1000
      )
      AND id NOT IN (
          SELECT DISTINCT ON (task_type) id
            FROM scheduled_tasks
           WHERE completed_at IS NOT NULL
             AND COALESCE(error, '') = ''
             AND COALESCE(NULLIF(result->>'status', ''), 'completed')
                 IN ('completed', 'ok', 'success')
           ORDER BY task_type, completed_at DESC
      )$$
);

-- migrate:down

SELECT cron.unschedule(jobid)
  FROM cron.job
 WHERE jobname = 'cleanup-scheduled-tasks';

SELECT cron.schedule(
    'cleanup-scheduled-tasks',
    '0 3 * * 0',
    $$DELETE FROM scheduled_tasks
      WHERE id NOT IN (
          SELECT id FROM scheduled_tasks
          ORDER BY created_at DESC
          LIMIT 1000
      )$$
);

DROP TABLE IF EXISTS meta.airflow_workload_ticks;
