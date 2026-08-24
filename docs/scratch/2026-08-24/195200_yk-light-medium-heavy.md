# YK queues are light / medium / heavy from the model profile

YK schedules:

- **light** — models that fit on 1 GPU
- **medium** — models that need 2 consecutive GPUs
- **heavy** — models that need 4 consecutive GPUs

A workload declares that profile (`gpu_tokens` 1 / 2 / 4, model, tp).
Queue names stay those three leaves (plus extract for offline Docling
and compute for no GPU). There is no embedding leaf.

ColBERT-Zero is light. `CltSkosAdmitFlow` now sets `gpu_tokens = 1`.
Aperture MaxSim inside the engine process is the anti-pattern: GPU work
that has not been migrated to Metaflow, so it loaded CUDA without a
profile and collided with thinking (heavy). Admit `gaius-embedding` on
**light** before that CUDA, or run MaxSim in the Metaflow.
