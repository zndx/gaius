# YK must place ColBERT; Aperture must not steal thinking's GPUs

Aperture loaded ColBERT-Zero on `cuda:0` inside the engine process while
standing thinking (HEAVY, 4×4090, ~20 GiB on GPU 0) was already there.
That CUDA OOM was logged as `#SDG.00000006.STARVE`. Starve is empty
MaxSim, not a scheduler collision.

## Profile (tinybox 6×4090)

| WRK | Leaf | GPU tokens | Physical |
|-----|------|------------|----------|
| thinking | `root.internal.inference.heavy` | 4 | 0–3 |
| embedding | `root.internal.inference.embedding` | 1 | leftover (4 or 5) |
| extract / light | extract / light leaves | 1 | the other leftover |

YK admits the embedding token (`gaius-embedding`). nvidia-smi places it
on a GPU thinking does not hold. `#YK.00000008.GPUCOLLIDE` if none is
left. Never default ColBERT to `cuda:0`.
