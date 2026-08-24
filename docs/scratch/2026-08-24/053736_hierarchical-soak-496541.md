# Hierarchical soak tick (05:37Z)

Sampler still C++ (`pid 2989721`, ~84 min, `kudu_ok`). jsonl ~4.4 h.
Hour **496541** still open (~37 min jsonl / 23076 Kudu rows with engine
double-write). Impala FE already `IMPALA_BUILD_OK`.

## Proven (no fake rows)

- C++ upsert **89034**. FDW lag ~0.1 s, `power_w` 7–142.
- Iceberg analog hours unchanged: 12156+21930+21594+19968.
- Kudu ranges 496536–496544. Strip=1h `driver=warehouse` matrix 72000.

## Fail-fast leftovers

- Do not analog 496541 until the hour closes (≥55 min).
- Do not DROP Kudu 496540 (`kudu_scan` 1h strip; UNION double-counts).
- Static `/tmp/gpu_kudu_create` still 01:57Z; `impala_sql` HS2 GSSAPI still missing.
