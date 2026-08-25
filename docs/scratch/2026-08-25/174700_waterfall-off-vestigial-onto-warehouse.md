# Waterfall reads the warehouse, not the process

The Discover waterfall had drifted: GPU channels were already warehouse-backed,
but eight cognition channels were still advertised from the in-process driver
registry and could never be filled by the warehouse path. They sat at zero
forever, which is why "most of the metrics became unwired".

```text
before                                 after
gpu-0..5     50/60  live               gpu-0..5   live   (Kudu ∪ Iceberg)
util-0..5    live / idle               util-0..5  live / idle
kv run gen-tps prefill   0/60 dark      persisted + read from cognition_metrics
clt sae ricci ricci-d    0/60 dark      persisted + read from cognition_metrics
driver: warehouse                      driver: warehouse
```

## What was actually wrong

`tick_from_gpu_rows` filled `gpu-{i}` and `util-{i}` and nothing else, while
channel *names* still came from `all_channel_names()` — the legacy registry of
four in-process drivers. So the strip advertised 20 channels and could fill 12.

The tremor gauge went with it: `set_cognition_tremor` was only called on the
retired in-process path, so `gaius.cognition.tremor` silently stopped being
published the moment the warehouse path became the default.

## What DCGM offers

The exporter (`federation-system/dcgm-exporter`, DaemonSet, `:9400`) publishes
17 metric families × 6 GPUs. The ingest persisted 4:

```text
persisted already   POWER_USAGE  GPU_UTIL  FB_USED  GPU_TEMP
added now           SM_CLOCK  MEMORY_TEMP  TOTAL_ENERGY_CONSUMPTION  XID_ERRORS
still unpersisted   MEM_CLOCK ENC_UTIL DEC_UTIL FB_FREE MEM_COPY_UTIL
                    NVLINK_BANDWIDTH_TOTAL {UN,}CORRECTABLE_REMAPPED_ROWS
                    ROW_REMAP_FAILURE
```

XID earns its place as a hardware-fault signal `/health` can consume; energy
enables thermal/cost work.

## Warehouse shape

Three product families, each `tier0` (Kudu, hot) ∪ `tier1` (Iceberg+HDF5,
settled) behind an Impala UNION view, all reachable as plain Postgres through
`impala_fdw`:

| product | grain |
|---|---|
| `gpu_metrics` | wide: power_w, util_pct, mem_used_mb, temp_c per GPU (unchanged) |
| `gpu_dcgm` | narrow: (gpu_index, field, value) — the four added DCGM fields |
| `cognition_metrics` | narrow: (channel, value, present) — the strip's 8 cognition channels |

### Why narrow, not columns on gpu_metrics

The plan was to widen `gpu_metrics`. It cannot be widened from here:

- `gpu_metrics_tier0` is created by the C++ `gpu_kudu_create` client (HS2
  `CREATE ... STORED AS KUDU` hits KUDU-2121), so this HMS-free Impala resolves
  it read-only through the `signals_catalog.catalog_tables` registry.
  `ALTER TABLE ... ADD COLUMNS` returns `TableNotFoundException` while
  `DESCRIBE` on the same table succeeds.
- `gpu_metrics_tier1` is `READONLY` to Impala: `Write not supported`.
- No `kudu` CLI is installed, so the Kudu-client path is not available either.

A sibling narrow table needs no mutation of either tier, and a further DCGM
field now costs no warehouse DDL at all. `present` on cognition_metrics carries
the same idea: a gap is a gap, never a zero.

### Iceberg registration

`CREATE ... STORED AS ICEBERG` through Impala does **not** reach the Polaris
MetaProvider here — Impala tries the Kudu provider and reports
`NoSuchObjectException`. Iceberg tiers were created through the Polaris REST
API and registered by hand, mirroring `gpu_metrics_tier1` exactly:

```text
POST /api/catalog/v1/signals/namespaces/signals_dataproducts/tables
INSERT INTO signals_catalog.catalog_tables (db_name, table_name, table_type, parameters)
  ... 'ICEBERG', {"location": "s3://…/iceberg/signals_dataproducts/<t>",
                  "iceberg.catalog": "polaris", "write.format.default": "hdf5"}
```

## Range partitions

