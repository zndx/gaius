# Hierarchical soak: analog 496549 (14:09Z)

Jsonl sampler `pid 36619` (~16 min this life) and engine warehouse
ingest `pid 8851` (~19 min) still up. Hour **496549** closed at 14:00Z.
Live hour **496550** is Kudu-only (engine FDW INSERT).

## Proven (no fake rows)

- Closed-hour analog from **FDW Kudu** (engine writer + sidecar
  13:00–13:46): **19752** rows → `gpu_metrics_hour_496549.h5`
  (195479 B). Jsonl for that hour is **18918** rows (3153 ticks) —
  short **447** ticks for the 13:46:23–13:53:50 sampler death, plus
  engine-only 13:50–13:53 not in jsonl. Analog used warehouse rows,
  not padded jsonl. Polarisfork `FileFormat.HDF5`. HS2/FDW
  `gpu_metrics_tier1` GROUP BY includes **19752** for 496549. Sample
  `power_w=104` `util=100` `mem=21334` (real nvidia-smi).
- **DROP RANGE 496549 not applied this tick** (cluster mutation
  blocked in auto mode). UNION currently **double-counts** 496549
  (Iceberg 19752 + Kudu 19752 = 39504). Live 496550 is not doubled.

  | hour   | store            | count |
  |--------|------------------|-------|
  | 496537 | Iceberg          | 12156 |
  | …      | Iceberg          | …     |
  | 496548 | Iceberg          | 21600 |
  | 496549 | Iceberg **and** Kudu | 19752 each (UNION 39504) |
  | 496550 | Kudu             | live  |

- FDW `:5455` `gpu_metrics` `impala_sql`. Live lag ~0.9 s. Strip=1h
  CLI+UI `driver=warehouse`, `n_times=3600`, matrix 72000.

## Next

Confirm `ALTER TABLE … DROP RANGE PARTITION 496549 <= VALUES < 496550`
then ADD 566–569. Analog 496550 after 15:00Z close.
