# gaius.inference eliminated — zero in-process inference outside the engine

Session log, 2026-08-30 (evening). Continues the same-day go-around
elimination (`9e034d7`, `303cc0b`) and the dual-constraint design note
(`180500_optillm-dual-constraint-capability.md`).

Directive: *"eliminate the legacy gaius.inference package all together. Every
aspect of that implementation must live in the engine going forward so zero
in-process inference remains in Gaius. We're all in on gRPC and
signals-protocol going forward."*

## Commits

| Commit | What |
|--------|------|
| `f445abe` | Engine scheduler surface: instantiate the (previously never-constructed) `engine/services/scheduler_service.SchedulerService` at startup; real `SubmitJob`/`GetJobResult` (were TODO stubs); `SchedulerStatus.metrics_json` (additive proto field); real `XAIBudget`; `SchedulerProxy.submit_job()` submit+poll helper; `get_metrics()`/`evaluate()` fixed (both dispatched to actions that never existed) |
| `308de3e` | The elimination: 27 modules / ~10k LOC removed; 72 files changed, +370 / −6268 |

## Where everything went

| Was (gaius.inference.*) | Now |
|---|---|
| `search/` (brave, bm25, vector, vector_multi) | `gaius.search` (+ `get_search()` facade; key = `BRAVE_API_KEY` env → `providers.brave.api_key`) |
| `search/colqwen.py`, `search/colbert.py` | `gaius.engine.embeddings` (GPU forward passes are engine-side) |
| `engine_client.py` | `gaius.client.engine_client` (+ `Message`, + fixed `ask_local`) |
| `manager.py` | `gaius.client.inference_manager` |
| `parallel.py` | `gaius.client.parallel` (now uses `OrchestratorProxy`) |
| `health.py` | `gaius.observability.gpu_health` (pynvml = observability, not inference) |
| `synthesis.py` | `gaius.core.synthesis` |
| `evaluation.py` | `gaius.engine.backends.external.evaluation` (external judge lanes live with the engine's external backends) |
| `llm.py` prompt builders | `gaius.engine.services.explain_prompts` |
| `scheduler.py` (client-side job queue) | **deleted** — engine queue via `SchedulerProxy.submit_job` / `Scheduler` gRPC actions |
| `router.py`, `client.py`, `config.py`, `orchestrator.py`, `persistence.py`, `recovery.py`, `routing_analytics.py`, `parallel_synthesis.py` | **deleted** (duplicated engine logic / dead) |

Consumer rewires: MCP `scheduler_submit`/`_async`/`get_result`/`metrics`/
`health_check`; CLI `/scheduler`, `/submit`, `/technique`, `/eval`,
`/research!`, `/eval-stats`, `/gpu health`; TUI `_start_scheduler` → no-op;
evolution `DailyEvaluator`, `orchestrated` (consult + status), `daemon`,
`curriculum`, `daemon_oracle`; `topics/scoring`; `nifi_som` dataset judges →
`Engine/Complete` with `agent="xai"` (backend_router routes external aliases);
`core/minigrids` explain → sync lattice Complete with an event-loop guard;
engine reverse-imports (servicer explain, cognition_logic, collection_service,
vector_search_service, clt_skos_aperture, colpali) all repointed.

## Latent bugs found and fixed en route

1. **`ask_local` always returned ""** — dispatched `service="scheduler"`
   (unknown service, `ValueError`) and read a `content` key the proto never
   returns (`CompleteResponse.text`). A test (`test_inference_migration.py`)
   asserted the lowercase bug; deleted.
2. **`ZettelkastenSynthesizer` saved empty notes** — same `content`-vs-`text`
   key bug on the gRPC response.
3. **`ParallelInferenceClient.start()` always raised** — called the
   deprecated `get_orchestrator()` shim, which unconditionally raises; the
   evolution daemon's parallel startup was broken. Now `OrchestratorProxy`.
4. **`SchedulerProxy.get_metrics`/`evaluate` dispatched to nonexistent
   actions** ("metrics", "evaluate" were never in `_call_scheduler`).
5. **Engine `SchedulerService` was dead code** — fully implemented, never
   instantiated; the gRPC job-queue surface was stubbed. Now wired + started.

Legitimate "inference" names kept: HOCON namespace
`gaius.inference.backends.*`, OTel metric names `gaius.inference.*`, YK
queues `internal.inference.*`.

## Verification

- Compile: `compileall` clean over src/tests/features/scripts.
- Import matrix: 36 rewired modules + heavy entries (`gaius.app`,
  `gaius.mcp_server`, `gaius.engine.server`) all import.
- Real restart (`systemctl restart gaius.service`, per
  restart-testing-validation-discipline) onto the new code:
  - `/scheduler status` → full `metrics_json` (engine scheduler `running:
    true`, queue depth, real XAI budget 50/200, backend-router state).
  - `/scheduler metrics` → parsed engine metrics via the new field.
  - `/technique` → engine `OptillmTechnique` enum.
- `/submit` E2E through the engine queue (after thinking finished its
  post-restart load): `job-1` → `completed`, content "Paris", 3.3s,
  `endpoint: grpc_engine`; engine metrics then showed
  `total_jobs_completed: 1` with per-agent `thinking` recorded — the full
  CLI → SchedulerProxy.submit_job → SubmitJob → engine SchedulerService →
  backend_router → vLLM → GetJobResult chain. optillm self-recovered to
  `healthy` once :8081 served.
- Follow-up fix found by the E2E: `/scheduler health` (CLI + MCP) compared
  endpoint status to `"healthy"` but the orchestrator returns proto enum
  strings (`PROCESS_STATUS_HEALTHY`); normalized to accept both.

Note: the MCP server process picks up the rewired `scheduler_*` tools on its
next restart; the parallel Signals-session remediation is expected to bounce
systems anyway.

## Related
- Memory: `gaius-inference-eliminated` (module map + bug symptoms),
  `engine-first-no-bypass`.
- Next (deferred): dual-constraint `capabilities=[method, model]` per the
  design note — the engine now being the only inference surface is its
  prerequisite, done.
