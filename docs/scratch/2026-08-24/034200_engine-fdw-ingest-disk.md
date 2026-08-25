# Engine warehouse ingest through impala_fdw; disk pressure

## Spec

`impala_fdw` SPEC **v0.5**: G11 INSERT (UPSERT) on `kudu_scan` foreign tables. N3 now excludes only UPDATE/DELETE and HS2 INSERT.

Verified: `INSERT INTO gpu_metrics …` on devenv PG `:5455` round-trips through the FDW to Kudu (`ts_ns=1999999999999` SELECT).

Gaius engine `warehouse_ingest` starts with `start_strip()` in `server.py`: nvidia-smi → `asyncpg` INSERT. Next engine process (not a full `signals.target`) picks it up. Stop the ad-hoc `scripts/gpu_metrics_kudu_ingest.py` once the engine loop is live so we do not double-write.

## Disk pressure (nodefs `/`, kubelet soft `<10Gi`)

`/` is **871 GiB / 916 GiB (7.4 GiB free, 100%)**. Raid `/md0` has **553 GiB free** — Kudu/RustFS data is not the eviction source.

| Path | Size | Ours? |
|------|------|-------|
| `/home/rch/.cache` | **100 GiB** | Yes — **uv 91 GiB**, vllm 601 MiB |
| `gaius/.devenv` | **27 GiB** | Yes — postgres **13 GiB**, nifi 1.3 GiB |
| `signals/.devenv` | **23 GiB** | Yes (toolchain, m2, kudu build trees) |
| `/var/log` | 3.6 GiB | Host |
| `/var/lib/rancher` | 293 MiB | k8s (small) |
| gpu-metrics jsonl | **3 MiB** | Negligible |
| Kudu tablets | `/raid/signals` | Off nodefs |

So **yes**: lab/dev caches and devenv state on the root disk are what keep kubelet in `DiskPressure`. Ingest is not. Highest-leverage reclaim: `uv cache prune` (~91 GiB) and moving or vacuuming Gaius devenv postgres (13 GiB). Leave `/raid` alone.