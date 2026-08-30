# Dual-constraint capabilities implemented — method × model over the signals-protocol

Session log, 2026-08-30 (late evening). Implements the same-day design note
(`180500_optillm-dual-constraint-capability.md`, phases 1–4). Ran in parallel
with the Signals-session schema remediation (disjoint surfaces; engine
restarts tolerated by design).

## What landed

| Commit | Repo | What |
|--------|------|------|
| `aeb8f6e` | signals-protocol (submodule, trunk) | `CompleteRequest.capabilities[12]`, `ReasoningLayer` + `CompleteResponse.reasoning[9]`/`fulfilled_by[10]`, `WorkloadOffer.methods[7]` (all additive v1); `specification/protocol/capabilities.md` (vocabulary companion) + `engine_grpc.md` Complete extension |
| `7bf804e` | gaius | Planner, engine-native fulfilment, optillm honesty, servicer/lattice/article-curate/hx wiring, 33 new tests, gitlink bump |

## The shape

- `Engine/Complete(capabilities=["cot_reasoning","thinking"])` — ≤1 method
  capability (optillm technique class) + ≤1 model capability. The engine
  plans the pair (`gaius/engine/capabilities.py`, pure/unit-tested) or fails
  fast `FAILED_PRECONDITION` **`#EP.00000020.NOMIX`** listing offered
  models × methods (`#EP.00000019` was already WEDGED — shifted).
- **Engine-native single-call fulfilment** (cot_reflection): the engine
  applies the byte-faithful optillm scaffold itself over the vLLM path —
  capturing BOTH layers: `ReasoningLayer(layer="model")` = the model's native
  `reasoning_content` (which the optillm proxy hop structurally drops) and
  `layer="method"` = the verbatim `<thinking>…</thinking>` block.
  `fulfilled_by = "cot_reflection@engine/Qwen/Qwen3.8-27B@vllm:8081"`.
- **optillm-composed methods** (bon, moa, …) return the method layer only and
  log **`#EP.00000021.METHODTRACE`** — honest, never fabricated.
- `WorkloadOffer.methods` advertises `SERVABLE_METHODS` — the intersection of
  the gaius enum and the INSTALLED optillm's `known_approaches`. En route this
  exposed a real bug: enum `PV="pv"` was unservable (upstream is `pvg`), so
  the `validator` agent's technique had been silently degrading to
  passthrough. Fixed (`pv`→`pvg`); `cot` remains excluded.
- **optillm passthrough honesty** (standing bugs fixed): `OptillmResponse`
  now forwards `reasoning_content` + `finish_reason` — truncated optillm
  answers used to report `stop`, so `#EP.00000017.TRUNCATED` could never
  fire on that path. The silent unknown-technique → NONE degrade is now
  fail-fast for planned requests (legacy callers keep the lenient path).
- v1 restriction: a method capability is one-shot text — combining with
  `tools_json`/`json_schema`/`messages_json` is `INVALID_ARGUMENT`. Method
  requests inherit optillm's defaults (0.6 / 4096) when unset.
- Clients: `lattice.complete(capabilities=[...])`; pre-flight checks the
  MODEL capability only; `LatticeComplete.reasoning`/`fulfilled_by`; the
  wrong-model guard tolerates technique-prefixed serving names.
- Consumer cutover: `ArticleCurationFlow.select_article` moved off the
  internal `model="leader"` alias (whose response has no reasoning field at
  all) onto the zndx dual-constraint Complete; retains tagged
  `reasoning_layers` (new `hx.cot_reasoning` column, field id 22, additive
  evolve) alongside `reasoning_trace`/`fulfilled_by`.

## Validation

- Unit: 33 new tests (planner 20, router 7, servicer 6); full engine sweep
  80/80 (also repaired the pre-existing stale `test_s2s` workload assertions).
- Live, on a real `systemctl restart gaius.service`:
  - `ServerQuery(WORKLOADS)` → optillm offer `methods=[cot_reflection, bon,
    moa, pvg, re2, self_consistency, rstar, plansearch]`; model offers none.
  - NOMIX negative `["cot_reasoning","sae"]` → FAILED_PRECONDITION with the
    offered sets (sae intentionally undeclared).
  - Legacy `capability="thinking"` byte-compatible (no layers, no
    fulfilled_by) — Kumo/waterfall safe.
  - **Dual-cap engine-native**: `fulfilled_by=cot_reflection@engine/…`,
    model layer 1628 chars (native trace) + method layer 353 chars
    (scaffold), model-first. Scaffold emission is stochastic on trivial
    prompts (same as upstream optillm's fallback) — the smoke retries; long
    production prompts comply reliably.
  - `bon` via optillm: `fulfilled_by=bon@optillm/…`, no fabricated model
    layer, METHODTRACE logged.
- **article-curate E2E (run 1729, production prompt)**: `select_article`
  fulfilled engine-natively; `hx.cot_reasoning` row carries
  `reasoning_layers` = [model: 17,030 chars (the native Qwen trace that was
  structurally unreachable on the old internal path), method: 1,710 chars
  scaffold], 18,798 trace chars total, subject `cyber-physical-systems`,
  technique `cot_reflection`, 5,244 output tokens.

## Out of scope (unchanged)
- Pushing signals-protocol (now [ahead 3]) + peer pin bumps — user
  coordination; Signals-side federated planner (phase 5); declaring
  `sae`/`clt`/`vision` model capabilities; model layer for multi-call
  methods (needs upstream optillm passthrough).
