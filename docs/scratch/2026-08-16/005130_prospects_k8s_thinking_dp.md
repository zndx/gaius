# Prospects rework: K8s Metaflow, thinking-local, Signals Data Product

Gaius owns the flow and the meaning of `gaius.prospects.*`.
Signals owns warehouse + RustFS. Contract:
`signals-protocol` `specification/protocol/data_products.md` (pin after
`git submodule update --remote`). Playbook:
`~/local/src/wxs/signals/docs/current/src/operations/peer-data-products.md`.

## Hard constraints

- No Cerebras, no XAI token-metered API on this path.
- No second Iceberg/Polaris/Kudu. No prospects SoR in Gaius PG `:5444` or pglite.
- Use the **Signals-provided** Metaflow (`:30180` + RustFS). Do not start a
  second Gaius/Tilt Metaflow. Gaius `config/metaflow/k8s.json` is leftover
  Tilt/MinIO — not SoR.
- `METAFLOW_DEFAULT_DATASTORE=s3` → `s3://metaflow/metaflow` on RustFS.
  Fail closed if datastore is `local`.
- YK leaves are resource classes, not `root.gaius`.
- Host GPU occupancy is `federation.zndx.org/gpu` only; thinking TP=4 stays
  on the host. `@kubernetes` is **local RKE2** (same tinybox), not a remote
  farm. Those pods must not `vllm serve` Qwen3.8; they call
  `zndx.engine.v1.Engine/Complete` on the host lattice (`:50051`).
- Peers do not implement `data-product.tier-upkeep`.

## Current vs target

Today: host `FlowSpec` subprocess, 30k-char keyword preprocessor, GLM per
filing, Grok synthesis, sitrep written to KB + PG cache.

Target: Airflow-triggered platform Metaflow with `@kubernetes` on every
step that can leave the host. In-engine `prospects-buffer` (same byte FIFO
as Ambient). `prospects-compact` and `prospects-summary` call local
`thinking`. ACP Overwatch (grok CLI, `grok login --device-auth`) writes
`hx_reasoning` on the product `tx`. Objects on RustFS. Facts in Signals
`details`/`tx`/`hx`.

## Lanes (YK)

| Work | Queue | Where |
|------|--------|--------|
| FMP pull / EDGAR fetch | `root.external.rate-metered` | K8s step |
| Docling extract | `root.internal.inference.extract` | K8s GPU or host extract token |
| ColBERT-Zero window encode + MaxSim | `root.internal.inference.embedding` | host embed (or K8s if the farm is in-cluster) |
| `prospects-compact` / `prospects-summary` | rides standing `thinking` | **RKE2 task** → Engine/Complete; weights stay on host |
| Grok ACP Overwatch | `root.external.subscription.rate-limited` | host ACP, not `/v1/chat` |
| Metaflow metadata / Airflow | `root.platform` | Signals |

`federation.project=gaius` is a label. `app-id` = `federation.workload_id`.

## RKE2 → host engine (lattice gRPC)

`@kubernetes` steps run as pods in this node's RKE2 (`KUBECONFIG=$HOME/.config/kube/rke2.yaml`,
namespace `metaflow`, SA `metaflow-task`). They do **not** share the host
netns. `127.0.0.1:50051` in the pod is not Gaius.

Call path (Signals protocol, not native `GaiusService`, not `:8081`):

```
Metaflow @kubernetes step
  → generated zndx.engine.v1 stub (pin proto, not ad-hoc HTTP)
  → Engine/Complete { capability="thinking", prompt, max_tokens, … }
  → host gaius-engine :50051
  → standing Qwen3.8 TP=4
```

### RKE2 / Service work

Do **not** put `hostNetwork: true` on every Metaflow task (YK placement,
port clashes, same anti-pattern Signals already avoided for Airflow).
Mirror the Airflow host-bridge instead:

1. Engine must listen on a node-reachable address (not only loopback).
   Confirm `gaius-engine` bind is `0.0.0.0:50051` (or add a host-side
   socat if it stays loopback-only).
2. In `metaflow` ns: `Endpoints`/`EndpointSlice` + ClusterIP Service
   `gaius-engine.metaflow.svc` → node InternalIP `:50051` (or a single
   `hostNetwork` socat pod like `signals-postgres-proxy`, then ClusterIP).
