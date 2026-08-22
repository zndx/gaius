-- migrate:up
-- pick_up_task used to claim rows STP had already completed with
-- #STP.00000003.NOHANDLER (completed_at set, picked_up_at still NULL).
-- Skip completed rows so Cognition/STP cannot re-claim poisoned clocks.

CREATE OR REPLACE FUNCTION public.pick_up_task(p_task_types text[] DEFAULT NULL::text[])
RETURNS public.scheduled_tasks
LANGUAGE plpgsql
AS $$
DECLARE
    v_task scheduled_tasks;
BEGIN
    UPDATE scheduled_tasks
    SET picked_up_at = NOW()
    WHERE id = (
        SELECT id FROM scheduled_tasks
        WHERE picked_up_at IS NULL
          AND completed_at IS NULL
          AND scheduled_for <= NOW()
          AND (p_task_types IS NULL OR task_type = ANY(p_task_types))
        ORDER BY
            CASE priority
                WHEN 'critical' THEN 0
                WHEN 'high' THEN 1
                WHEN 'normal' THEN 2
                WHEN 'low' THEN 3
                ELSE 4
            END,
            scheduled_for
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING * INTO v_task;

    RETURN v_task;
END;
$$;

COMMENT ON FUNCTION public.pick_up_task(text[]) IS
    'Atomically claim a pending (not completed) task for execution';

-- migrate:down

CREATE OR REPLACE FUNCTION public.pick_up_task(p_task_types text[] DEFAULT NULL::text[])
RETURNS public.scheduled_tasks
LANGUAGE plpgsql
AS $$
DECLARE
    v_task scheduled_tasks;
BEGIN
    UPDATE scheduled_tasks
    SET picked_up_at = NOW()
    WHERE id = (
        SELECT id FROM scheduled_tasks
        WHERE picked_up_at IS NULL
          AND scheduled_for <= NOW()
          AND (p_task_types IS NULL OR task_type = ANY(p_task_types))
        ORDER BY
            CASE priority
                WHEN 'critical' THEN 0
                WHEN 'high' THEN 1
                WHEN 'normal' THEN 2
                WHEN 'low' THEN 3
                ELSE 4
            END,
            scheduled_for
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING * INTO v_task;

    RETURN v_task;
END;
$$;
