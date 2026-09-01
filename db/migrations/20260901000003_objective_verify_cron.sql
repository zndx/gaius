-- migrate:up

-- Objective verification cadence: every 6 hours, off the :00/:30 marks.
-- The objective_verify task verifies every declared objective (site
-- freshness 3-way compare first), writes objective_verifications, and
-- silver-resolves upstream probe forecasts in the efficacy ledger —
-- the outcome side of "probes forecast, objectives resolve".

SELECT cron.schedule(
    'objective-verify',
    '38 1,7,13,19 * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, priority, source)
      VALUES ('objective_verify', '{}', 'normal', 'pg_cron')$$
);

-- migrate:down

SELECT cron.unschedule('objective-verify');
