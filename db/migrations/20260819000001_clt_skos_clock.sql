-- migrate:up
-- Living corpus clock: overlapping fetched_at watermark, quarantine,
-- label provenance. Two independently scheduled task_types.

ALTER TABLE public.admitted_item
    ADD COLUMN IF NOT EXISTS run_id TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS public.admit_progress (
    source_id TEXT PRIMARY KEY,
    fetched_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS admit_progress_fetched ON public.admit_progress (fetched_at);

CREATE TABLE IF NOT EXISTS public.admitted_quarantine (
    source_id TEXT PRIMARY KEY,
    fetched_at TIMESTAMPTZ,
    guru TEXT NOT NULL,
    reason TEXT NOT NULL,
    kb_path TEXT NOT NULL DEFAULT '',
    iceberg_id TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    quarantined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS admitted_quarantine_open
    ON public.admitted_quarantine (resolved_at)
    WHERE resolved_at IS NULL;

CREATE TABLE IF NOT EXISTS public.skos_pref_label (
    notation TEXT PRIMARY KEY,
    pref_label TEXT NOT NULL,
    clt_uri TEXT NOT NULL,
    labeler_model TEXT NOT NULL DEFAULT '',
    labeler_version TEXT NOT NULL DEFAULT '',
    exemplar_hash TEXT NOT NULL,
    item_ids BIGINT[] NOT NULL DEFAULT '{}',
    stale BOOLEAN NOT NULL DEFAULT FALSE,
    run_id TEXT NOT NULL DEFAULT '',
    labeled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    stale_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS skos_pref_label_stale
    ON public.skos_pref_label (stale)
    WHERE stale;

CREATE TABLE IF NOT EXISTS public.clt_skos_clock (
    key TEXT PRIMARY KEY,
    watermark_fetched_at TIMESTAMPTZ,
    overlap_seconds INTEGER NOT NULL DEFAULT 3600,
    last_run_id TEXT NOT NULL DEFAULT '',
    last_run_at TIMESTAMPTZ,
    run_count INTEGER NOT NULL DEFAULT 0
);

INSERT INTO public.clt_skos_clock (key)
VALUES ('admit'), ('label')
ON CONFLICT (key) DO NOTHING;

CREATE OR REPLACE FUNCTION public.should_run_clt_skos(p_key TEXT)
RETURNS BOOLEAN AS $$
DECLARE
    v_last TIMESTAMPTZ;
    v_task TEXT;
BEGIN
    SELECT last_run_at INTO v_last
      FROM public.clt_skos_clock
     WHERE key = p_key;
    v_task := CASE WHEN p_key = 'label' THEN 'clt_skos_label' ELSE 'clt_skos_admit' END;
    IF EXISTS (
        SELECT 1 FROM scheduled_tasks
         WHERE task_type = v_task
           AND picked_up_at IS NULL
           AND completed_at IS NULL
    ) THEN
        RETURN FALSE;
    END IF;
    IF v_last IS NULL THEN
        RETURN TRUE;
    END IF;
    RETURN EXTRACT(EPOCH FROM (NOW() - v_last)) >= 600;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION public.mark_clt_skos_started(
    p_key TEXT,
    p_run_id TEXT DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    UPDATE public.clt_skos_clock
       SET last_run_at = NOW(),
           run_count = run_count + 1,
           last_run_id = COALESCE(p_run_id, last_run_id)
     WHERE key = p_key;
END;
$$ LANGUAGE plpgsql;

SELECT cron.unschedule('clt-skos-admit')
WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'clt-skos-admit');
SELECT cron.unschedule('clt-skos-label')
WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'clt-skos-label');

SELECT cron.schedule(
    'clt-skos-admit',
    '*/15 * * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      SELECT 'clt_skos_admit', '{}'::jsonb, 'pg_cron', NOW()
      WHERE public.should_run_clt_skos('admit')$$
);

SELECT cron.schedule(
    'clt-skos-label',
    '*/15 * * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      SELECT 'clt_skos_label', '{}'::jsonb, 'pg_cron', NOW()
      WHERE public.should_run_clt_skos('label')$$
);

GRANT SELECT, INSERT, UPDATE, DELETE ON public.admit_progress TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.admitted_quarantine TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.skos_pref_label TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.clt_skos_clock TO gaius;
GRANT EXECUTE ON FUNCTION public.should_run_clt_skos(TEXT) TO gaius;
GRANT EXECUTE ON FUNCTION public.mark_clt_skos_started(TEXT, TEXT) TO gaius;

COMMENT ON TABLE public.clt_skos_clock IS
'Admit watermark + label clock. Two task_types; ledger is the join.';
COMMENT ON TABLE public.admitted_quarantine IS
'Poison inbound docs (#WS.00000019). Extract backfill reopens via cursor overlap.';
COMMENT ON TABLE public.skos_pref_label IS
'Minted feature labels with labeler + exemplar hash. Stale requeues ACP.';

-- migrate:down

SELECT cron.unschedule('clt-skos-admit')
WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'clt-skos-admit');
SELECT cron.unschedule('clt-skos-label')
WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'clt-skos-label');

DROP FUNCTION IF EXISTS public.mark_clt_skos_started(TEXT, TEXT);
DROP FUNCTION IF EXISTS public.should_run_clt_skos(TEXT);
DROP TABLE IF EXISTS public.clt_skos_clock;
DROP TABLE IF EXISTS public.skos_pref_label;
DROP TABLE IF EXISTS public.admitted_quarantine;
DROP TABLE IF EXISTS public.admit_progress;
