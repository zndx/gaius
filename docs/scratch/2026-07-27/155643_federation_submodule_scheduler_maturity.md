# Federation step 1a: signals-protocol submodule + YuniKorn scheduler maturity assessment

**Date:** 2026-07-27
**Context:** Follow-up to `docs/notes/2026-07-23/225628_signals_federation_protocol_extension.md`.
Aegir and Atelier both register `zndx.engine.v1.Engine` and share the advisory GPU lease dir
`/tmp/zndx-gpu-leases` (aegir primary currently leases GPUs 0–3). Gaius was "planned" on both.
RH direction this session: add the submodule; assess whether Gaius's YuniKorn-style scheduler
is the more mature foundation for cross-project GPU arbitration than the siblings' filelock.

## Done

- Added `external/signals-protocol` submodule (git@github.com:zndx/signals-protocol.git),
  pinned at `4433547` — identical to the commit aegir/atelier vendor. Remaining step-1 items
  (generate `zndx/engine/v1` bindings, `GaiusZndxEngineServicer`, lease adoption) not started.

## Scheduler maturity assessment

The engine's "YuniKorn-style" workload management is a full vertical slice, not a sketch:

- **Declarative workloads** (`engine/workloads.py`): `WorkloadRequest` declares capabilities +
  priority + duration/memory estimates (YuniKorn "applications"), never endpoints.
- **CP-SAT makespan solver** (`engine/scheduling/makespan_scheduler.py`, 466 lines): OR-Tools
  interval/boolean model — GPU assignment, TP contiguity constraints, eviction/start precedence,
  empirical load/unload times, minimize makespan. 27 unit tests.
- **Preemption rules** (`orchestrator_service.py:1419`): priority ordering, never evict
  in-flight, prefer idle; baseline set-point restore after transient workloads.
- **Full gRPC surface**: `BeginWorkload`/`CompleteWorkload`/`GetActiveWorkloads` +
  `PhaseChange` convergence RPCs; client proxy; used by flow runner, cloudera_docs, LuxCore
  render pipeline (the memory-eviction path is production-exercised as of 2026-02-24).
- **Health integration**: `AgendaTracker` suppresses incidents during planned transitions.

### Maturity limits found

1. **ortools not installed in the current venv** — `ORTOOLS_AVAILABLE=False`, so the CP-SAT
   capability path returns `#SCH.00000001.NOORDEPS` and 27/44 scheduler tests skip. Only the
   raw-memory eviction path is live. Fix: `uv sync --extra scheduler` (or `--extra orchestrator`).
2. **Dated**: solver last touched 2026-01-12; workload section 2026-02-24. Predates the triad.
3. **Single-tenant worldview**: the resource manager assumes all 6 GPUs belong to Gaius.
   `MakespanScheduler(reserved_gpus=…)` exists but is static config, not lease-aware.
4. **Cleanup paths are hostile to co-tenants (ACTIVE HAZARD)**:
   - `scripts/lib/gpu-helpers.sh gpu_cleanup()` kills **every** PID from
     `nvidia-smi --query-compute-apps` — run by gaius-engine startup and `just restart-clean`.
     With aegir holding GPUs 0–3 today, a restart-clean kills aegir's vLLM.
   - `orchestrator_service.cleanup_stale_processes()` kills any untracked GPU PID >100 MB
     whose cmdline matches vllm/torch/cuda/python — sibling engines all qualify.

### Verdict

More advanced than the siblings' `gpu_guard` in *mechanism* (real scheduler: declarative
workloads, priority preemption, optimal transition planning vs. advisory mutual exclusion),
but less mature in *co-tenancy*: gaius neither reads nor writes leases, and its cleanup
actively destroys co-tenants. The two compose naturally:

