-- migrate:up

-- Polarity fix (found 2026-09-01 during the first Brier scoring run
-- against an externally-verified outcome): the watchdog forecast wrote
-- proposition "no live worker owns task N" with verdict fail / p=0.15,
-- i.e. P(no-live-worker)=0.15 — the OPPOSITE of the watchdog's claim.
-- A correct reset scored 0.72 and a false positive would score 0.02.
-- Convention: affirmative proposition ("a live worker owns task N"),
-- verdict fail (p=0.15 = low P(alive)). Resolutions:
--   flow-was-alive  -> outcome=true  (reset was a miss,  Brier 0.72)
--   worker-was-dead -> outcome=false (reset was correct, Brier 0.02)
-- Existing rows keep their original wording+resolutions (append-only
-- history) and are excluded from scoring by their 'pg_cron' epoch.

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
            'a live worker owns task ' || v.id,
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
            'pg_cron_v2'
        FROM victims v
    )
    UPDATE scheduled_tasks st
    SET picked_up_at = NULL, error = 'reset by watchdog: stuck running'
    FROM victims v
    WHERE st.id = v.id$$
);

-- migrate:down

SELECT cron.unschedule('task-watchdog');
-- Restore the (polarity-inverted) v1 forecast job from 20260901000002.
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
            'watchdog:pg_cron.task_reset', 'cron.task-watchdog', 'watchdog',
            'no live worker owns task ' || v.id, 'fail', 0.15,
            jsonb_build_object('picked_up_at', v.picked_up_at),
            'watchdog_reset', v.task_type, v.id, 'CLAIMED', 'pg_cron'
        FROM victims v
    )
    UPDATE scheduled_tasks st
    SET picked_up_at = NULL, error = 'reset by watchdog: stuck running'
    FROM victims v
    WHERE st.id = v.id$$
);
