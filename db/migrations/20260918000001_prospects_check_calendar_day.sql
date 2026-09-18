-- migrate:up
-- Airflow gaius_prospects_check is 07:00 UTC. A 24h wall-clock gate after
-- yesterday 07:00:30 skipped the next 07:00 as 23h59m; engine-catchup
-- stamped last_run so 07:00 was gate_false (skip ≠ success → MISSTICK).

CREATE OR REPLACE FUNCTION meta.should_run_prospects_check() RETURNS boolean
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_last_run TIMESTAMPTZ;
BEGIN
    SELECT last_run_at INTO v_last_run
    FROM meta.prospects_cron_state
    WHERE key = 'prospects_check';

    IF v_last_run IS NULL THEN
        RETURN TRUE;
    END IF;

    RETURN (timezone('UTC', v_last_run))::date < (timezone('UTC', NOW()))::date;
END;
$$;

COMMENT ON FUNCTION meta.should_run_prospects_check() IS
'TRUE if no prospects check has completed on the current UTC date.
Airflow owns 07:00; engine catch-up uses the same predicate after 07:00.';

-- migrate:down
CREATE OR REPLACE FUNCTION meta.should_run_prospects_check() RETURNS boolean
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_last_run TIMESTAMPTZ;
    v_hours_since NUMERIC;
BEGIN
    SELECT last_run_at INTO v_last_run
    FROM meta.prospects_cron_state
    WHERE key = 'prospects_check';

    IF v_last_run IS NULL THEN
        RETURN TRUE;
    END IF;

    v_hours_since := EXTRACT(EPOCH FROM (NOW() - v_last_run)) / 3600;
    RETURN v_hours_since >= 24;
END;
$$;