1. **Lease-aware resource manager**: read `/tmp/zndx-gpu-leases` → feed foreign-held GPU sets
   into `reserved_gpus` (solver + resource manager); write gaius's own lease for GPUs it starts
   endpoints on. This is the "point the guard at the shared dir" step from the July note,
   except gaius's "guard" is the orchestrator itself.
2. **Cleanup exemption**: both cleanup paths must exempt PIDs owned by live lease holders
   (owner.json carries pid + project) — kill only *unleased* orphans.
3. **Later (federation proper)**: expose `BeginWorkload` on the v1 face so siblings can request
   GPU windows from gaius's solver — YuniKorn-style central arbitration for the shared box,
   which the advisory-lock layer can't do (it can only refuse, not plan).

## Addendum (same session): ortools closed; YK-on-K8s design not found

**ortools**: RH recalled trying to make ortools always-available via devenv. History shows it
was only ever the optional `scheduler` extra (e4f62be, 2025-12-03) — never in default deps or
devenv.nix, and devenv ran plain `uv sync` (no extras), so the venv never had it. Fixed:
`languages.python.uv.sync.extras = [ "scheduler" ]` in devenv.nix + immediate install.
All 44 scheduler tests now pass (was 17 passed / 27 skipped). Note: lock pins ortools 9.10.4067;
the manual install put 9.15 in the venv — next devenv sync converges to the locked version.

**Actual-YuniKorn-on-RKE2 mode** (YK deployed to local RKE2, "placeholder" pods for engine
workloads, engine telemetry → K8s apps, YK/K8s dashboards as single pane of glass across the
triad, YK doing the arbitration): searched gaius (src/docs/infra/KB), aegir, atelier, objsrv,
cldr/signals — **not written down anywhere**. Closest artifacts:
- cldr/signals `infra/aws/ansible/roles/dask/defaults/main.yml`: optional YuniKorn 1.5.0
  deployment for Dask (`dask_enable_yunikorn: false`) — real YK tooling, but AWS/Dask, not RKE2.
- Gaius KB vendors Cloudera CDP docs referencing YK (CDP embeds it) — likely seeded the idea.
- "Placeholder" is genuine YK terminology (gang-scheduling placeholder pods via taskGroups),
  so the remembered design maps cleanly onto real YK features; it just never got captured.
The substrate all exists: RKE2 up with Tilt/Metaflow, engine OTel telemetry, YK hierarchical
queues would give per-project quotas/fairness/preemption + web UI out of the box. Needs a
design note if we pursue it — shadow/placeholder pods representing engine workloads, with
BeginWorkload gating on YK admission, would subsume the advisory-lease layer entirely.

**Cleanup co-tenancy hazard FIXED** (same session, before restart): all gaius kill paths
are now lease-aware — they spare any process that is a live `/tmp/zndx-gpu-leases` holder
or its descendant. `gpu-helpers.sh` gained `_kill_unleased` (used by engine startup,
`just gpu-cleanup`, and a rebuilt `gpu-deep-cleanup`); `engine/resources/gpu_leases.py`
is the Python twin guarding `cleanup_stale_processes()` (the autonomous health path).
Verified live with aegir's supervisor leasing GPUs 0–3: survived both cleanup runs.
Also fixed a latent `set -euo pipefail` abort in gpu-deep-cleanup when GPUs are empty.
Note: gaius still doesn't *write* its own lease — that's the remaining half of mutual
co-tenancy (sibling guards can't see gaius endpoints except via nvidia-smi probe).

## Next steps

- [x] ortools always available (devenv sync extra) — 44/44 CP-SAT tests pass
- [x] Cleanup paths lease-aware (spare siblings) — shell + Python, tested live
- [ ] Generate v1 bindings + `GaiusZndxEngineServicer` (note §2)
- [ ] Lease-aware `reserved_gpus` + cleanup exemptions (items 1–2 above) — **do before the
      next restart-clean while siblings are active**
- [ ] Propose `BeginWorkload`-over-v1 to the triad as the arbitration evolution
