-- migrate:up
-- Airflow is the coordinated hub. ambient_synthesis and fmp_roll were still
-- ticking from pg_cron while their DAGs stayed paused, so GPU burn had no
-- Airflow run (observed 2026-09-12: Metaflow 4551 synthesize + 4549 compact
-- with idle LocalExecutor workers). Deactivate, do not drop.

UPDATE cron.job
   SET active = false
 WHERE jobname IN (
   'ambient-synthesis',
   'fmp-roll'
 );

-- migrate:down
UPDATE cron.job
   SET active = true
 WHERE jobname IN (
   'ambient-synthesis',
   'fmp-roll'
 );
