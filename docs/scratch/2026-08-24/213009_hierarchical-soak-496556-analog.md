# Hierarchical soak: analog 496556 (21:30Z)

Jsonl sampler `pid 36619` (~7.6 h, sample-only) still up. Hour **496556**
closed at 21:00Z. Analog HDF5 + Polarisfork append + **DROP RANGE 496556**
landed at **21:06** (previous tick). This tick verified Iceberg, UNION,
and Strip=1h. Live hour **496557** is Kudu-only (engine FDW INSERT).
Impala FE already `IMPALA_BUILD_OK`. Sidecar Kudu writer stays retired.

Engine recycled at **21:16:19** (`pid 4115269`; `gpu_cleanup` on
`devenv processes restart`). Ingest recovered: `ticks=720 inserted=4320`
by 21:29:28 (first this life ~21:16:30). Lag ~0.4–2 s.

## Proven (no fake rows)

- Closed-hour analog from **FDW Kudu** (engine writer): **16164** rows →
  `gpu_metrics_hour_496556.h5` (161991 B) on analog + Iceberg data
  prefixes. Polarisfork snapshot `21:06:28Z`
  (`snap-8647026470053668716…`). Jsonl for that hour is **21564** rows
  (3594 ticks) — short **900** warehouse ticks (20:35 / 20:45 recycles
  plus 20:00–20:08 hour-start gap; analog first `ts_ns` is ~20:08:11Z).
  Analog used warehouse rows, not padded jsonl. Polarisfork
  `FileFormat.HDF5`. HS2/FDW `gpu_metrics_tier1` GROUP BY includes
  **16164** for 496556 (2694 ticks × 6 GPUs). Sample `power_w=6/11/12`
  `mem=21117` on GPUs 0–2 (int16 analog of real DCGM after
  `gpu_cleanup`); hour max `power_w=126/129/141/143` `util=100`
  `mem=21443` on GPUs 0–3.
- **DROP RANGE VALUE = 496556** verified. SHOW RANGE left `496557` …
  `496582`. UNION no longer double-counts (t1 = u = 16164; t0 has no
  496556):

  | hour   | store   | count |
  |--------|---------|-------|
  | 496553 | Iceberg | 16770 |
  | 496554 | Iceberg | 13974 |
  | 496555 | Iceberg | 12486 |
  | 496556 | Iceberg | 16164 |
  | 496557 | Kudu    | live  |

- Live lag ~0.4–2 s. Sample `power_w=111–132` `util=100` `mem=21333`
  on GPUs 0–3, gpu-5 `mem=3` (real DCGM). Strip=1h UI+CLI
  `driver=warehouse`, `n_times=3600`, matrix **72000**, epoch
  21:27:40Z. gpu-0..5 nonzero 3202/3600 (honest recycle/hour-start
  gaps). `/discover 1h` buckets carry warehouse `watts`/`util` across
  Iceberg 496556 ∪ Kudu 496557.

Live `gpu_metrics` VIEW is still `tier0 UNION ALL tier1` **without**
`NOT IN`. Honest after DROP. Did not `ALTER VIEW` this tick (catalog
mutation; HMS previously rejected `alter_table`).

## Next

Analog **496557** after 22:00Z close, then DROP RANGE 496557. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour. Keep sampler 36619 and engine ingest.
