# Waterfall left-edge blob + tinybox LCD reconnaissance

## Left-edge "static red blob" — fixed

Regression from the settled-second anchor (`min(now-2, gpu_newest-1)`): the strip's
oldest column reaches back `window_s + backoff` seconds, but both fetches only asked
for `window_s`. Column 0 (`anchor-59 = now-61` at a 60 s window) fell one second
before the query start, so it was permanently `0.0`. The `0 → value` step at col 1
read as a rising edge that the onset field painted red every frame — a fixed red blob
welded to the left edge.

Fixes (commits on `trunk`):
- `33e02dd` widen both fetches to `window_s + _EDGE_MARGIN_S` (4 s).
- `ee6b013` bounded **leftward** backfill in the sample-and-hold: the forward pass
  carries rightward and can't fill col 0; backfill a short leading gap from the first
  present column, capped at `max_hold` so a post-restart warm-up stays honestly dark.

Two other left-edge phenomena, both benign:
- **Warm-up**: for the first ~60 s after any engine restart the warehouse has < 60 s
  of history, so leading columns are legitimately empty until history accumulates.
  Self-heals. (Caused the transient 9/50 in mid-verification.)
- Ingest lag consumes the anchor margin; with lag ~1 s there are 2–3 s of slack.

Verification (full history, HTTP path): 46 frames, 45 one-step pairs, **0 jumps,
0/46 empty-left-edge frames, 0 edge-scroll inconsistencies**. No warehouse gaps
(91 s window, 0 gaps).

## Limited dynamics — diagnosis (not yet fixed)

Live NVML (what the LCD shows): GPUs 0–3 pegged at **util 100 %** (flat) under vLLM
4-way TP, power 115–134 W; GPUs 4–5 idle. Util is saturated → carries no dynamics.

The pack is `1.0 + util + p01·1e-4` with `p = (watts - 22) / (350 - 22)`. Two problems:
1. `_BUSY_W = 350` (full TDP) vs. actual sustained ~100–134 W → power normalizes into a
   thin band `[0.23, 0.34]`, only 0.11 wide → the color barely moves.
2. Power lives in the `1e-4` residual of the packed value; the **onset field runs on the
   packed value and sees only util**, so power spikes produce no red/blue onset.

The tinybox LCD teaches the fix: when util pegs, **power is the signal** — the LCD
foregrounds it (big rolling-power number + a dedicated power line-graph), not util bars.

Recommended:
- Normalize power against a realistic sustained ceiling (or an adaptive/rolling range)
  so it uses the full [0,1].
- Route power into the gpu-N onset so a power spike yields the "spike → colored onset →
  scroll" behavior the user wants.

## The tinybox resident program

- Unit: `tinybox-display.service` → `/opt/tinybox/service/display/service.py`
  (venv python, PID 3002). Sibling `tinybox-button.service`.
- LCD driver: `/opt/tinybox/tinyturing/` — a **Turing Smart Screen** (480×1920-ish
  portrait USB panel), numba-accelerated blit.
- StatusScreen renders: per-GPU **vertical util bars**, per-GPU **horizontal VRAM bars**,
  **64 CPU-core bars**, **rolling total power (W)** + a **power LineGraph**, disk I/O
  (MB/s over the 4 RAID nvmes). Also Sleep/Welcome/Startup screens (BMC IP/pw, docs QR).
- Data source: `stats.py` → `NVGPUStats` via **pynvml**:
  - util  = `nvmlDeviceGetUtilizationRates(h).gpu`
  - power = `nvmlDeviceGetPowerUsage(h) // 1000` (mW→W)
  - mem   = `used / total * 100`
  (AMD path reads `/sys/class/drm/card*/device/gpu_busy_percent` and remaps 5–100→0–100.)

## Dynamics — corrected understanding + power-band fix (commit a9839a0)

User correction: util IS dynamic, and the intended design (bar-up→red, bar-down→blue;
DkCyan2 bivariate steady color when <100%) is already wired in discover.js
(`stripRgb`→`gpuRgb`: `dkcyan2(pVis,uVis)` + `overlayMotion(onsetField)`).

A/B (ported client pipeline, live data under bursty load):
- When util swings 30–100% (gpu-1/2/3), dynamics ALREADY work: colorσ 8–16, red on
  rise + blue on fall. OLD(22..350) and NEW(10..200) score nearly identically because
  **util dominates** that window.
- The power axis was starved. Isolated pegged-util decode swing (95→135→100 W):
  | band | power-axis width | steady colorσ | visible flash cells |
  |------|-----|-----|-----|
  | OLD 22..350 | 0.12 | 0.029 | 7/17 |
  | NEW 10..200 | 0.21 | 0.050 | 15/17 |
  → ~2× the power dynamics in the case that used to go static (util pegged, power the
  only signal). Honest limit: when util AND power are both flat (true steady state),
  the row is legitimately static — no mapping invents motion from constant data.

## Operational note: post-restart warehouse-ingest stall

Rapid engine restarts caused a ~2–3 min warehouse-ingest gap: `#DB.00000001.CONNFAIL`
(impala_fdw/Postgres warehouse conn not ready as the engine came up) froze
`signal_tier0` writes → blank strip. Self-healed once the conn recovered (freshness
back to age 0–1 s; tick log jumps 04:32:59 → 04:36:47). Same warm-up class as the vLLM
cold-start. Candidate hardening: ingest loop should retry the warehouse conn instead of
stalling the tick until it recovers.