3. NetworkPolicy / RKE2 ingress: allow `metaflow` pods → that Service.
   Cilium/RKE2 may need an explicit host-firewall hole for `:50051`
   from the pod CIDR (`iptables`/`nft` + `rke2` cilium policy).
4. Inject `GAIUS_ENGINE_GRPC=gaius-engine.metaflow.svc.cluster.local:50051`
   via Metaflow `@kubernetes(..., secrets=…)` / `METAFLOW_*` env.
   Host-side Airflow trigger still uses `127.0.0.1:50051`.
5. Fail closed if the in-cluster target is unset, `localhost`, or
   `METAFLOW_DEFAULT_DATASTORE=local`.

### Flow-side gRPC (must live in the step)

Today `zndx_engine_servicer.Complete` is not enough for compact/summary
as written:

| Gap | Why it matters |
|-----|----------------|
| Empty `capability` → `cognition` | Compact must send `capability="thinking"` (or Status must advertise thinking and we default to it). |
| `capability` treated as `agent_alias` | Works if we pass `thinking`; do not pass `cognition`. |
| `json_schema` → UNIMPLEMENTED | Filing memos want guided JSON. Either implement it on Complete or return JSON in the prompt and parse (fail-fast). |
| No `enable_thinking` / `reasoning_effort` on the lattice Complete | Compact/summary need thinking-on; extend proto **or** engine default-on when capability is thinking. |
| `reasoning_content` not mapped in the response | Protocol says retain traces; wire them through. |
| Step image | Metaflow K8s image must ship generated `zndx.engine.v1` stubs + grpcio (same pin as the engine). No `curl :8081`. |

A thin `gaius.flows.lattice.complete()` helper (codegen client, env-driven
target, Status probe then Complete) is the only inference API the flow
is allowed to call.

## In-engine twin of Ambient

Reuse `AmbientBuffer` shape (`max_bytes` default 256KiB, FIFO, 90% target).
New roles: `FILING`, `TABLE`, `WINDOW`, `COMPACT`, `SUMMARY`, `FMP`.
Do not share one deque with Ambient — two sources, one *interface*.

| Op | Ambient | Prospects |
|----|---------|-----------|
| ingest | HN Firebase → CONTENT | FMP+EDGAR+docling → FILING/TABLE/FMP |
| compact | research (web prose) | research (SEC + tables); **not** the same algo |
| summary | thinking, effort=low | thinking, effort=low; thesis-shaped |
| GPU pause | skip summarize, keep RAM | same |

Compact is an explicit research surface: a shared protocol
(`CompactRequest` / `CompactResult` with source, windows, tables, memo)
and two strategies. A universal algo is a later claim, not a day-one
implementation.

## Metaflow graph (K8s)

1. `start` — watchlist, platform-profile assert, mint UUIDv7 `tx_id`.
2. `fetch_fmp` — catalog only (filings, profile, 13F). Rate-metered.
3. `sync_edgar` — raw HTML bytes to `s3://signals-dataproducts/gaius/prospects/…`
   (Iceberg raw tables stay Signals-side if we already write via HX client;
   product *facts* point at the URI, not a copy in `:5444`).
4. `extract` — docling. Extract token.
5. **Fan-out (foreach filing), two parallel branches:**
   - `window_scan` — Aegir grain: `token_windows(size=512, stride=256)`
     using the ColBERT-Zero tokenizer (one scheme, no drift). Encode all
     windows in one forward pass. MaxSim against a **prospects aperture**
     in Qdrant (`gaius_prospects_aperture`, ColBERT-Zero 128-d). Greedy
     non-overlap resolve by margin (same as `item_scan`). Output: admitted
     windows + interstitial spans.
   - `table_structure` — plain-text/markdown table detect on the docling
     extract (SEC tables are the semantic payload the 30k preprocessor
     used to drop). Score tables (numeric density, YoY headers, scale
     words). Output: table spans + salience.
6. `join_structure` — merge admitted prose windows with high-salience
   tables. This is the *candidate set* for compact, not the compact itself.
7. `compact` — `@kubernetes` step calls `Engine/Complete`
   `capability=thinking` (not `:8081`, not Cerebras). Input: candidate
   set + FMP profile/holders. Output: structured memo. Engine also
   pushes `COMPACT` into `prospects-buffer` (in-process FIFO stays on
   the host; the step only sees the RPC result).
8. `summarize` — same lattice Complete, one pass per symbol.
   Push `SUMMARY`. No Grok.
