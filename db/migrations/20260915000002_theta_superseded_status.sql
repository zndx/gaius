-- migrate:up

ALTER TABLE theta_consolidation_runs DROP CONSTRAINT IF EXISTS theta_consolidation_runs_status_check;
ALTER TABLE theta_consolidation_runs ADD CONSTRAINT theta_consolidation_runs_status_check
  CHECK (status = ANY (ARRAY[
    'scheduled'::text, 'running'::text, 'completed'::text, 'failed'::text, 'superseded'::text
  ]));

UPDATE theta_consolidation_runs
   SET status = 'superseded'
 WHERE error LIKE '#THETA.00000008.STALESLICE%'
   AND status = 'failed';

-- migrate:down

UPDATE theta_consolidation_runs SET status = 'failed' WHERE status = 'superseded';
ALTER TABLE theta_consolidation_runs DROP CONSTRAINT IF EXISTS theta_consolidation_runs_status_check;
ALTER TABLE theta_consolidation_runs ADD CONSTRAINT theta_consolidation_runs_status_check
  CHECK (status = ANY (ARRAY['scheduled'::text, 'running'::text, 'completed'::text, 'failed'::text]));
