# Guru Meditation Codes

Complete catalog of error codes used across the Gaius platform.

## Format

**`#<COMPONENT>.<SEQUENCE>.<MNEMONIC>`**

## Catalog

### DS — DatasetService

| Code | Description | Fix |
|------|-------------|-----|
| `#DS.00000001.SVCNOTINIT` | DatasetService not initialized | `/health fix dataset` |

### NF — NiFi

| Code | Description | Fix |
|------|-------------|-----|
| `#NF.00000001.UNREACHABLE` | NiFi not reachable | `/health fix nifi` |

### EN — Engine

| Code | Description | Fix |
|------|-------------|-----|
| `#EN.00001.GRPC_BIND` | gRPC port bind failure | Check port 50051 |
| `#EN.00000014.DUALBIND` | Second gaius-engine dual-bound `:50051` (SO_REUSEPORT / extra devenv daemon) | `/health fix engine`; `ss -ltnp \| grep 50051` and stop the extra stack |
| `#EN.00000015.NOREFLECT` | grpcio-reflection import failed (protobuf gencode/runtime mismatch) | `uv sync --extra grpc` (lock pins `grpcio-reflection<1.82`) |
| `#EN.00000016.NOTUNIT` | `:50051` is `gaius.engine` but not this checkout's process-compose (setsid leftover) | `sudo systemctl restart gaius.service` or `devenv processes restart gaius-engine` — setsid only while devenv is down (tests) |
| `#EN.00002.VLLM_START` | vLLM startup failure | `/health fix endpoints` |
| `#EN.00003.GPU_OOM` | GPU out of memory | `just gpu-cleanup` |
| `#EN.00004.ORPHAN_PROC` | Orphan vLLM process | `just gpu-cleanup` |

### EP — Endpoints/Inference

| Code | Description | Fix |
|------|-------------|-----|
| `#EP.00000001.GPUOOM` | GPU out of memory during inference | `/health fix endpoints` |
| `#EP.00000002.NOAGENT` | Unknown agent alias | Use `thinking` (Qwen3.8-27B) or `open-thinking` (Olmo) |
| `#EP.00000003.CTXFIT` | Qwen3.8-27B `--max-model-len` did not fit 4×4090 BF16 | Set `resources.context-length` in `agents.conf` to the largest value that starts |
| `#EP.00000004.VLLMARGS` | vLLM rejected flags or model config (e.g. `qwen3_5` / transformers) | Match `vllm` + `transformers` to the Qwen3.8 recipe; do not guess flags |
| `#EP.00000005.TINYBOXCUDA` | Qwen3.8 JIT `cicc` loaded Nix `libstdc++` (needs glibc 2.38) | Host gcc-11 + `scripts/lib/tinybox-nvcc.sh` as `$CUDA_HOME/bin/nvcc`; do not install CUDA 13 |
| `#EP.00000006.VLLMTIMEOUT` | vLLM HTTP read timed out on Complete (thinking + queue > read timeout) | `/health fix endpoints`; sitrep follow-up needs the 180s read timeout |
| `#EP.00000007.SHMFULL` | `/dev/shm` full — leftover `vllm_offload_*.mmap` / `psm_*` after unclean vLLM stop | `/health fix endpoints` (reclaims unheld segments); `just gpu-cleanup` |
| `#EP.00000016.NOTREADY` | Complete hit a vLLM that is absent/STARTING | Wait for `/gpu status` HEALTHY; Settings starts light or medium Ask. Charts do not wait. |
| `#EP.00000017.NOTELEMETRY` | Signals `kind=telemetry` surface missing or :9410 returned 503 | Confirm `SIGNALS_ENGINE_TARGET` Status.surfaces; dcgm-exporter on :9400; no DCGM dep in Gaius |

### OPT — optillm proxy

