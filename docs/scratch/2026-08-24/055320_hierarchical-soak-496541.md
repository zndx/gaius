# Hierarchical soak tick (05:53Z)

Sampler still C++ (`pid 2989721`, ~100 min, `kudu_ok`). jsonl ~4.7 h.
Hour **496541** still open (~53 min jsonl / 33765 Kudu rows). Impala FE
already `IMPALA_BUILD_OK`.

## Proven (no fake rows)

- C++ upsert **94548**. FDW lag ~0, `power_w` 7–142.
- Iceberg analog unchanged: 12156+21930+21594+19968 (through 496540).
- Ranges 496536–496544. Strip=1h `driver=warehouse` matrix 72000.

## Next tick

Analog 496541 after 06:00Z close. Do not DROP Kudu 496540 (`kudu_scan`
1h strip; UNION double-counts). Static `gpu_kudu_create` not rebuilt.
