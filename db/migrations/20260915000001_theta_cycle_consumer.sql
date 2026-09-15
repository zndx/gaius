-- migrate:up

-- Airflow gaius_theta_cycle is the initiator. The INSERT-only twin is cover.
SELECT cron.unschedule(jobid)
  FROM cron.job
 WHERE jobname = 'theta-weekly-consolidation';

-- Stale latent-Qdrant era rows must not be drained as "honest" consolidations.
UPDATE theta_consolidation_runs
   SET status = 'failed',
       completed_at = COALESCE(completed_at, NOW()),
       error = '#THETA.00000008.STALESLICE Qdrant latent store empty; superseded 2026-09-15; consolidation input is cognition_thoughts'
 WHERE status IN ('scheduled', 'running')
   AND slice_id <> (to_char(NOW() AT TIME ZONE 'UTC', 'IYYY') || '-W' || to_char(NOW() AT TIME ZONE 'UTC', 'IW'));

-- migrate:down

SELECT cron.schedule(
    'theta-weekly-consolidation',
    '0 6 * * 1',
    $$SELECT schedule_theta_consolidation()$$
);