| Code | Description | Fix |
|------|-------------|-----|
| `#OPT.00000001.WATCHDOG` | gunicorn auto-restart failed (often `:8000` held by a foreign master) | `/health fix optillm` |
| `#OPT.00000002.NOTSTARTED` | OptillmController never started | `/health fix optillm` |
| `#OPT.00000003.UNHEALTHY` | optillm HTTP not 200 | `/health fix optillm` (reaps foreign `:8000`) |
| `#OPT.00000004.NOVLLM` | No healthy generate vLLM provided and thinking demand failed | `/health fix endpoints`; optillm binds any provided vLLM |

### DI — Discover landing

| Code | Description | Fix |
|------|-------------|-----|
| `#DI.00000001.NODB` | Discover has no engine db_pool | `/health fix postgres` |
| `#DI.00000002.BADWINDOW` | Window not `36h` / `7d` / `1h` | Pass a 1..3660 day window |
| `#DI.00000003.BADLIMIT` | limit not in 1..200 | Pass 50 |
| `#DI.00000004.BADBREAK` | breakdown not stream/source/layer | Pass `source` |
| `#DI.00000005.BADFEATURE` | feature pin not `layer:index` | `feature:12:4412` |
| `#DI.00000006.SURFACE` | Discover SQL failed | `/health fix postgres` |

### AG — Agenda (consciousness zettels)

| Code | Description | Fix |
|------|-------------|-----|
| `#AG.00000001.NOKB` | `GAIUS_KB_ROOT` missing or not a directory | Set `GAIUS_KB_ROOT` (default `build/dev`) |
| `#AG.00000002.BADKIND` | kind not `note`, `list`, or `event` | `/agenda create note <title>` |
| `#AG.00000003.BADPATH` | Path escape, missing file, or not under `scratch/` | Use the path returned by create |
| `#AG.00000004.BADWINDOW` | `window_days` not in 1..3660 | Pass 14 |
| `#AG.00000005.EMITFAIL` | Scheduled surface could not write an Agenda zettel | Confirm `GAIUS_KB_ROOT` and `/agenda cards` |
| `#AG.00000006.NOMEETTIME` | `intent=session` without `starts` | Pass an ISO start; Agenda is the calendar |
| `#AG.00000007.BADINTENT` | intent not `brief`, `reminder`, or `session` | `/agenda create` with a valid intent |
| `#AG.00000008.NOWRITE` | Thinking did not emit an Agenda write artifact | Retry Ask, or Agenda + |
| `#AG.00000009.BADORIGIN` | `origin` is not `YYYY-MM-DD` | Pass the caller's calendar today |
| `#AG.00000010.BADTZ` | `timezone` is not a valid IANA name | Pass `America/Denver`, not `MDT` |

### SS — Server-to-server

| Code | Description | Fix |
|------|-------------|-----|
| `#SS.00000001.NOGIT` | `git` missing for ServerQuery remotes | Install git on the engine host |
| `#SS.00000002.NOREPO` | Checkout is not a git repository | Set `GAIUS_REPO_ROOT` / `DEVENV_ROOT` |

### WS — Weekly Signals Summary

| Code | Description | Fix |
|------|-------------|-----|
| `#WS.00000001.NOKB` | `GAIUS_KB_ROOT` missing or not a directory | Set `GAIUS_KB_ROOT` (default `build/dev`) |
| `#WS.00000002.BADWEEK` | ISO week not `YYYY-Www` | Pass `2026-W34` |
| `#WS.00000003.ACPFAIL` | ACP could not compose the readout | `grok login --device-auth`; `/health fix engine` |
| `#WS.00000004.BADPATH` | Path is not a `*_wWW-summary.md` under `scratch/` | `/summary list` |
| `#WS.00000005.BADSECTION` | collection not ontology/heuristic/articles/projects/thoughts | `/summary knowledge` |
| `#WS.00000006.BADLENS` | lens not `articles`, `projects`, or `thoughts` | `/summary index heuristic thoughts` |
| `#WS.00000007.NOLINK` | `[[wiki]]` target does not resolve | `/summary hop <from> <target>` |
| `#WS.00000008.NOPAGE` | Summary page missing or outside the KB jail | `/summary index` |
| `#WS.00000009.NOFORK` | virtual lens page, or peer `ServerQuery` NOTE unimplemented | Fork a real KB path; wait for peer S2S |
| `#WS.00000010.NOSCHED` | `cron.job` catalog unreadable | `/health fix postgres` |
| `#WS.00000011.NOTRIG` | Clock does not enqueue `scheduled_tasks` | `/summary schedules` |
| `#WS.00000012.NOSECTION` | `current/ontology` or `current/heuristics` missing | Create the collection under `GAIUS_KB_ROOT` |
| `#WS.00000013.BADKPATH` | Write escaped the ontology/heuristics jail | `/summary knowledge` |
| `#WS.00000014.NOTHOUGHT` | `thought/<id>` not in `cognition_thoughts` | Open it from `/cognition` |

