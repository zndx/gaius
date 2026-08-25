# Shared 10 Hz ring + DkCyan2 / motion overlay

1. The engine poller now appends every 100 ms into a 60 s × 10 Hz
   ring (`start_strip()` at boot). Discover snapshots that buffer, so
   every client sees the same layout and a load is already filled
   (after the engine has been up long enough to collect history).

2. Steady-state `gpu-n` uses biscale **DkCyan2** (x=power, y=util).
   Onsets walk ColorBrewer Reds/Blues 5-stop ramps (not a solid flash).
   gpu-n DkCyan2 is driven by DC plus EMA high-pass of power/util so the
   bed gradients like util-n. The canvas lerps RGB between samples so
   peaks have spatial gradients.
