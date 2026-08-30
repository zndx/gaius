# optillm as a dual-constraint capability over the signals-protocol

Design note, 2026-08-30. Status: **proposal** (not implemented). Owner: gaius engine +
signals-protocol.

## The finding that motivates it

Retaining article-curation's reasoning traces as the `gaius.curation.cot_reasoning`
data product exposed a structural gap: today optillm is reached by an alias hack
(`model="leader"` → optillm `cot_reflection-<model>`), the *technique* lives outside
the protocol, and the engine composes optillm → vLLM opaquely. Consequences seen
this session:

- optillm returned only `<output>` (its `<thinking>/<reflection>` scaffold stripped)
  until a server-level flag was set; vLLM's separated **native** `reasoning_content`
  (Qwen3.8's 10–15k-token `<think>` block — the richest trace) **never passes through
  optillm at all**. The corpus captured 0 chars of reasoning until patched, and still
  loses the native trace.
- The tempting workaround — call thinking directly with a cot_reflection prompt to get
  `reasoning_content` — **goes around optillm to avoid the engine**. That is not
  possible in a real distributed Signals deployment: a federated engine can only ask
  the protocol for capabilities; it cannot reach a peer's optillm or vLLM.

So the fix is not a bypass. optillm must be provided **through the gRPC engine as a
dual-constraint capability**: a request names a *method* capability and a *model*
capability together, and the engine fulfils the pair (or fails fast).

### The rule, both directions (Engine-First)

- **Never go around optillm to reach a model** (e.g. calling thinking directly to
  recover `reasoning_content`): the method layer is part of the capability.
- **Never go around gRPC or the engine to reach optillm**: optillm's HTTP `:8000`
  is engine-internal plumbing, not a service surface. In a real distributed
  Signals deployment neither shortcut exists — a federated engine has only
  `Engine/Complete`.

Known go-around surface to retire (surveyed 2026-08-30; folded into Phase 4):

| Path | Nature |
|------|--------|
| `workers/triage.py:58,68` | worker defaults to `http://localhost:8000` (`OPTILLM_URL`) — direct optillm consumption |
| `inference/scheduler.py:645`, `inference/config.py:203` | legacy client scheduler with `GAIUS_OPTILLM_URL` — direct consumption |
| `cli.py` / `inference/*` `technique="cot_reflection"` call sites | route via the legacy client, not `Engine/Complete` |
| `health/checker.py` `_check_optillm` / port-audit probes | **observability, keep** — probing is not consuming (the checks themselves say "DEV FALLBACK … use gRPC for production") |

## Proposal

### 1. Protocol: multi-capability Complete (additive v1)

```proto
message CompleteRequest {
  string capability = 1;                 // legacy single capability (kept)
  // NEW: a capability SET the engine must satisfy TOGETHER, e.g.
  //   ["cot_reasoning", "thinking"]  — cot_reflection over Qwen3.8-27B
  //   ["cot_reasoning", "sae"]       — cot_reflection over the SAE-instrumented model
  //   ["bon", "thinking"], ["plansearch", "complete"], …
  // Method capabilities name an optillm technique class; model capabilities name a
  // served model class. Empty = legacy `capability`.
  repeated string capabilities = 12;
}

message CompleteResponse {
  // NEW: every reasoning layer the fulfilment produced, in order —
  // native model reasoning (vLLM reasoning_content) AND the method's scaffold
  // (cot_reflection <thinking>/<reflection>), each tagged by layer.
  repeated ReasoningLayer reasoning = 9;
  string fulfilled_by = 10;             // "cot_reflection@optillm/Qwen3.8-27B@vllm:8081"
}
message ReasoningLayer { string layer = 1; /* model | method */ string producer = 2; string text = 3; int32 tokens = 4; }
```

Capability vocabulary (`specification/protocol/capabilities.md`, new): **model**
capabilities (`thinking`, `complete`, `sae`, `vision`, `embed`, `clt`) and **method**
capabilities (`cot_reasoning`, `reflection`, `bon`, `plansearch`, `moa`, `mcts`, …
= optillm techniques). A request is a conjunction; the engine's fulfilment is a plan.

### 2. Advertisement: what a peer can fulfil

`ServerQuery(kind=WORKLOADS)` already returns `WorkloadOffer.capabilities` for models.
Add method offers so a federated planner can check the mix:

```proto
message WorkloadOffer { …; repeated string methods = 7; }   // optillm techniques this peer serves
```
(or a `SERVER_QUERY_KIND_METHODS`). Signals' federated view then knows, per peer, the
models × methods it can compose — "does the available mix of optillm methods and
deployable models satisfy `[cot_reasoning, sae]`?" becomes answerable before routing.

### 3. Engine: a fulfilment planner, optillm as an internal method layer

- `CapabilityPlan = resolve(capabilities)` → `(method, model_alias, endpoint)`; the
  model constraint selects/ensures the vLLM (existing `ensure_endpoint`), the method
  constraint selects the optillm technique (existing `OptillmTechnique`) — or none.
- Fulfilment runs optillm→vLLM **inside the engine's composition**, and the engine
  **collects both traces**: the model's `reasoning_content` (ask vLLM with the
  reasoning parser; optillm must forward it — either optillm's proxy passes
  `reasoning_content` through, or the engine issues the underlying vLLM call itself
  with the technique's prompt scaffold when the technique is a single-call one like
  cot_reflection) and the method scaffold. Both land in `CompleteResponse.reasoning`.
- Fail fast when the mix is unavailable: `#EP.00000019.NOMIX` with the offered
  models × methods in the message.
- Guru: `#EP.00000020.METHODTRACE` when a method drops the model trace.

### 4. Consumers

- article-curate `select_article`: `capabilities=["cot_reasoning","thinking"]`,
  retains `response.reasoning` (both layers) into `hx.cot_reasoning`
  (`reasoning_trace` = concatenated layers with tags; `raw_response` unchanged).
- Any federated engine (Signals, aegir, atelier) requests the same pair over
  `Engine/Complete` — no knowledge of optillm/vLLM topology required.

## Phasing

1. Protocol: `capabilities[]`, `ReasoningLayer`, `WorkloadOffer.methods` (+ spec).
2. Engine: planner + method-offer advertisement; keep `model="leader"` as an alias
   that resolves to `["cot_reasoning","thinking"]` for back-compat.
3. Trace capture: forward/collect `reasoning_content` alongside the scaffold.
4. Cut article-curate over; then Ask/Terminal consumers as they need methods.
   Retire the go-around surface: `workers/triage.py` direct `:8000`, the legacy
   `gaius.inference` scheduler/config `GAIUS_OPTILLM_URL` consumption paths — all
   optillm consumption moves behind `Engine/Complete` (health probes stay).
5. Signals federated planner: satisfy multi-capability requests across peers.

## Related
- `docs/scratch/2026-08-30/021057_engine-liveness-self-heal.md` (the session that
  surfaced this: optillm full-response, max_tokens, HX `hx.cot_reasoning`).
- Memory: reasoning traces are the product (never "lighten" a reasoning step).