### COG — Cognition

| Code | Description | Fix |
|------|-------------|-----|
| `#COG.00000002.DBREAD` | Failed to read `cognition_thoughts` | `/health fix postgres` |
| `#COG.00000018.NOSVC` | Cognition service missing on TriggerCognition | `/health fix engine` |
| `#COG.00000024.NOSVC` | Cognition service missing on CognitionSurface | `/health fix engine` |
| `#COG.00000025.NODB` | Surface needs the engine database pool | `/health fix postgres` |
| `#COG.00000026.BADWINDOW` | `window_days` not in 1..3660 | `/thoughts surface 365` |
| `#COG.00000027.BADLIMIT` | `thought_limit` not in 1..200 | Pass 80 |
| `#COG.00000028.SURFACE` | Surface query failed | `/health fix postgres` |
| `#COG.00000029.NOENGINE` | Thin client cannot reach engine gRPC for surface | `/health fix engine` |

### THETA — ThetaService / sitrep

| Code | Description | Fix |
|------|-------------|-----|
| `#THETA.00000007.NOSVC` | `ThetaService` not registered on the engine | `/health fix engine` |
| `#THETA.00000008.NOENGINE` | Thin client (CLI / TUI / MCP) cannot reach engine gRPC | `/health fix engine` |

### EM — Embeddings / late interaction

| Code | Description | Fix |
|------|-------------|-----|
| `#EM.00000001.NOVISION` | ColBERT-Zero asked to embed an image/PDF | Use Qwen3.8-27B vision; index extracted text |
| `#EM.00000002.NOPYLATE` | `pylate` not installed | `uv sync` |
| `#EM.00000003.RETIRED` | ColPali / ColNomic / ColQwen requested | Use `lightonai/ColBERT-Zero` |

### GR — gRPC

| Code | Description | Fix |
|------|-------------|-----|
| `#GR.00000001.CONNFAIL` | gRPC connection failed | Check engine status |
| `#GR.00000002.NOLATTICE` | Metaflow step cannot reach `zndx.engine.v1.Engine` | Set `GAIUS_ENGINE_GRPC`; apply `infra/k8s/gaius-engine-host-bridge.yaml` |
| `#GR.00000003.NOCAP` | Lattice Complete capability missing | Use `capability=thinking` |

### ACP — Agent Client Protocol

| Code | Description | Fix |
|------|-------------|-----|
| `#ACP.00000001.CONNFAIL` | ACP connection failed | Check grok CLI / thinking façade |
| `#ACP.00000002.TIMEOUT` | ACP connection timeout | Retry |
| `#ACP.SEC.00000002.NOTALLOWED` | Repo not in allowlist | Update acp.conf |
| `#ACP.SEC.00000003.NOTPRIVATE` | Repo not private | Make repo private |

### MF — Metaflow

