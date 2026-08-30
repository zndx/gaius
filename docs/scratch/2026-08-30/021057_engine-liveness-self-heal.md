# Engine liveness / process-status-desync self-healing (L0–L2)

Remediation for the 2026-08-29 class: engine dead / `:50051` dark while
process-compose reports "ready", nothing self-heals. Design = an SRE recovery
ladder (L0/L1/L2) deliberately decoupled from FMEA scoring; ACP is a continuous
first-class capability, not a gated last resort.

## Implemented (all on `trunk`, uncommitted — awaiting review)

**L0 — deterministic out-of-band restart (the reliable primary)**
- `scripts/engine-ready.sh` (new) + `scripts/systemd/gaius-engine-ready.service` (new):
  continuous out-of-band watchdog, `PartOf=/WantedBy=gaius.service`. Polls a cheap
  raw-gRPC Status probe; on **sustained `:50051` DEAD** (rc=2, UNAVAILABLE) does a
  complete `systemctl restart gaius.service`, bounded by a persistent, time-windowed
  recycle-budget ledger (`/var/lib/gaius/engine-recycles`) = the crash-loop breaker.
  On budget exhaustion drops `/var/lib/gaius/engine-breaker-tripped` (guru
  `#EN.00000017.SERVEDESYNC`) → hands to L2. Honors the crash-guard `defer-gpu` marker.
- `devenv.nix`: `availability.restart = "on_failure"` (+backoff/max_restarts) on
  `gaius-engine` — fast in-place relaunch on clean crash. **Validated: accepted by
  the native manager, no restart-thrash.**
- `scripts/engine_serving_probe.py` (new): cheap probe (~0.16s, `import grpc` only).
  Replaces `zndx_status_ok.py` for polling — that script drags in the whole engine
  via `engine_pb2_grpc.py:6`'s `from gaius.engine.generated...` (~11s CPU / 885 MB
  RSS **per call**; also burdens the readiness_probe every 10s — a pre-existing bug).
  Distinguishes **rc=2 dead (UNAVAILABLE → recycle)** from **rc=3 slow (DEADLINE →
  alive, do NOT recycle)** — essential because the engine's Status is bimodal
  (~0.15s but 20s+ spikes); a flat timeout would false-recycle a healthy-but-busy
  engine. **Validated live.**
- `just reboot-hardening-install` — reproducible install/enable of the hardening units.

**L1 — first-class incident + honest FMEA + the `/health fix engine` bug**
- `checker.py`: `engine_serving` check (reads the breaker marker) for `/health`.
- `db/migrations/20260830000001_*.sql`: `INFRA_005` "Engine Serving Desync", PFMEA,
  **honest** S9/O3/D5 (RPN 135; well-calibrated vs INFRA_002 S9/O3/D2). Applied to DB.
- `fmea/registry.py` + `fmea/loader.py`: `engine_serving → INFRA_005`.
- **Fixed `/health fix engine`** (CLI + TUI): was "Unknown service: engine" despite
  being advertised by `_health_diagnose`. Now recycles via `EngineFixStrategy`
  (`systemctl restart gaius.service`, no pid-kill). **Validated (dry-run).**
- `guru-codes.md`: `#EN.00000017.SERVEDESYNC`. KB heuristic `engine/serving_desync.md`.

