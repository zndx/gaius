# Signals peer unit (gaius.service)

Gaius joins the Signals lattice as peer id `gaius`. systemd is only
the `signals.target` membership hook. The wire contract is
`zndx.engine.v1.Engine` on **:50051**.

**Devenv-centric wrap:** `ExecStart` is `devenv up -d` — the same graph
as a login-shell `devenv up`. devenv assigns ports (so worktrees and
sibling projects do not collide) and injects secrets via SecretSpec.
Do not pin `PGPORT` or a dedicated `DEVENV_RUNTIME` in the unit. Lattice
accept is Engine/Status at gRPC bind, not vLLM SERVING and not a
systemd-cgroup ownership check.

This is **not** the older GPU-mesh story in `src/gaius/engine/FEDERATION.md`.
Lattice accept is Engine/Status, not KServe peer discovery.

| Fact | Value |
|------|--------|
| Peer id | `gaius` |
| Unit | `gaius.service` (`After=signals-ready.service`) |
| Wrappers | `scripts/systemd_start.sh` / `scripts/systemd_stop.sh` |
| gRPC lattice | `:50051` — `zndx.engine.v1.Engine` (+ native `GaiusService` + OIP) |
| Postgres | `:5444` (`zndx_gaius`) — never Signals `:5455` |
| Capability | `cognition` |
| Status.project | `gaius` |

## Wrappers

`systemd_start.sh` is idempotent: if a **process-compose-owned** listener
already answers `Engine/Status` **and** a login-shell `devenv processes`
sees that compose, it exits 0. The wrappers pin `XDG_RUNTIME_DIR` to
`/run/user/<uid>` so `systemctl restart gaius` and `devenv processes
restart gaius-engine` share one graph. Foreign `setsid` engines
(`#EN.00000016.NOTUNIT`) are reaped, then `devenv up -d` (never
foreground `just up` from the unit). Do not pin a dedicated
`DEVENV_RUNTIME` or `PGPORT` in the unit — that splits systemd from the
login-shell devenv.

`setsid` / PPID-1 `python -m gaius.engine` is test-only while
`devenv processes` is down. Normal operations use systemd and/or devenv
on this same graph.

`systemd_stop.sh` runs `just down` / `devenv processes down` for this
checkout and reaps leftover `gaius.engine` PIDs. It does **not** call
`just teardown` / GPU cleanup (sibling leases).

```bash
# Same graph as the unit
devenv up -d
devenv processes status          # includes gaius-engine
grpcurl -plaintext 127.0.0.1:50051 zndx.engine.v1.Engine/Status
devenv processes restart gaius-engine
just down
```

## Operator (after wrappers land)

From the Signals tree:

```bash
just install-systemd --peers gaius --enable
sudo systemctl restart signals.target    # complete group refresh (not bare "signals")
# or from Signals: just signals-restart
grpcurl -plaintext 127.0.0.1:50051 zndx.engine.v1.Engine/Status
just lattice-ci --require gaius
```

`systemctl start gaius` starts this peer alone; it still waits on
`signals-ready.service`. Unit start is not Status-only: wrappers wait for
Engine/Status **and** board UI `:9890` (Postgres lattice `:5444`).

The unit is `Type=oneshot` `RemainAfterExit=yes` with `KillMode=control-group`.
It sets `XDG_RUNTIME_DIR=/run/user/<uid>` only (same as Atelier / Signals
sample). After `systemctl restart gaius`, one `gaius.engine` on `:50051`
must be a child of this checkout's process-compose — the graph
`devenv processes` sees.

## Platform Metaflow / events (when federated)

When Gaius is joining the Signals foundation, treat platform Metaflow as the
system of record — do not treat the Gaius-local Tilt Metaflow as SoR.