| Code | Description | Fix |
|------|-------------|-----|
| `#MF.00000001.DBNOTCONN` | Metaflow metadata DB connection failed | Check platform PG / `just metaflow-platform` |
| `#MF.00000002.QUERYERR` | Metaflow metadata query failed | Inspect Metaflow service logs |
| `#MF.00000003.STACKDOWN` | Gaius-local Metaflow stack down | `/health fix metaflow` (standalone only) |
| `#MF.00000004.DNSDOWN` | In-cluster DNS for Metaflow pods | Check CoreDNS |
| `#MF.00000005.NOSCHED` | Signals Status reachable but scheduler/metaflow capability unhealthy | `just signals-ready`; YuniKorn :30080 |
| `#MF.00000006.NOPLATFORM` | Signals present but Metaflow `:30180` not ready | `just metaflow-platform` in Signals; do not start Gaius Tilt |
| `#MF.00000007.NOPROFILE` | Platform mode selected but `platform.json` missing | Set `SIGNALS_ROOT` or add `config/metaflow/platform.json` |

### YK — YuniKorn Application admit

| Code | Description | Fix |
|------|-------------|-----|
| `#YK.00000001.NOADMIT` | kubectl apply of the extract Application failed | Check `federation-signals` ns; stamp `yunikorn.apache.org/queue` |
| `#YK.00000002.NOTADMITTED` | Pod never reached Running on the leaf | `ListQueueApplications` on Signals `:50551`; GPU tokens advertised? |
| `#YK.00000003.NOAPP` | `BeginWorkload` without an admitted Application | Start the flow so `apply_and_admit` runs first |
| `#YK.00000004.ENVELOPE` | More than one Gaius Application on extract (1 GPU cap) | Yield the extra claim; `bind_workload_id` must reuse |
| `#YK.00000005.DISK` | This kind's write mount past floor (`/` 32Gi for KB/PG lanes; `/raid` 64Gi for RustFS product lanes; or >98% used) | `dust -d 1` on the mount in the guru text; product/FMP check `/raid` only |
| `#YK.00000006.MEM` | Host `MemAvailable` below 8Gi | Stop extra host children; do not mint another vLLM |
| `#YK.00000007.SHAREFAIL` | Signals rejected `RequestQueueShare` (cannot persist occupancy intent) | Signals `:50551` Scheduler; do not write queues.yaml from Gaius |

### DP — Signals Data Product (peer publish)

| Code | Description | Fix |
|------|-------------|-----|
| `#DP.00000001.NOPUBLISH` | `gaius.prospects.corpus` review into Signals warehouse failed | `uv run python -m signals.ops review-product gaius.prospects.corpus` in `$SIGNALS_ROOT`; `just signals-ready` |
| `#DP.00000002.NORUSTFS` | Product facts would point at a local / non-RustFS datastore | `GAIUS_METAFLOW_MODE=platform` (Signals `:30180` + RustFS `:9010`) |

### UI — gaius-ui (Keiretsu board + Ghostty harness)

| Code | Description | Fix |
|------|-------------|-----|
| `#UI.00000001.NOGROK` | Grok Build binary not found for the PTY harness | `export GAIUS_GROK_BIN=$(command -v grok)` or build `external/oss-grok-build` |
| `#UI.00000002.NOBWRAP` | `bwrap` missing; `--sandbox workspace` cannot enforce its deny list | Re-enter devenv (`pkgs.bubblewrap`) or `apt install -y bubblewrap` |
| `#UI.00000003.NOMCPPY` | Devenv venv python missing for sandboxed MCP | `uv sync` so `.devenv/state/venv/bin/python` exists |
| `#UI.00000004.BRANDPACK` | Logo pack missing or custom slot empty | Upload a Weathership-shaped `.tgz` on `/settings` |
| `#UI.00000005.BRANDTGZ` | Brand archive invalid or too large | Flat `logo.svg`+`favicon.svg` or `logo/lockup/lockup-mono-white.svg` |
| `#UI.00000006.BRANDSAVE` | Could not persist `GAIUS_UI_CONFIG` | Check write access to `build/dev/.gaius-ui.json` |
| `#UI.00000007.BADARTIFACT` | Ask artifact missing type/fields | `type` is `ohlc`/`markdown`/`table`; ohlc bars need `t,o,h,l,c` |
| `#UI.00000008.NOBARS` | ohlc artifact has no bars | Pass FMP `symbol` to `gaius__ask_present` or a non-empty `bars` array |
| `#UI.00000009.ASKBACKEND` | Settings Ask backend not `clt-pair` or `sae-9b` | Choose 2×1.7B+CLT or 1×9B+SAE |

