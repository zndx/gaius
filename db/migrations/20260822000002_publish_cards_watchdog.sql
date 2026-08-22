-- migrate:up
-- LuxCore card enrich is ~60s/card. The 15-minute watchdog reset
-- publish_cards while RenderCards was still running, leaving the
-- listen loop blocked on the dead claim and gaius.zndx.org stale.

SELECT cron.unschedule('task-watchdog');
SELECT cron.schedule(
    'task-watchdog',
    '10,25,40,55 * * * *',
    $$UPDATE scheduled_tasks
      SET picked_up_at = NULL, error = 'reset by watchdog: stuck running'
      WHERE picked_up_at IS NOT NULL
        AND completed_at IS NULL
        AND CASE
          WHEN task_type IN ('article_curate', 'prospects_update', 'publish_cards')
            THEN picked_up_at < NOW() - interval '60 minutes'
          ELSE picked_up_at < NOW() - interval '15 minutes'
        END$$
);

-- migrate:down

SELECT cron.unschedule('task-watchdog');
SELECT cron.schedule(
    'task-watchdog',
    '10,25,40,55 * * * *',
    $$UPDATE scheduled_tasks
      SET picked_up_at = NULL, error = 'reset by watchdog: stuck running'
      WHERE picked_up_at IS NOT NULL
        AND completed_at IS NULL
        AND CASE
          WHEN task_type IN ('article_curate', 'prospects_update')
            THEN picked_up_at < NOW() - interval '60 minutes'
          ELSE picked_up_at < NOW() - interval '15 minutes'
        END$$
);
