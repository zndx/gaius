# 64K Context Deployment for DeepSeek-R1-Distill-Qwen-32B

## Summary

Successfully deployed DeepSeek-R1-Distill-Qwen-32B with 64K context window on 4x RTX 4090 GPUs using tensor-parallel=4.

## Key Configuration

### Optimal vLLM Parameters

```bash
vllm serve deepseek-ai/DeepSeek-R1-Distill-Qwen-32B \
  --port 8081 \
  --tensor-parallel-size 4 \
  --gpu-memory-utilization 0.90 \
  --max-model-len 65536 \
  --max-num-seqs 32
```

### Resource Metrics

| Metric | Value |
|--------|-------|
| Available KV cache memory | 5.35 GiB |
| GPU KV cache size | 87,632 tokens |
| Maximum concurrency at 64K | 1.34x |
| CUDA graph capture time | 3 seconds |
| Total engine init time | ~30 seconds |

## Problem Solved

Initial attempt with `--max-num-seqs 256` (default) failed during sampler warmup:

```
RuntimeError: CUDA out of memory occurred when warming up sampler with 256 dummy requests.
Please try lowering `max_num_seqs` or `gpu_memory_utilization` when initializing the engine.
```

The fix was reducing `--max-num-seqs` from 256 to 32, which:
- Reduces CUDA graph memory (0.53 GiB vs 2.37 GiB)
- Speeds up graph capture (3s vs 23s)
- Maintains 1.34x concurrency for single 64K requests (sufficient for reasoning workloads)

## Files Modified

1. **config/base.conf** - Updated vLLM defaults:
   - `gpu_memory_utilization = 0.90`
   - `max_model_len = 65536`
   - `max_num_seqs = 32`

2. **config/agents.conf** - Updated reasoning agent:
   - `context-length = 65536`
   - `max-num-seqs = 32`

3. **src/gaius/inference/orchestrator.py** - Added `max_num_seqs` parameter:
   - Load from config: `self._max_num_seqs = vllm_cfg.get("max_num_seqs", 32)`
   - Pass to vLLM: `"--max-num-seqs", str(self._max_num_seqs)`

## Model Selection

Switched from `Qwen/QwQ-32B` to `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B`:
- **Reason**: DeepSeek-R1-Distill was already cached at `/raid/cache/huggingface`
- **Benefit**: SOTA reasoning capabilities via R1 distillation
- **Architecture**: Qwen2ForCausalLM (same as QwQ)

## Environment Variables

Critical environment variable for model cache:
```bash
HF_HOME=/raid/cache/huggingface
```

The orchestrator now auto-detects this path if not explicitly set.

## Verification

```bash
# Check endpoint
curl -s http://localhost:8081/v1/models | jq '.data[0].max_model_len'
# Output: 65536

# Test inference
curl -s http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B", "messages": [{"role": "user", "content": "What is 2+2?"}], "max_tokens": 50}'
```

## Trade-offs

| Aspect | 32K Context | 64K Context |
|--------|-------------|-------------|
| max_num_seqs | 256 (default) | 32 |
| gpu_memory_utilization | 0.85 | 0.90 |
| Concurrency | Higher throughput | Lower throughput, longer context |
| Use case | Batch processing | Deep reasoning |

For reasoning workloads (evolution, complex analysis), the 64K context with 1.34x concurrency is optimal since these tasks are typically single-request, long-context operations.
