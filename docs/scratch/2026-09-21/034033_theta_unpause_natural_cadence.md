# Theta unpaused — natural cadence, not a catch-up dump

2026-09-21T03:40Z. `gaius_theta_cycle` `is_paused=false` (PATCH confirmed).
`catchup` stays false. `max_active_runs=1`. Next interval is **today**
Monday `2026-09-21T06:00:00Z`, consolidating **previous ISO week
2026-W38** (14–20 Sep). Zero Airflow dagRuns yet; this is the first
on-time tick on this Airflow.

`atelier_sdg_classify` remains paused.

## Not a stampede

Historical `theta_consolidation_runs` are failed/superseded back to
W10. Unique pending is only `scheduled|running`, so today's tick can
insert a new W38 row beside the 2026-09-15 **failed** row. We do **not**
`just theta-backfill` the year. Missed weeks stay persistent failures
until a later daily-increment backfill, as friction, one week at a time.

## Likely first friction (W38 2026-09-15)

`#THETA.00000005.ONTOLOGY_INVALID` at `deeponto_load` on
`build/dev/.cache/ontology/kb_current.owl` (mtime 2026-09-15 00:49,
same as the failed run). W37 also `#THETA.00000001.DEEPONTO` /
`en_core_web_sm`. Do not pre-empt the 06:00 run; remediate what it
actually hits.

LIGHT `root.internal.inference.light`: 1/2 GPU allocated, 1 GPU
headroom. Metaflow `:30180` pong. Airflow health green.

## Paused DAG backlog (not cleared)

Still paused, on purpose until a tick needs them:

`gaius_board_reindex`, `gaius_clt_skos_admit`, `gaius_clt_skos_label`,
`gaius_content_*`, `gaius_engine_audit`, `gaius_evolution_cycle`,
`gaius_feature_probe`, `gaius_feed_check`, `gaius_held_out_refresh`,
`gaius_heuristic_triage`, `gaius_llm_triage`, `gaius_metaagent_audit`,
`gaius_metabase_sync`, `gaius_model_merge`, `gaius_objective_verify`,
`gaius_research_processing`, `gaius_task_ideation`, `gaius_tda_computation`,
`gaius_tier_settle`, `gaius_weekly_summary` (THS name — live digest is
unpaused `gaius_weekly_signals_summary`), `signals_ci`, `signals_eventing_ci`.

Already in cadence: cognition, ambient, article curate, prospects, FMP
roll, four publish slots, agenda brief, weekly_signals_summary, Theta.

Watch: `~/.grok/long-running-background-tasks/watch_theta_monday.py`
(ACTION_REQUIRED on run start or missing 06:20Z slot; DONE/FAILED on
terminal).
