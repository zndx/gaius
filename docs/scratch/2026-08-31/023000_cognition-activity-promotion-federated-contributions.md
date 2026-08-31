# Cognition: 2D Activity promotion + FEDERATED Contributions

User course-corrections, executed in one tranche:

## Activity consolidation

- The true-width SVG bar chart ("Activity") is GONE — component, brush,
  cogchart helpers (niceScale/unitTicks/monthLabel), CSS.
- The 2D contributions calendar is now **the** Activity component,
  directly under Federation, meta readout (`interval · n buckets · as-of`)
  in its head.
- **Regression avoided** (design review catch): the calendar used to hide
  for hour/6h grains — 24h/7d would have lost all activity viz AND range
  authoring. It now renders the bucket strip at those grains.
- **Range authoring re-anchored**: the SVG brush was the only way to
  author from/to. Calendar cells now carry `data-s`/`data-e` (UTC day
  bounds; strip cells carry bucket bounds) and a pointer-capture drag on
  `#cog-year` authors the range (click = single cell); out-of-window
  filler cells can't author. Chip-clear unchanged.

## Contributions (replaces Hour of week) — federated from day one

Doctrine: contributions are retrieved from **federated systems of record
over the signals protocol** — Atlas+OpenLineage from core Signals (its
'Sources' visible in Marquez, currently 0, Signals-side fix incoming),
K8s Signals Metaflow + Airflow. That retrieval is **PENDING** (Impala-THS
doctrine posture); the groundwork is laid NOW and the UI bootstraps from
local Gaius activity so nothing is a rewrite later:

- **Protocol** (signals-protocol, additive v1): `SERVER_QUERY_KIND_
  CONTRIBUTIONS = 11` + `ContributionsHint{project, interval, range,
  buckets, items[{group, id, system, total, series}]}`. Peers answer as
  their systems of record become able; unset is honest.
- **Local bootstrap systems of record** (same DB/pool as the surface):
  sources ← `activity_events` (`kb_create`, `domain` = feed-source name,
  system `gaius.activity`); workflows ← `lineage_events`
  (`gaius.flows`/`START`, `job_name`, system `gaius.openlineage` — the
  local store already speaks OL vocabulary, aligning with the future
  Atlas+OL feed). `cognition_thoughts` was proven dimensionless for this
  (all candidate columns empty in prod).
- **Surface contract**: `CognitionSurfaceResponse.contributions = 27` —
  `CognitionContribution{group, id, system, total, series[], peer}`,
  series positionally aligned with the response buckets (same grain +
  range params; `fold_named_series` in cognition_buckets, unit-tested).
  `hours` retired per the days precedent (field kept, `[]`).
- **Federated path real end-to-end**: gaius answers kind=11 (SCHEDULES-
  pattern async enrichment), `s2s.collect_peer_contributions` (absent-
  peer-honest BFS), `GaiusService/FederationContributions`, gaius-ui
  `/api/gaius/v1/federation/contributions`.
- **UI**: SOURCES / WORKFLOWS sections — AgentsView ProjectBreakdown bar
  rows (ratio-to-max, min-width 2px) + per-bucket heat strips (≤64
  buckets) + top-6 + "Other (N)" fold; row titles carry system + peer
  provenance; meta line reports `federated: N answering · more PENDING`.
  Contributions ignore the stream filter (they aren't thoughts — honest)
  and honor the brushed range.

**Signals-session flags**: signals-protocol submodule now carries
PRODUCTS + COGNITION + CONTRIBUTIONS ahead of their pin; Marquez
'Sources' fix + Atlas+OL/Metaflow/Airflow kind=11 answers are the
Signals-side work that makes the federation fill in.
