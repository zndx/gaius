# Hierarchical soak: analog 496550 (15:17Z)

Jsonl sampler `pid 36619` (sample-only, `kudu_via=engine_fdw`, `inserted:0`)
and engine warehouse ingest `pid 267627` (started 14:18Z) still up. Impala
FE already `IMPALA_BUILD_OK`. Hour **496550** closed at 15:00Z. Live hour
**496551** is Kudu-only (engine FDW INSERT). Do not analog the open hour.

## Proven (no fake rows)

- Closed-hour analog from **FDW Kudu** (engine writer): **20334** rows →
  `gpu_metrics_hour_496550.h5` (200911 B) on analog + Iceberg data
  prefixes. Jsonl for that hour is **21570** rows (3595 ticks) — short
  **206** warehouse ticks for engine/DCGM gaps (14:17 restart, 14:21
  `:9400` blip). Analog used warehouse rows, not padded jsonl.
  Polarisfork `FileFormat.HDF5`. HS2/FDW `gpu_metrics_tier1` GROUP BY
  includes **20334** for 496550. Sample `power_w=125` `util=100`
  `mem=21332` (real DCGM / nvidia-smi).
- FDW `:5455` `gpu_metrics_tier0` live lag ~0.6 s. Sample `power_w≈50–68`
  `mem=21225` on GPUs 0–3 (thinking loaded).
- Strip=1h UI+gRPC `driver=warehouse`, `n_times=3600`, `n_channels=20`,
  matrix **72000**. gpu-0..5 nonzero 3372/3600 (honest gaps). `gaius-cli`
  import currently fails (`NEXT_QUESTION_RESERVE_TOKENS` missing from
  dirty `cognition_buffer.py`); landing strip is the UI/gRPC path.

## UNION double-count (needs catalog mutation)

Live `SHOW CREATE VIEW signals_dataproducts.gpu_metrics` is
`tier0 UNION ALL tier1` **without** the `NOT IN` Kudu-hour exclusion
from `config/platform/gpu-metrics-iceberg.sql`. After analog, UNION
`496550` = **40668** (Iceberg 20334 + Kudu 20334). Other analog hours
match Iceberg exactly; live 496551 is Kudu-only.

`DROP RANGE PARTITION VALUE = 496550` and `ALTER VIEW … NOT IN` were
not applied this tick (cluster mutation blocked in auto mode). Confirm:

```
ALTER TABLE signals_dataproducts.gpu_metrics_tier0
  DROP RANGE PARTITION VALUE = 496550;
ALTER VIEW signals_dataproducts.gpu_metrics AS
  … tier0 UNION ALL tier1 WHERE epoch_hour NOT IN (SELECT … tier0 …);
ALTER TABLE … ADD RANGE PARTITION VALUE = 496566;  -- through 569
```

`SHOW RANGE` is still `VALUE = 496550` … `496565`.

## Next

Approve DROP RANGE 496550 (and ALTER VIEW NOT IN), then ADD 566–569.
Analog 496551 after 16:00Z close. Keep sampler 36619 and engine ingest.
