-- migrate:up
-- Discover 36h default landing. Page loads SELECT this view; Metaflow end
-- (and /discover refresh) run REFRESH MATERIALIZED VIEW CONCURRENTLY.

CREATE INDEX IF NOT EXISTS feature_tape_created_at
    ON public.feature_tape (created_at DESC);

CREATE MATERIALIZED VIEW public.discover_landing_36h AS
WITH last AS (
    SELECT max(created_at) AS t FROM public.feature_tape
),
win AS (
    SELECT
        CASE
            WHEN last.t IS NULL THEN now()
            WHEN now() - last.t <= interval '2 minutes' THEN now()
            ELSE last.t
        END AS end_ts,
        last.t AS last_salience_at
    FROM last
),
bounds AS (
    SELECT
        end_ts,
        end_ts - interval '36 hours' AS start_ts,
        last_salience_at
    FROM win
),
docs AS (
    SELECT
        c.id,
        c.title,
        left(COALESCE(c.summary, ''), 400) AS body,
        c.fetched_at,
        COALESCE(c.url, '') AS url,
        COALESCE(s.name, '') AS source
    FROM public.content_items c
    LEFT JOIN public.feed_sources s ON s.id = c.source_id
    CROSS JOIN bounds b
    WHERE NOT COALESCE(c.summary_excluded, false)
      AND EXISTS (
          SELECT 1 FROM public.feature_tape t
           WHERE t.event_id = 'inflow:' || c.id::text
             AND t.created_at >= b.start_ts
             AND t.created_at <= b.end_ts
      )
),
src AS (
    SELECT source, count(*)::int AS n FROM docs GROUP BY 1
),
feat AS (
    SELECT
        t.layer,
        t.feature_idx,
        count(DISTINCT d.id)::int AS n,
        avg(t.activation) AS a
    FROM docs d
    JOIN public.feature_tape t
      ON t.event_id = 'inflow:' || d.id::text
    GROUP BY 1, 2
),
buck AS (
    SELECT
        date_trunc('hour', t.created_at) AS m,
        count(DISTINCT t.event_id)::int AS n,
        COALESCE(sum(t.activation), 0) AS sal
    FROM public.feature_tape t
    CROSS JOIN bounds b
    WHERE t.created_at >= b.start_ts
      AND t.created_at <= b.end_ts
    GROUP BY 1
)
SELECT
    'doc'::text AS kind,
    d.id::text AS key,
    jsonb_build_object(
        'id', d.id,
        'title', COALESCE(d.title, ''),
        'body', COALESCE(d.body, ''),
        'fetched_at', to_char(d.fetched_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
        'url', d.url,
        'source', d.source
    ) AS payload
FROM docs d
UNION ALL
SELECT
    'src',
    COALESCE(s.source, ''),
    jsonb_build_object('n', s.n)
FROM src s
UNION ALL
SELECT
    'feat',
    f.layer::text || ':' || f.feature_idx::text,
    jsonb_build_object(
        'layer', f.layer,
        'feature_idx', f.feature_idx,
        'n', f.n,
        'a', f.a
    )
FROM feat f
UNION ALL
SELECT
    'bucket',
    to_char(bk.m AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    jsonb_build_object(
        't', to_char(bk.m AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
        'n', bk.n,
        'sal', bk.sal
    )
FROM buck bk
UNION ALL
SELECT
    'meta',
    'snapshot',
    jsonb_build_object(
        'start_ts', to_char(b.start_ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
        'end_ts', to_char(b.end_ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
        'last_salience_at', CASE
            WHEN b.last_salience_at IS NULL THEN ''
            ELSE to_char(b.last_salience_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
        END,
        'total', (SELECT count(*)::int FROM docs),
        'refreshed_at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
        'interval', 'hour',
        'window', '36h'
    )
FROM bounds b;

CREATE UNIQUE INDEX discover_landing_36h_kind_key
    ON public.discover_landing_36h (kind, key);

GRANT SELECT ON public.discover_landing_36h TO gaius;

COMMENT ON MATERIALIZED VIEW public.discover_landing_36h IS
    'Discover default 36h landing. Refresh CONCURRENTLY from engine RPC / Metaflow end.';

-- migrate:down

DROP MATERIALIZED VIEW IF EXISTS public.discover_landing_36h;
DROP INDEX IF EXISTS public.feature_tape_created_at;
