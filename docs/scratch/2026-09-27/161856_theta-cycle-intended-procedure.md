# Theta cycle — intended procedure

Mapped 2026-09-27 so a blank `completed` row can be judged against the procedure, not against the writer that accepted it. Not a design change.

## When a cycle runs

One natural run: Monday 06:00 UTC, `gaius_theta_cycle`, `catchup=false`, `max_active_runs=1`. The logical date's previous ISO week is the slice. The week still in progress waits for that Monday.

A missed closed week is a backfill: earliest UTC day of that week, then forward, one LIGHT day at a time, into the same ledger row. Not a year dump. Not one out-of-band occupancy of the whole week. `--latest-first` is the old order. `--weekly` is the coarse one-Monday path.

The next Monday after a finished week is the next point. It is not another backfill of the week already on the ledger.

## What one run is

Airflow's run is a Coordination Activity: declare, hold, close. Gaius enqueues `scheduled_tasks` `theta_cycle` (`source=airflow`) and runs `ThetaCycleFlow` on one LIGHT GPU. ColBERT-Zero encodes. BERTSubs is CPU/JVM. The engine does not run the heavy stages in-process.

Stages, in order:

1. **Start.** A `window_date` binds that UTC day and the ISO week that contains it. No window means the whole previous week.
2. **Prepare.** One ledger row for that week. Load that day's thoughts, or the week's if this is the Monday run. No thoughts on a week-level run is `#THETA.00000009.NOTHOUGHTS`, not success.
3. **Extract.** CLT activations for the slice. Resident `gaius-clt` if it is up; otherwise this same LIGHT token.
4. **Encode.** ColBERT-Zero centroid, merged into the week (running mean, not a day product). MaxSim grounds the week's admitted items onto the TBox. Empty encode is `#THETA.00000010.NOENCODE`. Thoughts feed encode and the NVAR signal only. Classes do not come from thought text.
5. **Infer.** Novel, non-entailed, CLT-grounded OWL pairs. BERTSubs Intra scores them against the certified TBox. Knowledge-gradient selects. Selected links augment KB documents. No novel pairs is `#THETA.00000011.NOPAIRS`. Ontology, JVM, and consolidation exceptions are their own guru codes. They are not success.
6. **Complete.** Write the row. A day refines it (`scheduled` until Monday–Sunday are in `metadata.windows`). A week-level run finishes it.
7. **End.** If the result is not success, the flow raises. Airflow must fail. A green DAG with an empty result is a lie.

## What "completed" is for

The ledger is coverage for Nautilus and sitrep. It is not `gaius.theta.consolidation`, and that product is not published.

Two predicates are in use and must not be collapsed:

- **Coverage.** Monday–Sunday of the slice were incorporated. That is what `week_is_complete` checks.
- **Result.** The stages that ran left their outcome on the row. Encode leaves `n_encoded` and groundings in metadata. Infer leaves `candidates_evaluated`, `candidates_selected`, and `documents_augmented`.

A completed row with an empty error is what the opening treats as "this week is not a backfill." That word is only honest if the result predicate held. Coverage without a result — both counters zero, no error — is a swallowed failure (`#THETA.00000013.CONSFAIL`), not completion.

The cortical objective is still the entailed stack OWL ⊨ SKOS ⊨ SHACL, effective on the accumulated corpus. Class–class pairs and `documents_augmented` are the old alignment habit, not that objective. They are still the only result the flow knows how to record. Until a replacement measure exists, a run that records neither an error nor those counts has not finished.

## What the opening may say

After Monday 06:00 plus the five-hour admission window, the previous ISO week either has a completed row or it does not. Only the second case is a backfill, and only that case belongs in the session opening. A missing `scheduled_tasks` tick for a week that is actually complete is not that signal. A week still inside its Monday window is the scheduled run, not a backfill.

## Where 2026-W38 sits

Row 23 is `completed` with an empty error and all seven days in `windows`. Metadata has a centroid, `n_encoded=228`, and 114 item groundings. The result columns are all zero. Encode ran. Infer's counts were never the thing that completed the row. That is coverage without a result. It is not a finished cycle under the procedure above. Week 39 is not due until Monday 28 September 2026 at 06:00 UTC.
