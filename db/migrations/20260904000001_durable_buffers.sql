-- migrate:up
-- Durable FIFO store behind the ambient / prospects / publishing buffers.
--
-- (2026-09-04) The three RAM FIFOs were the reason three model workloads ran
-- inside the engine on private timers (ambient synthesis cycle, FMP roll +
-- compaction, publishing axis roll). Those loops are now Metaflow flows on
-- pg_cron; they write and compact the buffers HERE and the engine's buffers
-- are read-through caches of the live rows (compacted_at IS NULL).
--
-- Same byte contract as AmbientBuffer: a compaction replaces the oldest
-- entries with one SUMMARY row; the replaced rows keep their content with
-- compacted_at / compacted_into set (history, not deletion).

CREATE TABLE IF NOT EXISTS buffer_entries (
    id             UUID PRIMARY KEY,
    buffer         TEXT NOT NULL CHECK (buffer IN ('ambient', 'prospects', 'publishing')),
    role           TEXT NOT NULL,
    content        TEXT NOT NULL,
    content_bytes  INTEGER NOT NULL,
    source_url     TEXT NOT NULL DEFAULT '',
    metadata       JSONB NOT NULL DEFAULT '{}'::jsonb,
    writer         TEXT NOT NULL DEFAULT '',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    compacted_at   TIMESTAMPTZ,
    compacted_into UUID
);

CREATE INDEX IF NOT EXISTS buffer_entries_live_idx
    ON buffer_entries (buffer, created_at)
    WHERE compacted_at IS NULL;
CREATE INDEX IF NOT EXISTS buffer_entries_created_idx
    ON buffer_entries (buffer, created_at);

COMMENT ON TABLE buffer_entries IS
    'Durable FIFO rows for the ambient / prospects / publishing buffers. Live = compacted_at IS NULL. Written by flows (fmp_roll, ambient_synthesis); the engine reads through.';
COMMENT ON COLUMN buffer_entries.writer IS
    'Who appended: flow:<FlowName> or engine';
COMMENT ON COLUMN buffer_entries.compacted_into IS
    'The SUMMARY row that replaced this entry in the FIFO';

GRANT SELECT, INSERT, UPDATE ON buffer_entries TO gaius;

-- Task-queue enqueues (the processor spawns the flows). No-pending guard:
-- a slow run is never doubled by the next tick.
SELECT cron.unschedule('fmp-roll')
 WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'fmp-roll');
SELECT cron.schedule(
    'fmp-roll',
    '7,37 * * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, priority, source)
      SELECT 'fmp_roll', '{}', 'normal', 'pg_cron'
       WHERE NOT EXISTS (
           SELECT 1 FROM scheduled_tasks
            WHERE task_type = 'fmp_roll' AND completed_at IS NULL)$$
);

SELECT cron.unschedule('ambient-synthesis')
 WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'ambient-synthesis');
SELECT cron.schedule(
    'ambient-synthesis',
    '*/20 * * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, priority, source)
      SELECT 'ambient_synthesis', '{}', 'normal', 'pg_cron'
       WHERE NOT EXISTS (
           SELECT 1 FROM scheduled_tasks
            WHERE task_type = 'ambient_synthesis' AND completed_at IS NULL)$$
);

-- migrate:down
SELECT cron.unschedule('ambient-synthesis')
 WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'ambient-synthesis');
SELECT cron.unschedule('fmp-roll')
 WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'fmp-roll');
DROP TABLE IF EXISTS buffer_entries;
