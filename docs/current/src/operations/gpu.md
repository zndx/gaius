# GPU Management

Gaius manages 6 NVIDIA GPUs across vLLM inference, LuxCore rendering, and embedding workloads.

## GPU Allocation

| GPU | Typical Use |
|-----|-------------|
| 0-1 | Reasoning endpoint (tensor_parallel=2) |
| 2-3 | Coding endpoint (tensor_parallel=2) |
| 4 | Embedding endpoint |
| 5 | Available for rendering/evolution |

Allocation is managed by the Orchestrator. GPUs can be temporarily reassigned for rendering or evolution workloads via makespan scheduling.

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

## Rendering GPU Eviction

The viz pipeline temporarily evicts a low-priority endpoint to use a GPU for LuxCore rendering:

1. Orchestrator evicts endpoint from target GPU
2. LuxCore renders using PATHOCL engine with CUDA
3. `clear_embeddings()` releases Nomic model (~3GB)
4. Orchestrator restores evicted endpoint
