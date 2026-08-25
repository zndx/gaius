# 10 Hz strip: named operational + semantic drivers

The Discover waterfall is a visualization surface over **real
measures**. Quiet is idle or missing, not a synthetic envelope.

## Channels (20)

| Rows | Source | Feature scenario |
|------|--------|------------------|
| `pwr-0..5` `util-0..5` | DCGM `:9400` (tinybox six 4090s) | Onsets track the hardware display: 0–3 thinking, 4 CLT, 5 spare |
| `kv` `run` `gen-tps` `prefill` | thinking vLLM `:8081/metrics` | Heavy-workload presence; flatline if the endpoint is down |
| `clt` `sae` | `feature_tape` + CLT loaded | Loaded heartbeat ~0.08; tape writes brighten `clt`; `sae` reserved absent until a driver exists |
| `ricci` `ricci-d` | Ollivier–Ricci on KB `agg` + latent buffer / CLT embeddings | Mean curvature of the live manifold; `ricci-d` is Δ×8 salience onset |

`register(driver)` appends or replaces by `name`. SAE / latentMAS later
are new drivers, not new gauges in `tick()`.

## Cadence

- Fast poller 10 Hz: hardware, vLLM, CLT (HTTP off the gRPC thread).
- Slow poller 2 s: Ricci. Ollivier OTD runs in a **spawn** worker so it
  cannot hold the engine GIL and stall `CognitionWaterfall`.
- KB `agg` scroll is reused while `points_count` is unchanged (30 s).
- `CognitionWaterfall` only reads the cache (first column may be zero).
- Tape energy uses indexed `feature_tape.ts` (not `created_at`).

## Discover 1h (2026-08-23 later)

Kumo went blank: `gpu_minute_stats` empty, PromQL used
`gaius_gaius_cognition_tremor` (OTel exports `_ratio`), and first
series of a dual-engine scrape was zeros. Query
`max(max_over_time(..._ratio[1m]))` and flop util; overlay live DCGM
minutes from the 10 Hz poller for watts.

The strip painted DC occupancy (util held at 1.0) as horizontal
bars. AC-couple real measures (dim residual + high-pass onsets) so
activity deltas show as transients; absent stays 0.

## Kumo envelope

`gaius.cognition.tremor` is max(|ricci-d|, clt, sae, gen-tps, prefill).
GPU util/power stay on the strip and on the watts/util Kumo series; they
do not latch salience at 1.0.