Kudu range partitions are per UTC hour and an INSERT into an hour with no
partition fails the flush. `impala_fdw_exec` permits exactly this DDL, so the
ingest now provisions the hour on first tick of each hour across all three
tier0 tables.

The FDW's own post-ALTER check reads `SHOW RANGE PARTITIONS` before the catalog
settles and reports `ALTER RANGE did not verify` for a partition that is in
fact present, so `ensure_hour_partition` asks again itself and treats that
answer as authoritative.

## Verified

```text
warehouse partitions hour=496577 {'gpu_metrics_tier0': 'present',
  'gpu_dcgm_tier0': 'present', 'cognition_metrics_tier0': 'present'}

gpu_dcgm_tier0     energy_mj 1062 rows  1.5e10..6.9e10
                   sm_clock_mhz 1062    210..2670 MHz
                   mem_temp_c 1062      0 (not reported by these cards)
                   xid_errors 1062      0 (no faults)

cognition_metrics_tier0   8 channels × ~121 rows
                          ricci present=true, mean 0.0118

/thoughts waterfall  driver=warehouse  ricci 44/60 live from Kudu
```

Round-tripped through both readers — Gaius `:5444` and Signals `:5455` — via
the UNION view.

Channels reading `present=false` (kv/run/gen-tps/prefill, clt/sae) are honest:
vLLM `:8081` was reloading and the CLT service was not loaded. The flag exists
so a dark channel means "not reported", not "zero".

`tests/engine/` 703 passed (2 pre-existing `test_gaius_servicer.py::TestComplete`
failures untouched); `test_warehouse_cognition.py` covers narrow-row shape,
absent-field-is-absent-row, gap-is-not-zero, tremor from onset channels only,
unknown channels ignored, and the GPU strip surviving an empty cognition set.

## Not done

**Tier-up for the two new tables.** `gpu_metrics_tier_up.py` settles a closed
hour of `gpu_metrics_tier0` into Iceberg+HDF5 and hardcodes that table's
columns. `cognition_metrics` and `gpu_dcgm` have their Iceberg tiers and views
but nothing migrates into them yet, so their tier0 grows in Kudu unbounded.
Nothing DROPs their range partitions (`gpu_metrics_settle` only knows
gpu_metrics), so there is no data-loss risk today — only unbounded hot storage.

**A related find:** `gpu_metrics_tier0` had range partitions only to hour
496582 when the current hour was 496577 — about five hours of runway. The
ingest's `ensure_hour_partition` now provisions the hour for all three tables
on the hour boundary, which closes that gap, but it is worth knowing the
warehouse was that close to refusing writes.

## Incident: I broke the gaius venv mid-task

Reaching Impala needs the Signals HS2 client. I ran `uv run python -c "from
signals.impala import …"` believing my shell was in the Signals checkout — a
`cd` from an earlier command had not persisted, so it ran against **gaius**.
`uv` re-resolved and installed a CUDA-13 stack beside the locked CUDA-12 torch:

```text
17:50  nvidia-nccl-cu13 nvidia-cudnn-cu13 nvidia-cusparselt-cu13 nvidia-nvshmem-cu13
       → ImportError: libtorch_cuda.so: undefined symbol: ncclCommResume
```

`uv.lock` was untouched and lists none of those. `uv sync` would have restored
them but also pruned `pyluxcore`, which is installed `--no-deps` on purpose, so
the repair was surgical: uninstall the four cu13 packages, then reinstall the
locked cu12 libraries whose shared `nvidia/` trees the cu13 wheels had
overwritten (`cudnn 9.20.0.48`, `nccl 2.29.7`, `cusparselt 0.8.1`,
`nvshmem 3.4.5`).

```text
torch 2.13.0+cu129 cuda 12.9 | import OK
tests/engine + tests/health   719 passed
vllm=200   engine :50051 up
```

The running stack was never affected — vLLM and the engine hold their libraries
mapped — but the next endpoint restart would have failed to import torch.

Lesson: `cd` does not persist between tool calls here. Use the target repo's
interpreter by absolute path (`$SIGNALS_ROOT/.devenv/state/venv/bin/python`)
rather than `uv run`, which resolves against whatever project the cwd happens
to be.
