-- migrate:up

-- Progress doctrine: the SQL watchdog is an OUTER NET for rows orphaned by
-- engine death — the real supervision is the task processor's output-idle
-- watchdog, which kills only on demonstrated stall. The old 60-minute
-- wall-clock reset sat BELOW the median article_curate runtime (~67 min)
-- and on 2026-08-31 reset the row of a healthy, actively-rendering run
-- (flow 1805), leaving it re-claimable mid-flight. Generous thresholds:
-- long flows 4h, everything else 45m.

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
            THEN picked_up_at < NOW() - interval '4 hours'
          ELSE picked_up_at < NOW() - interval '45 minutes'
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
          WHEN task_type IN ('article_curate', 'prospects_update', 'publish_cards')
            THEN picked_up_at < NOW() - interval '60 minutes'
          ELSE picked_up_at < NOW() - interval '15 minutes'
        END$$
);
