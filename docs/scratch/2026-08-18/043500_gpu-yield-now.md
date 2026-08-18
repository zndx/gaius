# GPU yield now — 2026-08-18 04:34 UTC

Snapshot while thinking Qwen3.8-27B is the only loaded endpoint.

## Board

| GPU | Util | Power | VRAM | Role |
|-----|------|-------|------|------|
| 0–3 | 100/100/25/100 % | ~110–128 W each (~463 W) | 21.2 / 24.6 GiB | heavy thinking TP=4 `:8081` |
| 4–5 | 0 % | ~19 + 16 W | empty | parked (medium/light off) |

Box total ~499 W. TDP is 450 W/card — we are **decode-bound**, not
compute-bound. `vllm:iteration_tokens` is almost all 1 token/step
(batch = 1). `Observe` flops ~38 % is the honest number; nvidia-smi
100 % SM is occupancy theater.

vLLM (this process, ~5.6 h):

- 697 engine Completes labeled `thinking`
- 58 529 prompt tokens, 154 302 generation tokens
- avg ~62 in / ~149 out per request
- 238 / 697 (34 %) finished `length` (truncated)
- prefix-cache **0 hits / 58 529 queries**
- 1 request running, KV cache 0.7 %
- Only client of `:8081` is the engine (PID 2348764). A 22 h
  `grok --continue` in this repo talks to the engine via MCP, not
  around it.

`tokens_in_total` / `tokens_out_total` series exist but have **no
samples**. `tokens_total` = 147 066. Root cause: `BackendRouter.route`
passed `tokens=` sum and omitted the split kwargs. Fixed in
`backend_router.py`; needs engine recycle to scrape.

## What is not happening

- Medium (9B+SAE) / light (1.7B+CLT) are **not** loaded. Correct duty cycle.
- CLT collection `gaius_clt_latent_thoughts`: **0 points**.
- `cognition_thoughts` latest row: **2026-08-15 13:25Z**. Cognition
  cycles that parse 4–6 thoughts are not landing as queryable
  artifacts the surface can read.
- No DCGM series on local Prometheus `:9090` yet (Signals parallel).

## High-value vs noise

Noise signature on this box right now:

1. Single-stream decode on 4×4090 (~110 W/card, 100 % SM, 0.7 % KV).
2. Short prompts (~62 tok), no prefix reuse.
3. One in three Completes hits `max_tokens`.
4. No CLT slice, no fresh thought row, no yield event.

Actionable understanding per watt, in order:

1. Recycle engine so split token counters hydrate (patch is in-tree).
2. Persist `InferenceYield` for every Complete (class, in/out, ms,
   artifact id). ELK table is that tape.
3. Make cognition save actually visible (same DB the MCP
   `get_recent_thoughts` reads). Watts that do not leave a row are
   noise.
4. Run 27B *output text* through light CLT on a parked GPU as a
   labeled probe — that is the time-slice stack.
5. Do not fill 4–5 with another generative replica.
6. Consume DCGM from Signals when the exporter is up; overlay W on
   the Discover histogram. No DCGM dep here.

Four other `grok --continue` PIDs (gaius, signals, aegir, atelier)
are live shells. Only the gaius one is on this engine. Do not kill
them from this session.