Adoption is **detected**, not a flag: `gaius.flows.platform_metaflow` calls
`zndx.engine.v1.Engine/Status` on Signals `:50551`. If `project=signals` and
capability `metaflow` (preferred) or `scheduler` (YuniKorn today) is healthy,
and `http://127.0.0.1:30180/ping` returns pong, flows apply
`config/metaflow/platform.json` (or `$SIGNALS_ROOT/config/metaflow/platform.json`).
If Signals is present but that ping fails, Gaius fail-fasts
`#MF.00000006.NOPLATFORM` — it does **not** stand up Tilt Metaflow.

```bash
export METAFLOW_SERVICE_URL=http://127.0.0.1:30180
# profile resolved by apply_metaflow_config() / metaflow_child_env()
grpcurl -plaintext 127.0.0.1:50551 zndx.engine.v1.Engine/Status
```

CloudEvents such as `dev.gaius.article.curate.requested` go to the platform
broker (`signals-events/default`), not a Gaius-local event bus.

Gaius-local Metabase on `:3100` is **not** the federation dashboard. That is
the optional AGPL Metabase peer (`:3200` / `:50451`).

## YK Applications (resource class, not `root.gaius`)

There is no `root.gaius`. Project is identity (`federation.project=gaius`,
C2, `Engine/Yield`). `article_curate` and `prospects_update` admit a YK
Application on **`root.internal.inference.extract`** before the Metaflow
child starts. Host GPU occupancy is `federation.zndx.org/gpu` only — never
`nvidia.com/gpu` on the CPU-only sentinel.

`BeginWorkload` refuses exclusive GPU if no admitted Application exists
(`#YK.00000003.NOAPP`). Intra-node `/tmp/zndx-gpu-leases` stay refuse-only.
Nested render/extract rides the parent Application id. A live extract
Application is reused (`bind_workload_id`) — next `/article curate` does
not mint a new `app-id`. Teardown is Yield (or host-child exit). Do not
call YuniKorn REST; observe via Signals
`zndx.scheduler.v1.Scheduler/ListQueueApplications`.

## Always-on survey → morning sitrep

Gaius is meant to stay on: survey the world and condense it so a morning
sitrep (or a conversation about that sitrep) is already written. That work
is **YK occupancy**, not silent host CUDA.

| Clock (pg_cron, UTC) | Host child | YK leaf |
|----------------------|------------|---------|
| `0 7 * * *` `prospects-daily-check` | FMP triage (API, no GPU) | **`root.external.rate-metered`** — admit, then delete (comes and goes) |
| then `prospects_update` if recommended | docling / filings / sitrep | **bind** live extract Application |
| else `record_availability` | History heartbeat (`kind=maintained`) | no new GPU claim |

`gaius.prospects.corpus` stays current **without a human or ACP hop**.
`gaius.service` (under `signals.target`) keeps `ScheduledTaskProcessor`
listening. Engine start **catch-up** inserts `prospects_check` when the
24h cooldown is due, so a recycle cannot skip a day. HX and product
objects use RustFS `s3://signals-dataproducts/gaius/…`, not devenv
MinIO. A reused extract Application is **not** deleted when update ends.
Airflow remains the federation-wide clock for `@kubernetes` platform
flows; this peer cadence is pg_cron + LISTEN while the unit is up.
| `0 9 * * *` `article-curate-daily` | article pipeline | **bind** same extract `app-id` |
| Engine start (default) / `/ambient stop` | RAM FIFO; Qwen think-summarize when extract is admitted | **`root.internal.compute`** standing (`gaius-ambient`); summarization **binds extract**. Yield **pauses GPU**, buffer stays. |

One extract Application holds `federation.zndx.org/gpu=1` of parent
`internal.inference` max 6. Ægir and Atelier keep **instruct / reasoning /
orchestration** leaves. They cannot take Gaius's extract token; Gaius
cannot squat their leaves. That is how always-on survey stays fair.

**Envelope (what Signals / YK should show).** Tinybox physical is 6 GPU
tokens, ~128Gi RAM, 916G `/` and 3.6T `/raid`. Gaius never asks YK for
more than this claim, and refuses a new host child when the box is past
the host floors:

| Dimension | Gaius claim / floor | YK parent max | Physical (tinybox) |
|-----------|---------------------|---------------|--------------------|
| Applications | **1 per leaf** (`bind_workload_id`; `#YK.00000004.ENVELOPE` if 2 on the same queue) | extract 16 / rate-metered 16 / compute 32 | — |
| `federation.zndx.org/gpu` | **1** (limits=requests) | 6 | 6 |
| claim memory | **16Mi** | 400Gi inference | ~128Gi |
| claim vcore | **10m** | 64 | 64 |
| host `/` free | **≥ 32Gi** — KB / PG lanes only (`article-curate`) | not a YK resource | 916G |
| host `/raid` free | **≥ 64Gi** — RustFS product / FMP / prospects | not a YK resource | 3.6T |
| host `MemAvailable` | **≥ 8Gi** (`#YK.00000006.MEM`) | not a YK resource | ~128Gi |

Dashboard evidence is three Gaius rows on existing Signals leaves
(never `root.gaius`):

1. **extract** — one Running GPU token (allocated GPU=1, headroom GPU=5).
   Article, `prospects_update`, and Ambient/FMP agentic summarization
   bind this `app-id`.
2. **rate-metered** — FMP ingest. Appears for the check, then Completing.
   That flicker is the intended signal: the API comes and goes.
3. **compute** — Ambient RAM FIFO (`gaius-ambient`). **On by default** at
   engine start unless `/ambient stop` (operator-disabled). No GPU, no
   disk write. Think-summarize binds extract (`thinking` = Qwen3.8-27B,
   capabilities `[thinking, vision]`). Yield of extract pauses GPU
   phases; Yield of `gaius-ambient` drops the compute row.

**Ambient phases (YK stamps `federation.phase`).** Buffer never takes a
GPU token. Summarize and planned compact **share** the one extract token
so Ægir fine-tune preempts a single claim, not two.

| Phase | Kind | Leaf | GPU | When |
|-------|------|------|-----|------|
| `buffer` | `ambient` | `internal.compute` | 0 | daemon lifetime (HN FIFO, 16Mi/10m) |
| `summarize` | `ambient-summarize` | `internal.inference.extract` | 1 | think-summarize on thinking vLLM |
| `compact` | `ambient-compact` | `internal.inference.extract` | 1 (same bind) | planned sitrep compaction |

Thinking vLLM still occupies **4 physical 4090s**. The extract token is
the federation-visible lid (1 of 6). Ægir fine-tune that needs those
cards must preempt extract → Yield → Ambient `pause_gpu`; freeing the
cards is a later eviction of thinking (not automatic this step — `/ask`
shares that process).

YK enforces apps / GPU / claim cpu / claim memory. Host disk and RAM
are Gaius floors — the pause pod cannot cap Metaflow artifacts, KB, or
Postgres `:5444`. Ambient skips the disk floor (buffer is RAM-only).
Crossing a floor keeps the Application (occupancy stays visible) and
fail-fasts the child so we cannot write the box empty. Measure with
`dust`, not `du`.

`prospects_update` already writes `scratch/<date>/*_prospects_sitrep.md`.
Article curate fills the publication backlog. Yield (C2 `:50561` →
`Engine/Yield` `:50051`) is the only teardown of the extract claim.

## Health

Health/FMEA stays Gaius-local (`/health`, `/health fix engine`). Lattice-ci
probes generated-client Status **and** server reflection (`grpcurl list`).
Generated stubs remain the protocol SoR; reflection is the external spot-check.

`:50051` is exclusive. gRPC `SO_REUSEPORT` is off; a second `gaius-engine`
must fail with `#EN.00000014.DUALBIND` rather than dual-bind. GPU cleanup
is lease-aware and must stay that way so Ægir/Atelier endpoints survive a
Gaius restart.
