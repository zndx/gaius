# Prospects split: in-engine check vs Metaflow update

The comments are not a plot; they freeze a 2026-09-07 doctrine
("Airflow orders; Metaflow executes only the heavy enabled flow") that
`tests/engine/test_workload_catalog.py` still asserts:
`prospects_check.runner == RUNNER_TASK`.

End to end today:

1. Airflow `gaius_prospects_check` 07:00 declares an Activity (no GPU claims).
2. Coordination watcher either skip-releases (`gate_false`) or inserts
   `scheduled_tasks` `prospects_check`.
3. Engine start **catch-up** can insert the same row (`engine-catchup`)
   and run it immediately — this is what actually ran 12–15 Sep.
4. `handle_prospects_check` is **in-engine**: `ProspectsService.run_check`
   (FMP + HX pending), then `mark_prospects_check_started()`, then
   maybe `_enqueue_prospects_update(symbols)`.
5. `handle_prospects_update` spawns **ProspectsUpdateFlow** (Metaflow),
   which Completes thinking/instruct on the engine that hosts Qwen.

A second, unused `ProspectsCheckFlow` exists (`flows/prospects/flow.py`)
and still says "Triggered by pg_cron"; its `compare_filings` is a 30-day
cutoff TODO, not the HX check the engine runs.

The split is why: catch-up stamps last_run while Airflow skip-succeeds;
check can enqueue update while the heavy endpoint is absent; two clocks
and two check implementations. Completing the re-arch is one Airflow-
ordered Metaflow (check+update or check then Asset-triggered update)
that Completes a healthy engine — not a cheaper in-engine half.
