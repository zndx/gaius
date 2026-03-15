# vLLM Controller

The VLLMController manages vLLM inference server processes across 6 NVIDIA GPUs, handling startup sequencing, health monitoring, graceful shutdown, orphan detection, and CUDA memory recovery.

## Process Lifecycle

Each vLLM endpoint runs as a subprocess managed by the controller:

```
start_endpoint() → subprocess.Popen(vllm serve ...)
    → PENDING (queued, waiting for GPU)
    → STARTING (process spawned, model loading)
    → HEALTHY (health check passes, serving)
```

Shutdown: SIGTERM → 30s grace period → SIGKILL if needed → `torch.cuda.empty_cache()` to reclaim VRAM.

### Orphan Detection

On startup, the controller scans for stale vLLM processes from previous runs. Orphan processes consume GPU memory without serving requests — a common issue after unclean shutdowns. The controller identifies them by matching process names and GPU device assignments, then terminates before attempting fresh starts.

## GPU Allocation

6 NVIDIA GPUs (80GB each) allocated across endpoints:

| Endpoint | GPUs | Tensor Parallel | Purpose |
|----------|------|-----------------|---------|
| reasoning | 0, 1 | 2 | Large model inference (24B-70B) |
| coding | 2, 3 | 2 | Code generation |
| embedding | 4 | 1 | Nomic 768-dim single-vector |
| available | 5 | — | Rendering, evolution, overflow |

Allocation is managed by the `OrchestratorService`, not the controller directly. The orchestrator calls `VLLMController.start()` with specific GPU IDs and ports. GPU 5 is deliberately kept available for transient workloads — LuxCore rendering requires GPU eviction of a running endpoint, and evolution cycles benefit from a dedicated GPU during idle periods.

## Model Loading

Loading a 70B model to VRAM takes ~240 seconds. During this time:

1. The engine streams progress to connected clients via gRPC server-streaming
2. The endpoint status transitions: `PENDING → STARTING → HEALTHY`
3. Health checks begin polling at 30-second intervals
4. The `AgendaTracker` marks the endpoint as in-transition to suppress health incidents

A circular log buffer (500 lines per endpoint) captures vLLM stderr for diagnostics. When a start fails, the buffer provides the error without requiring external log access.

## Health Monitoring

The controller polls each endpoint's `/health` HTTP endpoint at configurable intervals (default 30s). Three consecutive failures trigger an incident. Health check results feed into the FMEA engine — a persistent health degradation increases the Occurrence (O) score for that failure mode, raising the RPN and potentially escalating the remediation tier.

## Optillm Integration

The `OptillmController` wraps vLLM with reasoning enhancement techniques:

| Technique | Description |
|-----------|-------------|
| `cot_reflection` | Chain-of-thought with self-reflection |
| `bon` | Best-of-N sampling |
| `moa` | Mixture of Agents |
| `pv` | Plan and Verify |
| `z3` | Z3 SMT solver integration |

These are accessed via the `technique` field on `InferenceRequest`. A request for `cot_reflection` on a 24B model typically takes 15-20 seconds per completion.

## Common Issues

| Symptom | Guru Code | Fix |
|---------|-----------|-----|
| Process won't start | `#EP.00000001.GPUOOM` | `/health fix endpoints` |
| Orphan process blocking GPU | `#EN.00004.ORPHAN_PROC` | `just gpu-cleanup` |
| cv2 import error | OpenCV conflict | See pyproject.toml uv override |
| KV-cache exhaustion | `#VLLM_006` | Reduce `max_model_len` or restart |
| Model loading timeout | — | Check disk I/O; HuggingFace cache may be cold |
