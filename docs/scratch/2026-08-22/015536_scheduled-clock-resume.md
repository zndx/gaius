# Scheduled clocks resume (keep freeze-at-last-tape)

Discover salience stays anchored on last `feature_tape` write. That is the
desired UX while inflow is dead. The stall after **2026-08-20 20:20Z** was
the engine dispatcher, not the chart.

## Cause

`ScheduledTaskProcessor` LISTENs on `scheduled_task_ready` and:

1. Completed unknown types as `#STP.00000003.NOHANDLER` on NOTIFY
   (including jittered `feed_check` at INSERT, before `scheduled_for`).
2. `_pickup_due` claimed **every** due row, then errored types it does
   not own. CognitionService (poll 30s) lost the race.

`feed_check` never called `schedule_due_fetches()`. Last `fetch_jobs`
success matches last tape. `feature_probe` kept ticking with
`probed=0` because unprobed inflow was empty.

## Fix

- STP binds CognitionService types (`feed_check`, triage, `cognition_cycle`,
  `engine_audit`, …). `article_curate` stays the Metaflow handler.
- Unknown types stay pending (not completed).
- `_pickup_due` filters to owned types and `completed_at IS NULL`.
- Cognition poll still runs CPU clocks when GPUs are busy.
- `pick_up_task` skips completed rows (dbmate
  `20260822000001_pick_up_task_skip_completed`).
- Engine-only recycle: `GAIUS_CLEAN_START=false` skips vLLM kill/preload.

Do not extend the 36h window to wall `now`.
