-- migrate:up
-- Progress-based watchdog (2026-09-04 18:20, doctrine: progress over timeouts).
--
-- The task-watchdog reset fmp_roll 29346 at 17:25 as "stuck running" after
-- 48 min: its compaction was generating on thinking the whole time (Metaflow
-- heartbeat lines every 5 min, 10–30 tok/s), and the flow is still running
-- an hour later. A wall-clock threshold on a live engine is the naive timeout
-- the doctrine forbids; the watchdog exists for ORPHANS — rows whose processor
-- is gone. Progress is the signal: the processor stamps heartbeat_at from the
-- child's output lines (throttled), and the watchdog measures SILENCE since the
-- last heartbeat, falling back to picked_up_at for handlers that never stamp
-- (in-engine coroutines; unchanged behaviour for them).
ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;
COMMENT ON COLUMN scheduled_tasks.heartbeat_at IS
  'Last progress signal from the handler (spawned-flow output line, throttled ~60 s). '
  'The task-watchdog resets on silence since COALESCE(heartbeat_at, picked_up_at), never on age alone.';

CREATE INDEX IF NOT EXISTS scheduled_tasks_inflight_hb_idx
  ON scheduled_tasks (picked_up_at, heartbeat_at) WHERE completed_at IS NULL;

-- The watchdog's victim rule: silence, not age. Same class split as before
-- (4 h for the long classes, 45 min otherwise) applied to the last heartbeat.
UPDATE cron.job
   SET command = replace(
         replace(command,
                 'THEN picked_up_at < NOW() - interval ''4 hours''',
                 'THEN COALESCE(heartbeat_at, picked_up_at) < NOW() - interval ''4 hours'''),
                 'ELSE picked_up_at < NOW() - interval ''45 minutes''',
                 'ELSE COALESCE(heartbeat_at, picked_up_at) < NOW() - interval ''45 minutes''')
 WHERE jobname = 'task-watchdog'
   AND command NOT LIKE '%COALESCE(heartbeat_at, picked_up_at)%';

-- migrate:down
UPDATE cron.job
   SET command = replace(command, 'COALESCE(heartbeat_at, picked_up_at)', 'picked_up_at')
 WHERE jobname = 'task-watchdog';
DROP INDEX IF EXISTS scheduled_tasks_inflight_hb_idx;
ALTER TABLE scheduled_tasks DROP COLUMN IF EXISTS heartbeat_at;
