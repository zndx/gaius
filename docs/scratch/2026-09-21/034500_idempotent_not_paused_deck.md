# Deck: idempotent cadence, not pause; some Theta backfill

2026-09-21. Pause is a last resort. A class that can prove “nothing
changed” belongs **enabled** on Airflow and **retired** from pg_cron.
Hiding work in pg_cron while the DAG is paused is the opposite of a
hub-visible cadence.

`atelier_sdg_classify` stays paused until its no-op path is real.
Do not dump a year of Theta. Do not unpause `atelier_sdg_classify` today.

## 1. Theta — on-time tick, then a *small* backfill

| Slice | How | When |
|-------|-----|------|
| **2026-W38** (14–20 Sep) | Monday 06:00 UTC on-time (`gaius_theta_cycle`, already unpaused) | **today** |
| **2026-W37** (7–13 Sep) | 7 daily LIGHT increments (`just theta-backfill --from-date 2026-09-07 --to-date 2026-09-13`) | **after** W38 reaches terminal |
| W36 and older | still persistent failures | not this week |

`max_active_runs=1`: queuing W37 **now** would steal LIGHT from 06:00.
Dry-run of W37 is seven `theta_day_YYYY-MM-DD` runs, latest day first.

W38 last failed `#THETA.00000005.ONTOLOGY_INVALID`. W37 last failed
`#THETA.00000001.DEEPONTO` / `en_core_web_sm`. Remediate what the 06:00
run actually hits, then backfill W37.

## 2. Atelier classify — verify no reclassification, accept new tables

Today `ClassificationFlow.probe` is SKOS/vocab + encoder identity. It
does **not** look at Ægir’s relational projection. The gateway already
computes `new_table_count = source_table_count - classified_table_count`
(`gateway.py` artifact panel). Atlas already exposes `rdbms_table`
under `footprint.*@aegir` (`atelier.governance.atlas_source.read_tables`).

**On deck for classify (then `enabled=True`):**

1. **Scope step** (cheap, no LIGHT): fingerprint Ægir Atlas table set
   (qualified names + column names, not values).
2. Compare to last classify dataset for that source.
3. **Δtables = 0** and vocab signature unchanged → **success no-op**
   (verified: no reclassification needed). Do not claim LIGHT, do not
   encode, do not NHSVM.
4. **Δtables > 0** → classify **only the new tables**; merge into the
   existing artifact set. Vocab/encoder change still forces precondition
   (existing probe).
5. Prove one K8s Metaflow run of the no-op path (YK app-id), then flip
   `WorkloadEntry.enabled=True` (`atelier/engine/workload_catalog.py`)
   so `atelier_sdg_classify` unpauses on the daily `0 8 * * *`.

Pause was “until a K8s Metaflow run is proven” *and* catch-up risk on
unpause. The no-op path plus `start_date = enabled_since_ns` (Signals
coord_workloads) removes both excuses.

## 3. Gaius — Airflow pause ≠ not running

pg_cron is **still active** for most classes whose DAGs are paused:
`clt-skos-admit/label`, `board-reindex`, `engine-audit-hourly`,
`feature-probe`, `content-*`, `heuristic-triage`, `llm-triage`,
`objective-verify`, `weekly-summary` (the THS name), `tier-settle-signal`,
…. Hub-visible Airflow cadence already owns article_curate, ambient,
FMP, cognition, publish slots, prospects, agenda brief, weekly_signals,
Theta.

**On deck to invert pause → idempotent Airflow (one class at a time):**

| Next | Why it can be enabled | Gate still needed |
|------|------------------------|-------------------|
| `clt_skos_admit` + `label` | already `should_run_clt_skos`; Theta’s pairing substrate | clock is “≥600s”, not “nothing to admit” — tighten to empty-buffer / no new activations before enable |
| `objective_verify` | 6 h, judged, not LIGHT | confirm it no-ops when no new objectives |
| `engine_audit` | hourly, no GPU | confirm cheap skip |
| `board_reindex` | already `should_run_board_reindex` | **not** every-minute Airflow until the gate is cheap |
| `gaius_weekly_summary` | **do not enable** | THS name; live digest is `gaius_weekly_signals_summary` |

Pattern: `gate_sql` answers “is there work?”, Airflow `enabled=True`,
`pg_cron_active=False` after one proven run. Same as article_curate.

## 4. Not on deck

- Year of Theta daily increments.
- Unpausing `atelier_sdg_classify` before the Atlas Δtables no-op.
- Enabling `signals_ci` / `signals_eventing_ci` as a substitute for
  elevated `*-ci` lanes.
- Dual-running pg_cron and Airflow for the same class.
