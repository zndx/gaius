# Hierarchical soak: HMS-free UNION view (04:59Z)

Sampler still C++ (`pid 2989721`, `kudu_ok`). Impala FE rebuilt this
slice (`impala-frontend` package SUCCESS).

## Proven (no fake rows)

- `CREATE VIEW signals_dataproducts.gpu_metrics` persisted in
  `catalog_tables` as `VIEW` (jsonb SQL). HS2 `SELECT` the UNION.
- Iceberg HDF5 hours 496537–496539 still scan; Kudu has all four hours.
  UNION double-counts closed hours until DROP RANGE.
- FDW `:5455` `gpu_metrics` `kudu_scan` lag ~0.8 s (min/max power real).
- Strip=1h CLI+UI `driver=warehouse`, `n_times=3600`, matrix 72000.
- jsonl C++ upsert 75192 this pass.

## Still fail-fast

- Do **not** DROP Kudu closed hours: Gaius 1h strip is FDW `kudu_scan`,
  not the Impala view (`impala_sql` still lacks HS2 GSSAPI).
- FDW `gpu_metrics_tier1` remains HS2-blocked.
