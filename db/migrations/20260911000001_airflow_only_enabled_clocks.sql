-- migrate:up
-- Airflow is the coordinated hub for enabled catalogue kinds. WatchActivities
-- is restored (scheduler_pb2 zndx import). Dual-firing pg_cron twins would
-- publish twice at 21:00 UTC. Deactivate, do not drop, so a rollback is a flip.

UPDATE cron.job
   SET active = false
 WHERE jobname IN (
   'publish-cards-predawn',
   'publish-cards-morning',
   'publish-cards-afternoon',
   'publish-cards-evening',
   'prospects-daily-check',
   'weekly-signals-summary'
 );

-- migrate:down
UPDATE cron.job
   SET active = true
 WHERE jobname IN (
   'publish-cards-predawn',
   'publish-cards-morning',
   'publish-cards-afternoon',
   'publish-cards-evening',
   'prospects-daily-check',
   'weekly-signals-summary'
 );