**L2 — continuous agent (ACP), decoupled from FMEA tier**
- `health_observer_service.py`: `_check_engine_serving` (in-engine, reads the breaker
  marker — the autonomous handoff, fires ONLY on recovery-exhausted recurrence);
  `_attempt_remediation` routes INFRA_005 straight to ACP (driven by "deterministic
  recovery exhausted", **not** the RPN tier — the honest decouple); a specialized
  `_build_engine_serving_acp_prompt` carrying breaker context + known-cause
  hypotheses (uv-run churn / GPU-thinking load / process-compose desync) + a
  meta-maintenance directive (enrich the heuristic + tooling on `acp/health-fix`).

## Validation
- Isolation: all modules compile/import; `read_engine_breaker` (absent/fresh/stale/
  malformed); probe exit codes (0/2/3); ACP prompt render. All pass.
- Live watchdog: healthy poll silent + cheap (0.29s/2 polls); dark-path counts;
  **correctly treats slow Status as alive (no false recycle)**.
- Real restarts BOTH planes (systemctl + `just restart-clean`): engine loads the new
  code, 18-min stable single instance, `availability.restart` no thrash.
- **Deferred** (need a healthy engine — ACP needs thinking): breaker→INFRA_005→ACP
  E2E; L0 kill→recovery chaos; the both-scopes `signals.target` matrix.

## Incident surfaced (independent of this code)
The validation restarts exposed a **pre-existing restart-fragility**: the thinking
27B / vLLM endpoints **do not reload** — all 6 GPUs stay at 4 MiB, no vLLM process,
no launch attempt or error in the log, no defer marker, crash-guard clean — across
BOTH a systemctl restart and `just restart-clean`. The orchestrator is wedged
(`/gpu status` hangs; Status intermittently 25s). This is an endpoint/orchestrator/
GPU-admission issue (cf. yunikorn/k8s gaps in prior notes), NOT the engine-liveness
class: `:50051` serves, so the new watchdog **correctly does not recycle** (it acts
only on a DEAD port). Needs operational investigation / owner context.

## RESOLVED — the wedge was a clobbered venv package (2026-08-30)

Root cause dug out: **`nvidia-nvshmem-cu12` 3.4.5 was clobbered** — 12/12 `.so`
missing (dist-info intact), so `import torch` failed (`ImportError:
libnvshmem_host.so.3`), every `vllm serve` died, and the orchestrator retry-looped
(→ Status 25s spikes, `/gpu status` hung, GPUs empty). NOT caused by this code
(dormant) — a pre-existing clobber ([[gaius-venv-cuda13-clobber-repair]]) that the
restart surfaced. Fix: `uv pip install --reinstall --no-deps
nvidia-nvshmem-cu12==3.4.5` (1 pkg, safe under the live engine). Result: torch.cuda
True/6, 27B loaded (GPUs 0-3 → 21 GB), Status back to ~0.15s, no engine restart
needed. The `M uv.lock` cu13-exclusion is the correct durable guard — keep it.

## Chaos E2E — BOTH PASSED (2026-08-30, on the recovered engine)

- **L2 autonomous handoff (breaker → INFRA_005 → ACP):** injected a synthetic
  breaker marker; the observer created `INFRA_005:engine` **1 s later**. The
  healing-event trail proves the routing: `sequence_started(0) →
  attempt_started(tier 2) → attempt_failed(2) → tier_entered(3) →
  attempt_started(3)`. FMEA scored it honestly (S9/O3/D4, RPN 108). My tier-2 guard
  worked. ACP itself couldn't connect — **`grok` CLI not on the engine's PATH**
  (`#ACP.00000012.AGENTMISSING`) — so it sequential-escalated to tier 3 / GitHub
  issue (existing fallback). Cleaned up (marker removed, issue #67 closed,
  sequence terminated).
- **L0 kill → recovery:** `kill -9` the engine → **`availability.restart`
  relaunched it out-of-band in ~20 s** (new PID, `:50051` back); the watchdog
  logged the slow reload as `rc=3 (alive, not recycling)` and did **not** recycle
  (recovery beat the 300 s sustain); thinking reloaded to 21 GB/GPU (nvshmem fix
  held across the crash).

## Discovered gaps (adjacent, worth fixing)

1. **ACP is non-functional due to a PATH gap** (HIGH): every escalation fails
   `#ACP.00000012.AGENTMISSING` because `grok` (`~/.local/bin/grok`) isn't on the
   engine's PATH → self-heal always falls to GitHub issues, never the agent. Fix:
   `GAIUS_GROK_BIN=/home/rch/.local/bin/grok` (or add `~/.local/bin` to the engine
   env). This makes the premier ACP capability actually run.
2. **`gaius-thinking-ready` is boot-only** — doesn't re-fire on a manual/devenv
   restart, so a thinking-load failure after a manual restart isn't auto-recovered
   (surfaced this incident). Consider making it a continuous/timer watchdog too.

## ACP made live + intent-driven workload watchdog (2026-08-30, later)

**ACP was non-functional (grok not on the engine PATH).** `_grok_bin()` only did
`shutil.which("grok")` and ignored `GAIUS_GROK_BIN` despite the error hint. Fix:
`.env` sets `GAIUS_GROK_BIN=/home/rch/.local/bin/grok` (sourced by gaius-engine.sh),
surfaced via `acp.conf` `grok_bin = ${?GAIUS_GROK_BIN}`, and `_grok_bin()` now reads
config→env→PATH (`acp/client.py`, shared `_parse_acp_conf`). Verified: engine env has
it, `_grok_bin()` resolves it → ACP escalations reach grok instead of
`#ACP.00000012.AGENTMISSING`. **The premier self-heal capability is live.**

**thinking-ready rebuilt as an INTENT-DRIVEN watchdog (user redirect).** The
GPU-idle heuristic was replaced: it guessed intent and false-positives (thinking is
legitimately down during a viz eviction, "idle" mid-load). Instead the engine now
DECLARES intent and the watchdog verifies against it, via a new signals-protocol
stream:
- **signals-protocol (additive v1):** `rpc WatchWorkload(...) returns (stream
  WorkloadProfile)` + `WorkloadProfile{phase(SETTLED|TRANSITIONING), generation,
  intents[], settled_at_ms}` + `WorkloadIntent{capability, alias, model, port,
  gpu_ids, backend, warmup_seconds, actual(WorkloadStatus)}`. Regenerated bindings.
- **Engine:** `services/workload_profile.py` — a versioned intended-profile publisher
  on `OrchestratorService` (`(preload − evicted) ∪ running`, each with actual status
  from ProcessStatus); `@_publishes_transition` brackets `begin_workload`/
  `complete_workload` as TRANSITIONING→SETTLED; `GaiusZndxEngineServicer.WatchWorkload`
  streams it (seed + fanout + 15s heartbeat).
- **Watchdog:** `scripts/workload_watchdog.py` (Python; unit `gaius-thinking-ready`
  repoints to it, `thinking-ready.sh` retired). Consumes the stream; per-intent
  `bad_since` — an intent is a MISS once not-SERVING for its `warmup_seconds`
  (measured from when the WATCHDOG first saw it bad, so the engine gets its full
  grace to self-restore); holds during TRANSITIONING; an evicted intent drops out
  (never a miss); budget-bounded recycle. Guru `#EP.00000018.THINKNOLOAD`,
  `#GR.00000014.NOWORKLOADPROFILE`.

**Prerequisite win (Phase 1):** `gaius/engine/__init__.py` made lazy (PEP 562) —
importing the protobuf stubs no longer drags in `.server`. `engine_pb2`:
6.88 s/885 MB → **0.16 s/36 MB**; the readiness probe (every 10 s) and
`zndx_status_ok.py`: ~7 s/885 MB → **0.21 s** (also fixes its silent 5 s-timeout
flakiness).

**Validated live (staged):** engine boots on lazy `__init__`; WatchWorkload streams
`thinking starting→serving` as the 27B loaded and `generation` advanced on real
`begin_workload` changeovers; watchdog healthy-silent against serving thinking;
kill-thinking → detect miss → **recycle → thinking restored** (the full chain fired;
a stale-`settled_at` grace bug found + fixed to per-intent `bad_since`). grok
resolves in-engine.

## Final state (evening)
`:8081` thinking `Qwen3.8-27B` serving · `:50051` ~0.15 s · WatchWorkload streaming ·
engine-ready + workload watchdog (gaius-thinking-ready) + crash-guard active · ACP
grok resolvable. All committed on trunk; signals-protocol proto change is additive v1.

## Morning: article-curate → reasoning corpus as a federated data product

**Overnight failures root-caused (not a YK fault):** a controlled extract sentinel
binds in <1 s. `clt-skos-admit` (`*/15`) holds the ONE spare GPU token (thinking
pins heavy's 4-GPU floor) for ~195 s, and the GPU admit wait was 180 s — so any
extract flow on a `:00/:15/:30/:45` boundary was a guaranteed `#YK.NOTADMITTED`;
the daily 09:00 article-curate collided every night. Fix (`1c69b13`): GPU admit
wait → 600 s (`GAIUS_YK_GPU_ADMIT_TIMEOUT_S`), `article-curate-daily` → 09:07 UTC.

**Reframe (user):** deep CoT+reflection is the PRODUCT, not overhead. Article
selection is the crucible refining an accumulating thinking corpus; sustained
reasoning = sustained GPU utilization, encouraged. The earlier "lighter
technique" suggestion is retracted. Also fixed (`0f1f0e1`): the flow's naive
`first-{…last-}` JSON grab choked on rich reasoning (12k-token trace, correct
selection, `#ACF.BADJSON`) — now scans for the selection object and preserves
the full trace.

**The data product — structure (reviewed against the nascent surface):** the
signals-protocol data-product surface is a *warehouse contract*
(`specification/protocol/data_products.md`): `product_id = {peer}.{domain}.{name}`,
Signals-owned `tx/details/hx_reasoning` inventory (UUIDv7), one shared Polaris
catalog (`signals` @ :8181, `s3://signals-dataproducts/iceberg`) that gaius HX
writes and Signals Impala reads. So:
- Iceberg table **`hx.cot_reasoning`** (`src/gaius/hx/cot_reasoning.py`): one
  physical table for every flow's reasoning, partitioned `flow_name` + month;
  `step_name`, `subject` (article slug), `run_id`, technique, model, prompt,
  `reasoning_trace`, raw_response, output/decision, tokens, YK provenance. The
  path `gaius-content-curation/select_article/hx/cot_reasoning` is a PROJECTION
  (subject/step/table), never a namespace — one product carries every article and
  every run, with Iceberg snapshot history.
- Federated product **`gaius.curation.cot_reasoning`**
  (`flows/article_curation/publish.py`, shared helpers `flows/dataproduct.py`):
  published at flow `end` via `signals.ops.history.review` (mirrors
  `gaius.prospects.corpus`), run-qualified `run.{flow}/{run_id}.*` facts +
  OpenLineage `gaius.hx/hx.cot_reasoning:{id}`.
- `select_article` retains the trace FAIL-FAST (`#HX.00000003.COTWRITE`) — a lost
  trace is a failed run.
- **Discovery over the wire (additive v1):** `ServerQuery(kind=PRODUCTS=9)` →
  `repeated ProductHint products=11` (`s2s.declared_products`); warehouse stays
  the inventory of record.
- **Proven:** table created in Polaris; row written/read/deleted with the engine's
  env; **Signals Impala `SHOW TABLES IN hx → cot_reasoning` + full DESCRIBE with
  zero registration** — the federation path works.

**Incident (self-inflicted, fixed, `3079711`):** the root-run watchdog units wrote
root-owned `__pycache__` into rch's venv → the next flow spawn's `uv run` sync
failed mid-way (31 uninstalled, 67 never reinstalled): torch/protobuf/pyarrow/
pyluxcore missing, thinking down, every flow spawn failing. Repaired via
`uv sync --inexact` + pyluxcore + chown; units now `PYTHONDONTWRITEBYTECODE=1`.
Root cause of the chronic 67-pkg churn found: a leaked `UV_PROJECT_ENVIRONMENT`
makes signals-tree `uv run` sync into the gaius venv (memory updated).
