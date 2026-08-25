# Warehouse: engine writes signal_tier0; strip reads Kudu, Kumo reads the hierarchy

Companion to signals `docs/scratch/2026-08-25/*_tiered-stack-wiring.md` and
the schema in signals `214236_schema-final-e2e.md`. Commit `27f5ee2`.

- `warehouse_ingest.py` — 25 series (17 DCGM INT incl. `dcgm.power_mw`, 8
  cognition DECIMAL `cog.<channel>`), `series_id = blake2b(name)`; Prometheus
  parsed as text so integers never pass through `float()`.
- `cognition_waterfall.py` — `fetch_gpu_metrics` / `fetch_cognition_metrics`
  read `signal_tier0` (kudu_scan, `series_id = ANY(...)`, `ts_ns` range);
  `tick_from_gpu_rows` pairs power/util per (gpu, column).
- `fetch_gpu_hist_buckets` (Kumo) — one query on the `signal` view.
- Engine readiness probe: `scripts/zndx_status_ok.py` via process-compose.
