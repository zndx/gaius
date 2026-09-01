-- migrate:up

-- The task-watchdog now records its own forecast IN THE SAME STATEMENT
-- that performs the reset. Previously the watchdog's false positives
-- erased their own evidence: it wrote error='reset by watchdog: ...' on
-- a row it also un-claimed, and a later successful run overwrote
-- error=NULL — the wrong verdict vanished from history. As a CTE, the
-- probe_forecasts row (observer 'watchdog:pg_cron.task_reset', verdict
-- fail on "no live worker owns task N") is captured before the evidence
-- can be overwritten. Resolution comes later: outcome=false with
-- resolver 'flow-was-alive' when runs_v3 shows the flow survived the
-- reset (the 2026-08-31 run-1805 class), or true when the worker was
-- genuinely dead. Thresholds unchanged (progress doctrine: 4h long
-- flows / 45m outer net).

SELECT cron.unschedule('task-watchdog');
SELECT cron.schedule(
    'task-watchdog',
    '10,25,40,55 * * * *',
    $$WITH victims AS (
        SELECT id, task_type, picked_up_at
        FROM scheduled_tasks
        WHERE picked_up_at IS NOT NULL
          AND completed_at IS NULL
          AND CASE
            WHEN task_type IN ('article_curate', 'prospects_update', 'publish_cards')
              THEN picked_up_at < NOW() - interval '4 hours'
            ELSE picked_up_at < NOW() - interval '45 minutes'
          END
    ), forecasts AS (
        INSERT INTO probe_forecasts (
            observer, call_site, observer_kind, proposition, verdict, p,
            evidence, side_effect, task_class, task_id, task_lifecycle,
            engine_rev
        )
        SELECT
            'watchdog:pg_cron.task_reset',
            'cron.task-watchdog',
            'watchdog',
            'no live worker owns task ' || v.id,
            'fail',
            0.15,
            jsonb_build_object(
                'picked_up_at', v.picked_up_at,
                'age_minutes', ROUND(EXTRACT(EPOCH FROM (NOW() - v.picked_up_at)) / 60)
            ),
            'watchdog_reset',
            v.task_type,
            v.id,
            'CLAIMED',
            'pg_cron'
        FROM victims v
    )
    UPDATE scheduled_tasks st
    SET picked_up_at = NULL, error = 'reset by watchdog: stuck running'
    FROM victims v
    WHERE st.id = v.id$$
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
            THEN picked_up_at < NOW() - interval '4 hours'
          ELSE picked_up_at < NOW() - interval '45 minutes'
        END$$
);
