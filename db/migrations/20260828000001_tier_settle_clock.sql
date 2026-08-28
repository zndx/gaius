-- migrate:up
-- Clock for the product-generic Transparent Hierarchical Storage settle.
-- Gaius pg_cron (:5444) enqueues scheduled_tasks(task_type='tier_settle',
-- payload={'product': ...}); the engine ScheduledTaskProcessor claims it and
-- spawns gaius.engine.services.tier_settle, which drives the per-product
-- Kudu->Iceberg/HDF5 settle (fail-closed verify before any Kudu DROP RANGE).
-- One cron row per product; minute staggered off gpu-metrics-settle's :05.
-- latent / clt_activation add their own rows once their tier1 tables exist.

SELECT cron.unschedule('tier-settle-signal')
WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'tier-settle-signal');

SELECT cron.schedule(
    'tier-settle-signal',
    '20 * * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      SELECT 'tier_settle', '{"product":"signal"}'::jsonb, 'pg_cron', NOW()
      WHERE NOT EXISTS (
        SELECT 1 FROM scheduled_tasks
         WHERE task_type = 'tier_settle'
           AND payload->>'product' = 'signal'
           AND picked_up_at IS NULL
           AND completed_at IS NULL
      )$$
);

-- migrate:down
SELECT cron.unschedule('tier-settle-signal')
WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'tier-settle-signal');
