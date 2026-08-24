# Hierarchical soak: hour 496541 hot (05:23Z)

Sampler still C++ (`pid 2989721`, elapsed ~70 min, `kudu_ok`, `kudu_err` empty).
jsonl ~4.2 h. Impala FE already `IMPALA_BUILD_OK`.

## Proven (no fake rows)

- FDW `:5455` hours 496537–496541; hot lag ~0.1 s (`power_w` 7–142).
- C++ jsonl upsert **83586**. Kudu ranges 496536–496544 (covers next
  three hour rolls).
- Iceberg HDF5 still 12156+21930+21594+**19968** (496540 analog).
- Strip=1h CLI+UI `driver=warehouse`, matrix 72000.

## Fail-fast leftovers

- `/tmp/gpu_kudu_create` is still the 01:57Z static 154 MiB binary
  (create no-op if table exists). Source adds ranges; a dynamic
  toolchain link needs `libsasl2.so.2` / older libstdc++ — do not
  replace the working static helper.
- Do **not** DROP Kudu 496540: FDW strip is `kudu_scan`; UNION
  double-counts that hour. `impala_sql` HS2 GSSAPI still missing.
