# GPU Management

Gaius manages 6 NVIDIA RTX 4090 GPUs (24GB VRAM each, 144GB total) across vLLM inference, LuxCore rendering, and embedding workloads.

## GPU Allocation

Device assignment is **all-or-nothing**. One model owns a GPU. We never
place two models on one card, even when VRAM is free. A large model
takes as many *whole* GPUs as tensor-parallel requires.

| GPU | Typical Use | VRAM | Notes |
|-----|-------------|------|-------|
| 0–3 | thinking (Qwen3.8-27B) | 4 × 24GB | TP=4, whole devices |
| 4–5 | Ask light / medium | 2 × 24GB | 2× 1.7B (light, one GPU each) or 1× 9B-SAE (medium, TP=2) |

The Orchestrator manages allocation via capability-based scheduling (OR-Tools CP-SAT). GPUs can be temporarily reassigned for LuxCore rendering or evolution training via makespan scheduling — the Orchestrator evicts a low-priority endpoint, runs the workload, then restores the endpoint.

## Status Monitoring

```bash
# Endpoint status
uv run gaius-cli --cmd "/gpu status" --format json

# GPU health (memory, temperature, utilization)
uv run gaius-cli --cmd "/gpu health" --format json
```

## Cleanup

When GPU processes get stuck or memory leaks:

```bash
# Standard cleanup (kill orphan vLLM processes)
just gpu-cleanup

# Deep cleanup (aggressive memory recovery)
just gpu-deep-cleanup
```

The `gpu-helpers.sh` shared library provides the `gpu_cleanup` function used by both the engine startup script and the justfile recipes.

## Common Issues

| Issue | Symptom | Fix |
|-------|---------|-----|
| Orphan vLLM process | GPU memory used but no endpoint | `just gpu-cleanup` |
| OOM during model load | Endpoint stuck in STARTING | Free GPU, then `/health fix endpoints` |
| CUDA memory fragmentation | Degraded inference speed | `just gpu-deep-cleanup` then restart |
| OpenCV conflict | vLLM WorkerProc fails (cv2 error) | Already fixed via pyproject.toml override |
| Qwen3.8 JIT `cicc` / `GLIBC_2.38` | thinking STARTING then FAILED after ~14 GiB/GPU | Tinybox CUDA 12.4 + host gcc-11; `scripts/lib/tinybox-nvcc.sh` shadows `$CUDA_HOME/bin/nvcc`. Do not install CUDA 13 |
| `/dev/shm` full (`#EP.00000007`) | thinking fails: `Insufficient space in /dev/shm` (0 MiB free) | Leftover `--kv-offloading-size` maps. `/health fix endpoints` or `just gpu-cleanup` unlinks unheld `vllm_offload_*.mmap` / `psm_*` only — never PostgreSQL or `gaius-aeron` |

## Rendering GPU Eviction

The viz pipeline temporarily evicts a low-priority endpoint to use a GPU for LuxCore rendering:

1. Orchestrator evicts endpoint from target GPU
2. LuxCore renders using PATHOCL engine with CUDA
3. `clear_embeddings()` releases Nomic model (~3GB)
4. Orchestrator restores evicted endpoint
