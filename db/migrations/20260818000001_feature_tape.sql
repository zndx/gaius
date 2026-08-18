-- migrate:up
-- CLT FeatureTape: temporal activations for Discover salience.

CREATE TABLE IF NOT EXISTS public.feature_tape (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL,
    stream TEXT NOT NULL,
    source_id TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    layer INTEGER NOT NULL,
    feature_idx INTEGER NOT NULL,
    activation DOUBLE PRECISION NOT NULL,
    worker TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS feature_tape_event_feat
    ON public.feature_tape (event_id, layer, feature_idx);
CREATE INDEX IF NOT EXISTS feature_tape_ts ON public.feature_tape (ts DESC);
CREATE INDEX IF NOT EXISTS feature_tape_feat ON public.feature_tape (layer, feature_idx);

GRANT SELECT, INSERT, UPDATE ON public.feature_tape TO gaius;
GRANT USAGE, SELECT ON SEQUENCE public.feature_tape_id_seq TO gaius;

SELECT cron.unschedule('feature-probe')
WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'feature-probe');

SELECT cron.schedule(
    'feature-probe',
    '*/5 * * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      SELECT 'feature_probe', '{"gpu_index":4}'::jsonb, 'pg_cron', NOW()
      WHERE NOT EXISTS (
          SELECT 1 FROM scheduled_tasks
          WHERE task_type = 'feature_probe'
            AND picked_up_at IS NULL
            AND completed_at IS NULL
      )$$
);
