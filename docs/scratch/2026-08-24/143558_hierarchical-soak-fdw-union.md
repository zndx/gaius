# Hierarchical soak: FDW UNION is impala_sql (14:35Z)

Jsonl sampler `pid 36619` (sample-only, `kudu_via=engine_fdw`) and engine
warehouse ingest (`pid 267627`, started 14:18Z) still up. Hour **496550**
is hot. Closed **496549** is Iceberg HDF5.

## Proven (no fake rows)

- `SHOW RANGE PARTITIONS` is `VALUE = 496550` … `496565`. **496549 is
  gone** (DROP RANGE already applied). UNION no longer double-counts:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496537 | Iceberg | 12156 |
  | 496538 | Iceberg | 21930 |
  | 496539 | Iceberg | 21594 |
  | 496540 | Iceberg | 19968 |
  | 496541 | Iceberg | 21594 |
  | 496542 | Iceberg | 21600 |
  | 496543 | Iceberg | 21600 |
  | 496544 | Iceberg | 21594 |
  | 496545 | Iceberg | 21600 |
  | 496546 | Iceberg | 21594 |
  | 496547 | Iceberg | 21600 |
  | 496548 | Iceberg | 21600 |
  | 496549 | Iceberg | 19752 |
  | 496550 | Kudu    | live  |

- Iceberg 496549 sample `power_w=104` `util=100` `mem=21332` (real
  nvidia-smi). Live Kudu sample `power_w≈46–63` `mem=21117` (DCGM while
  thinking loads GPUs 0–3).
- Postgres `gpu_metrics` as a VIEW of `kudu_scan` ∪ Iceberg projected
  only `epoch_hour` on the Iceberg scan (NOT IN filter). Measure columns
  came back NULL → `tick_from_gpu_rows` `int(None)` TypeError. Recreated
  as `FOREIGN TABLE` `access=impala_sql` of the HS2 UNION view. Iceberg
  `ts_ns` is populated again.
- Strip=1h CLI `driver=warehouse`, `n_times=3600`, matrix **72000**.
  gpu-0..5 nonzero ≈3104/3600 (honest gaps, not padding). Discover 1h
  buckets have warehouse watts. Hot lag ~0.6 s.
- Engine ingest recovered from a 14:21:42 DCGM `:9400` blip (~26 s) and
  a 14:17:34–14:18:32 engine restart (~58 s). Jsonl sampler stayed up.

## Next

Analog **496550** after 15:00Z close. Ranges 496550–565 already present
(ADD 566–569 not applied). Do not analog the open hour.
