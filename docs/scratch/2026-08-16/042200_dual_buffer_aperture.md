# Dual-buffer attention vs Aegir aperture

Do not merge Ambient and Prospects deques. Each stream keeps its
FIFO. Attention is an Aegir-shaped **aperture**: 512/256 ColBERT-Zero
windows, MaxSim vs a concept set, genus margin ≥ τ, greedy
non-overlap, root-preponderance → ACP (not drop).

Today: grain exists (`windows.scan_windows`); production compact
calls it **without** `maxsim`. `gaius_prospects_aperture` is unseeded.
Ambient is recency + thinking. Prospects market FIFO is `[*]` markup
+ last-24 thinking.
