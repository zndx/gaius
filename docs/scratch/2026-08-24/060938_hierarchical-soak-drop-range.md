# Hierarchical soak: DROP RANGE after analog 496541 (06:09Z)

Sampler still C++ (`pid 2989721`, ~2 h, `kudu_ok`). Hour **496542** hot.
Closed **496541** analog 21594 jsonl rows → HDF5 on Polarisfork. HS2
Iceberg `GROUP BY` = 12156+21930+21594+19968+**21594**. Sample
`power_w=109` `util=28` `mem=21334`.

Dropped Kudu range partitions **496537–496541** (ALTER reported
TTransportException; SHOW RANGE left 496536 + 496542–544). UNION no
longer double-counts:

| hour   | store   | count |
|--------|---------|-------|
| 496537 | Iceberg | 12156 |
| 496538 | Iceberg | 21930 |
| 496539 | Iceberg | 21594 |
| 496540 | Iceberg | 19968 |
| 496541 | Iceberg | 21594 |
| 496542 | Kudu    | live  |

FDW `:5455` `gpu_metrics` is `impala_sql` of that view. Postgres
`SELECT` returns analog Iceberg rows + live Kudu. Strip=1h CLI+UI
`driver=warehouse` matrix 72000 (window spans Iceberg 496541 + Kudu
496542). Hot lag via UNION ~25 s (was ~0 on `kudu_scan`).