### KB — Knowledge base board

| Code | Description | Fix |
|------|-------------|-----|
| `#KB.00000001.NOROOT` | Configured KB root directory is missing | Create `build/dev` or set `kb.root` |
| `#KB.00000002.UMAPLIVE` | Refused to overwrite a live UMAP `current_state` with topology | `/reindex` to refresh embeddings; do not publish `kb_topology` over it |

### SDG — Signals Data Governance (local corpora + strategy)

| Code | Description | Fix |
|------|-------------|-----|
| `#SDG.00000001.NOCORPORA` | `external/sdg-corpora` vocabulary missing | `git submodule update --init external/sdg-corpora` |
| `#SDG.00000002.UNKCODE` | Attention token not in corpora SKOS and not in strategy aiming C | Check `annotations.csv` / `aperture.snapshot.json`; do not invent codes |
| `#SDG.00000003.NOSTRATEGY` | `external/sdg-strategy` aperture spec missing | `git submodule update --init external/sdg-strategy` |
| `#SDG.00000005.NOMAXSIM` | `sdg_aperture` not in Qdrant; CLT SKOS ingest will not admit-all | Load the aiming collection or pass a MaxSim callback |
| `#CLT.00000010.OFFMISMATCH` | CLT token position outside offset_mapping | Extract and ground with the same tokenizer |
| `#CLT.00000011.ACPJSON` | ACP SKOS alignment reply was not JSON | Re-run `acp_align`; agent must return only the verdict object |
| `#SDG.00000004.NOAPERTURE` | Strategy checkout present but snapshot / registered τ incomplete | Re-sync sdg-strategy from Aegir's published pin |
| `#SDG.00000005.NOENTRY` | `record_attention` on a source_id that was never merged | Merge into the cognition scratchpad first |

### COL — Public collections / gaius.zndx.org

| Code | Description | Fix |
|------|-------------|-----|
| `#COL.00000015.NOINFLOW` | Featured collection empty and no public feed URLs to admit | Confirm `feed_check` writes `content_items.url`; `devenv processes restart gaius-engine` |
| `#COL.00000016.NOENRICH` | Pending cards did not get LuxCore image + local open-weights | RenderCards + thinking; Brave/Cerebras optional |

### HX — object capture

| Code | Description | Fix |
|------|-------------|-----|
| `#HX.00000001.NORUSTFS` | HX cannot reach Signals RustFS; filesystem/MinIO fallback refused | `just signals-ready`; confirm `:9010` `signals-dataproducts`; devenv MinIO is not a warehouse |
| `#HX.00000002.NOPOLARIS` | Polarisfork Iceberg REST `:8181` not reachable | `sudo systemctl start signals-polaris.service` (`signals.target`); not a Gaius process |

### ACF — Article Curation Flow

| Code | Description | Fix |
|------|-------------|-----|
| `#ACF.00000013.NOHINTS` | Empty keywords in article frontmatter | Add keywords/news_queries |

### XB — X Bookmarks

| Code | Description | Fix |
|------|-------------|-----|
| `#XB.00000001.NOTOKEN` | No auth token | Complete OAuth flow |
| `#XB.00000011.NOFOLDER` | Folders API unavailable (403) | Upgrade API tier |

### HL — Health

| Code | Description | Fix |
|------|-------------|-----|
| `#HL.00001.GRPC_DOWN` | gRPC connection down | `just restart-clean` |
| `#HL.00002.GPU_OOM` | GPU memory exhausted | `just gpu-cleanup` |

> **Note**: This is a representative subset. Guru codes are assigned as new failure modes are identified. See `CLAUDE.md` for the full format specification.