9. `publish` — write parquet/json under
   `s3://signals-dataproducts/gaius/prospects/{run}/`. Map
   `facts_from_run` (flow, run_id, pathspec, snapshot_uri, data_uri,
   code_package_sha, yk_app_id, yk_queue, rustfs_endpoint). Emit
   `dev.signals.dataproduct.updated`.
10. `overwatch` — Gaius ACP `grok agent stdio` (subscription). Observe
    quality / lineage / delta / nominal into `hx_reasoning`. Walk
    `data-product.history-review` to `understood` or `failed`.
    Holding (still buffering) is not failed.
11. `end` — never DROP warehouse partitions.

KB zettels may still be *derived* from SUMMARY for the TUI, but they
are not the product SoR.

## Aperture (Aegir pattern, Gaius collection)

Aegir: every 512-token window sees the whole aperture via MaxSim; genus
margin admits; overlapping winners suppress rivals; root-preponderance
with no genus hit → ACP review worklist.

Prospects aperture is **not** FinePDFs topics. Seed `gaius_prospects_aperture`
with ColBERT-Zero documents: MD&A / risk / guidance / liquidity / segment
/ related-party / going-concern prototypes, plus prior compact memos.
Tables are a second genus (numeric statements), admitted by the parallel
structure step rather than MaxSim-on-prose.

Window encode uses Gaius `ColBERTZeroEmbedder` (`lightonai/ColBERT-Zero`),
same as `gaius_kb_colbert_zero`. Do not revive ColPali.

## Overwatch (Atelier pattern, Grok harness)

Atelier Overwatch: tool-using supervisor, side effects only through
controlled CLIs, no direct Write.

Here: `acp.agent=grok` already resolves to `grok agent stdio` and prefers
`~/.grok/auth.json` (subscription) over `XAI_API_KEY`. Queue
`root.external.subscription.rate-limited`. Prompt is the method `doc`
(FSM, inputs, URIs, YK stamps) — the agent observes, it does not
re-inventory Signals History and does not call metered `/v1/chat`.

## Protocol / engine chores (Signals checklist §7)

1. `git submodule update --remote` `external/signals-protocol`; regen stubs.
2. Implement `Engine/Remediate` for `TX_ID_NOT_UUIDV7` (remint v7, resubmit).
3. Ask Signals to seed `gaius.prospects.corpus` once (or
   `gaius.prospects.outputs` if we want summary-shaped product).
4. `require_rustfs` on flow start.
5. Retire host `flow_processes.py` spawn for this flow; Airflow triggers
   platform Metaflow.

## Phasing

1. Protocol pin + Remediate + platform-profile fail-closed.
2. Lattice Complete usable from a pod: thinking capability default,
   thinking kwargs / `reasoning_content`, optional `json_schema`.
3. RKE2 Service/Endpoints (or one host-bridge socat) so
   `gaius-engine.metaflow.svc:50051` reaches host engine. Probe with
   `grpcurl` from a debug pod.
4. `gaius.flows.lattice.complete()` in the Metaflow image.
5. `prospects-buffer` + gRPC parity with Ambient (host).
6. Aegir-grain window_scan + table_structure as `@kubernetes` steps.
7. compact/summary via Engine/Complete; delete GLM/Grok from this path.
8. Airflow + publish + Overwatch ACP.
9. Compact-strategy research (shared protocol, two implementations).

Do not keep GLM as a fallback. Fail if thinking is not HEALTHY.

## Implemented (2026-08-16)

- Signals Metaflow only (`require_signals_metaflow`; in-cluster profile=`platform`).
- `gaius.flows.lattice.complete` + Engine/Complete defaults to thinking,
  maps `reasoning_content`, accepts `json_schema` as vLLM `guided_json`.
- Host-bridge: `infra/k8s/gaius-engine-host-bridge.yaml`.
- `ProspectsBuffer` + `/prospects buffer` + proto fields on ProspectsStatus.
- Analyze/synthesize call thinking; 512-token windows + table detect replace
  the 30k keyword compact as the analysis input.
- History seed: Signals `gaius.prospects.corpus` in
  `config/platform/data-products.json`. Flow `end` publishes via
  `gaius.flows.prospects.publish` → `signals.ops.history.review`.
- Not done: Airflow DAG, Overwatch hx_reasoning on the tx, aperture seed,
  `@kubernetes` on every step (needs a task image), protocol submodule bump.
