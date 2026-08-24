# Hierarchical soak: analog 496555 (20:30Z)

Jsonl sampler `pid 36619` (~6.6 h, sample-only) still up. Hour **496555**
closed at 20:00Z. Live hour **496556** is Kudu-only (engine FDW INSERT).
Impala FE already `IMPALA_BUILD_OK`. Sidecar Kudu writer stays retired.

Engine `pid 3518301` (started 20:12:42 this life; ingest `ticks=930`
at 20:29:39). Hour 496555 HDF5 sat on analog + Iceberg data prefixes
from 20:06 without a Polarisfork snapshot (metadata still 00018 /
496554). This tick registered the analog, verified Iceberg, then DROP.

## Proven (no fake rows)

- Closed-hour analog from **FDW Kudu** (engine writer): **12486** rows →
  `gpu_metrics_hour_496555.h5` (127663 B) on analog + Iceberg data
  prefixes. Jsonl for that hour is **21546** rows (3591 ticks) — short
  **1510** warehouse ticks (19:00–19:10 engine-down, 19:16 / 19:28 /
  19:44 recycles, 19:48–19:55 stall). Analog used warehouse rows, not
  padded jsonl. Polarisfork `FileFormat.HDF5`. HS2/FDW `gpu_metrics_tier1`
  GROUP BY includes **12486** for 496555. Sample `power_w=7/11/12`
  `mem=21117` on GPUs 0–2 (int16 analog of real DCGM after `gpu_cleanup`).
- **DROP RANGE VALUE = 496555** verified (catalog reload fault; SHOW
  RANGE left `496556` … `496578` after ADD 575–578). UNION no longer
  double-counts (was 24972 = 12486×2 before DROP):

  | hour   | store   | count |
  |--------|---------|-------|
  | 496553 | Iceberg | 16770 |
  | 496554 | Iceberg | 13974 |
  | 496555 | Iceberg | 12486 |
  | 496556 | Kudu    | live  |

- Live lag ~1 s after catalog mutations. Sample `power_w=120–137`
  `util=100` `mem=21331` on GPUs 0–3, gpu-5 `mem=3` (real DCGM).
  Strip=1h UI+CLI `driver=warehouse`, `n_times=3600`, matrix **72000**,
  epoch 20:29:08Z. gpu-0..5 nonzero 2354/3600 (honest recycle/stall
  gaps).

Live `gpu_metrics` VIEW is still `tier0 UNION ALL tier1` **without**
`NOT IN`. Honest after DROP.

## Next

Analog **496556** after 21:00Z close. Retry `ALTER VIEW … NOT IN` when
HMS accepts `alter_table`. Do not analog the open hour. Keep sampler
36619 and engine ingest.
