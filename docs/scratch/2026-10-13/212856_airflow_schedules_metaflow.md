# Airflow schedules Metaflow; Signals asserts the YK configuration

Airflow orders a Metaflow class. The catalogue `claims` are that run's
YuniKorn configuration. Signals asserts them while the activity is in
force and retracts them when the engine releases the activity. The Gaius
child records `GAIUS_YK_ACTIVITY_ID` and does not call `apply_and_admit`.

`prospects_update` is enabled as `gaius_prospects_update`, asset-scheduled
on `task.prospects_check` (`after_mode=all`, so `wire_cron` is empty).
The check records `symbols` on its result and does not insert an update
row. The update reads that list; a hand-enqueued payload list wins. An
empty list completes as `nothing to update`. A skip would fail the
Airflow lease (`#CO.0000000F.NOEFFECT`).

The activity claim is the run's own workload: extract, 1 GPU, for the
whole ProspectsUpdateFlow. The analyze phase still borrows the shared
embedding seat on light. That floor is emitted when the step starts, not
held for acquire and surface. pg_cron children, and the interactive
prospects path, still admit their own sentinel.

The live engine still publishes the previous catalogue on its 30-minute
`SyncWorkloads`. This tree was not synced from a one-off, and the engine
was not restarted: both light seats are held by the d3-flash processes.
The new DAG appears after the next controlled restart. Until the first
successful Airflow completion, `prospects_update` is a missed tick
(`#CO.0000000D.MISSTICK`).

Checked with `.devenv/state/venv/bin/python -m pytest` on the catalogue,
dispatch, flow-token, agenda, workload sync/view, prospects publish,
sentinel, and coordination tests (93 + 39 passed).
