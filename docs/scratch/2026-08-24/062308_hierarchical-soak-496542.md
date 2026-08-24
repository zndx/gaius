# Hierarchical soak tick (06:23Z)

Sampler still C++ (`pid 2989721`, ~2.2 h, `kudu_ok`). Hour **496542** hot
(~21 min jsonl). Impala FE already `IMPALA_BUILD_OK`.

## Proven (no fake rows)

- FDW UNION: Iceberg 496537–496541 exact analog counts; Kudu **496542**
  8088, lag ~2.4 s (`power_w` 7–131).
- Dropped leftover empty range **496536**. Kudu ranges now 496542–544.
- Strip=1h `driver=warehouse` matrix 72000 (Iceberg 496541 + Kudu 496542).

## Next

Analog 496542 after 07:00Z. Static `gpu_kudu_create` still 01:57Z.
Sidecar HS2 path still `No module named 'impala'` (C++ ingest is enough).
