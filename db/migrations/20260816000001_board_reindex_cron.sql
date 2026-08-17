-- migrate:up
-- Continuous board reindex: current_state IS the KB. The UI is current
-- because this clock never stops (tautology), not because someone
-- refreshed a cache.

CREATE TABLE IF NOT EXISTS meta.board_reindex_state (
    key TEXT PRIMARY KEY,
    last_run_at TIMESTAMPTZ,
    run_count INTEGER DEFAULT 0,
    last_generation BIGINT,
    last_n_documents INTEGER
);

INSERT INTO meta.board_reindex_state (key, last_run_at, run_count)
VALUES ('board_reindex', NULL, 0)
ON CONFLICT (key) DO NOTHING;

-- 60s gate so a stuck cycle does not pile cron inserts
CREATE OR REPLACE FUNCTION meta.should_run_board_reindex()
RETURNS BOOLEAN AS $$
DECLARE
    v_last_run TIMESTAMPTZ;
BEGIN
    SELECT last_run_at INTO v_last_run
    FROM meta.board_reindex_state
    WHERE key = 'board_reindex';

    IF v_last_run IS NULL THEN
        RETURN TRUE;
    END IF;

    RETURN EXTRACT(EPOCH FROM (NOW() - v_last_run)) >= 60;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION meta.mark_board_reindex_started(
    p_generation BIGINT DEFAULT NULL,
    p_n_documents INTEGER DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    UPDATE meta.board_reindex_state
    SET last_run_at = NOW(),
        run_count = run_count + 1,
        last_generation = COALESCE(p_generation, last_generation),
        last_n_documents = COALESCE(p_n_documents, last_n_documents)
    WHERE key = 'board_reindex';
END;
$$ LANGUAGE plpgsql;

SELECT cron.unschedule('board-reindex')
WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'board-reindex');

SELECT cron.schedule(
    'board-reindex',
    '* * * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      SELECT 'board_reindex', '{}'::jsonb, 'pg_cron', NOW()
      WHERE meta.should_run_board_reindex()
        AND NOT EXISTS (
          SELECT 1 FROM scheduled_tasks
          WHERE task_type = 'board_reindex'
            AND picked_up_at IS NULL
            AND completed_at IS NULL
        )$$
);

GRANT SELECT, INSERT, UPDATE ON meta.board_reindex_state TO gaius;
GRANT EXECUTE ON FUNCTION meta.should_run_board_reindex() TO gaius;
GRANT EXECUTE ON FUNCTION meta.mark_board_reindex_started(BIGINT, INTEGER) TO gaius;

COMMENT ON TABLE meta.board_reindex_state IS
'Clock for continuous 19x19 board reindex. UI reads current_state; this job is why that row is current.';

-- migrate:down

SELECT cron.unschedule('board-reindex')
WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'board-reindex');

DROP FUNCTION IF EXISTS meta.mark_board_reindex_started(BIGINT, INTEGER);
DROP FUNCTION IF EXISTS meta.should_run_board_reindex();
DROP TABLE IF EXISTS meta.board_reindex_state;
