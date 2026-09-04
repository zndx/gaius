-- migrate:up
-- Two small truths for the Nautilus observe phase (2026-09-04).
--
-- 1. overwatch_events.source — during adoption the in-engine NautilusService and the
--    resident Nautilus (via EngineSupervision directives) both record trigger
--    firings here; the source column is what the daily comparison groups on.
ALTER TABLE overwatch_events ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'engine.nautilus';
COMMENT ON COLUMN overwatch_events.source IS
  'Who rendered the firing: engine.nautilus (in-engine daemon, retiring) or nautilus.rs '
  '(the resident supervisor over the Supervise stream).';
CREATE INDEX IF NOT EXISTS overwatch_events_source_idx ON overwatch_events (source, created_at DESC);

-- 2. A reset must clear the previous attempt's heartbeat. The claim UPDATE never
--    nulled heartbeat_at, and neither did the watchdog's reset, so a re-claimed row
--    inherited a stale heartbeat and could be a victim at the very next tick.
--    (The processor's claim SQL gets the same fix in code.)
UPDATE cron.job
   SET command = replace(command,
         'SET picked_up_at = NULL, error = ''reset by watchdog: stuck running''',
         'SET picked_up_at = NULL, heartbeat_at = NULL, error = ''reset by watchdog: stuck running''')
 WHERE jobname = 'task-watchdog'
   AND command NOT LIKE '%heartbeat_at = NULL%';

-- migrate:down
UPDATE cron.job
   SET command = replace(command, 'SET picked_up_at = NULL, heartbeat_at = NULL, error', 'SET picked_up_at = NULL, error')
 WHERE jobname = 'task-watchdog';
DROP INDEX IF EXISTS overwatch_events_source_idx;
ALTER TABLE overwatch_events DROP COLUMN IF EXISTS source;
