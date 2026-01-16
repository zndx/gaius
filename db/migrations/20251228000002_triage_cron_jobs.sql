-- migrate:up
-- NOTE: This migration requires pg_cron to be enabled and configured.
-- If pg_cron is not available, these jobs will need to be scheduled externally.

-- Heuristic triage: every hour at :05 (after feed fetches at :00/:15/:30/:45)
-- Scores 100 items per run using fast keyword/pattern matching
SELECT cron.schedule('heuristic-triage-hourly', '5 * * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('heuristic_triage', '{"limit": 100}', 'pg_cron', NOW())$$);

-- LLM triage: every 4 hours at :35 (after heuristic at :05)
-- Uses inference endpoint to assess quality of heuristic-passed items
SELECT cron.schedule('llm-triage-periodic', '35 0,4,8,12,16,20 * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('llm_triage', '{"limit": 50}', 'pg_cron', NOW())$$);

-- Content processing: every 2 hours at :45
-- Writes high-quality triaged content to KB as zettelkasten notes
SELECT cron.schedule('content-processing', '45 */2 * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('content_processing', '{"limit": 30}', 'pg_cron', NOW())$$);

-- Task watchdog: every 15 minutes at :10,:25,:40,:55
-- Resets stuck tasks that have been running too long
SELECT cron.schedule('task-watchdog', '10,25,40,55 * * * *',
    $$UPDATE scheduled_tasks
      SET picked_up_at = NULL, error = 'reset by watchdog: stuck running'
      WHERE picked_up_at IS NOT NULL
        AND completed_at IS NULL
        AND picked_up_at < NOW() - interval '15 minutes'$$);

-- migrate:down

SELECT cron.unschedule('task-watchdog');
SELECT cron.unschedule('content-processing');
SELECT cron.unschedule('llm-triage-periodic');
SELECT cron.unschedule('heuristic-triage-hourly');
