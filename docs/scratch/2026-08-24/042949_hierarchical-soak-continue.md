# Hierarchical soak continue (04:29Z)

Live tinybox nvidia-smi jsonl `/tmp/gpu-metrics-hour.jsonl` (1 Hz). Sampler
`scripts/gpu_metrics_kudu_ingest.py` still C++ (`kudu_via=cpp`, `kudu_ok=true`).
Do not kill it.

## Proven this slice (no fake rows)

- jsonl ~3.2 h from 01:09Z; hours **496537** (12156), **496538** (21930),
  **496539** (21594 jsonl / 21595 Kudu), **496540** hot.
- Impala isolated FE rebuild already `IMPALA_BUILD_OK` (01:54Z,
  Iceberg `1.11.0-signals-hdf5`). HS2 `:21050` is up again after the
  04:24 Kudu/Postgres recycle (`just up` / devenv-85cf547).
- C++ table `impala::signals_dataproducts.gpu_metrics_tier0` exists.
  Full jsonl upsert backfill: **64068** rows. FDW `:5455` `gpu_metrics`
  `kudu_scan` lag ~0.5 s on hour 496540 (min/max power real, not stub).
- Closed-hour analog already on RustFS for 496537–496539 (both analog
  prefix and Iceberg data prefix). HS2
  `SELECT epoch_hour, count(*) FROM gpu_metrics_tier1 GROUP BY 1` =
  **12156 + 21930 + 21594**. `SELECT * … LIMIT 3` returns analog rows
  (`power_w=8.0`, `mem=21332`). Snapshot `numRows=55680`.
- `config/platform/gpu-metrics-fdw.sql` re-applied (tier0 kudu_scan,
  tier1 `impala_sql`, logical `gpu_metrics` still kudu_scan of hot
  tablets).
- Gaius Discover Strip=`1h warehouse`: CLI `/thoughts waterfall 3600`
  and UI `:9890/api/gaius/v1/cognition/waterfall?window_s=3600` →
  `driver=warehouse`, `n_times=3600`, `n_channels=20`, matrix 72000.

## Still fail-fast (not stubbed)

- Impala **Java** Kudu client TGT (`KUDU-2121`). catalogd has FQDN
  masters, JAAS keytab, `useSubjectCredsOnly=false`,
  `kudu.krb5ccname=/tmp/krb5cc_impala` with a live impala TGT **and**
  `kudu/tinybox…` ticket. HS2 `SELECT` / `CREATE VIEW gpu_metrics AS
  tier0 UNION ALL tier1` still cannot load `gpu_metrics_tier0`
  (`missing or expired TGT`). Do not DROP Kudu hour ranges until that
  scan path works — 1h strip still reads tablets via FDW `kudu_scan`.
- FDW `gpu_metrics_tier1` `impala_sql` fails:
  `HS2 Kerberos/SASL not yet implemented` (SPEC: Iceberg via HS2, not
  kudu_scan). Cold HDF5 is HS2-only until FDW GSSAPI exists.
- 04:23–04:24: Kudu master + Postgres `:5455` died (devenv recycle).
  jsonl kept sampling; C++ ingest stalled on 243-attempt connect.
  Restored; backfilled. `kudu_ok` in status can still read true while
  `kudu_err` is set (`kudu_via=="cpp"`). Engine FDW INSERT + sidecar
  C++ both write hour 496540 (distinct `ts_ns`, real nvidia-smi).

## Query path under test

Gaius Discover strip (`window_s=3600`) → Engine gRPC → devenv Postgres
`:5455` `impala_fdw` `gpu_metrics` → Kudu `gpu_metrics_tier0` (all four
hours still in tablets). Iceberg HDF5 is independently correct on HS2
`gpu_metrics_tier1`. Transparent UNION remains blocked on Java SASL.
