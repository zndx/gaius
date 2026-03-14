# vLLM Controller

The VLLMController manages vLLM inference server processes across 6 NVIDIA GPUs, handling startup, health monitoring, graceful shutdown, and recovery.

## Process Management

```python
class VLLMController:
    async def start_endpoint(
        self,
        model: str,          # HuggingFace model ID
        gpu_ids: list[int],  # Allocated GPUs
        port: int,           # Serving port
        tensor_parallel: int = 1,
    ) -> ProcessStatus

    async def stop_endpoint(self, port: int) -> bool
    async def health_check(self, port: int) -> bool
```

### Lifecycle

- **Graceful shutdown**: SIGTERM first, force kill after timeout
- **CUDA memory cleanup**: `torch.cuda.empty_cache()` on shutdown
- **Orphan detection**: Scans for stale vLLM processes on startup
- **Circular log buffer**: 500 lines for diagnostics

## GPU Allocation

6 GPUs are allocated across endpoints:

```
GPU 0-1: reasoning endpoint (tensor_parallel=2)
GPU 2-3: coding endpoint (tensor_parallel=2)
GPU 4:   embedding endpoint
GPU 5:   available for rendering/evolution
```

Allocation is managed by the Orchestrator, not the controller directly.

## Model Loading

Loading a 70B model to VRAM takes ~240 seconds. During this time:

1. The engine streams progress to connected clients
2. The endpoint status transitions: `PENDING → STARTING → HEALTHY`
3. Health checks begin polling at 30-second intervals

## Status Monitoring

```bash
# Check all endpoint status
uv run gaius-cli --cmd "/gpu status" --format json

# Watch during restart
for i in $(seq 1 15); do
    sleep 10
    uv run gaius-cli --cmd "/gpu status" --format json | \
        jq '.data.endpoints[] | {name, status}'
done
```

## Common Issues

| Symptom | Guru Code | Fix |
|---------|-----------|-----|
| Process won't start | `#EP.00000001.GPUOOM` | `/health fix endpoints` |
| Orphan process | `#EN.00004.ORPHAN_PROC` | `just gpu-cleanup` |
| cv2 import error | OpenCV conflict | See MEMORY.md OpenCV section |
