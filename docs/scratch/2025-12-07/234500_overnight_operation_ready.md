# Overnight Operation Ready

**Date**: 2025-12-07 23:45

## Summary

Successfully configured gaius-engine for continuous overnight operation with both vLLM endpoints healthy.

## Fixes Made

### 1. Per-endpoint `max_num_seqs` Support

The reasoning endpoint was failing with OOM during sampler warmup because vLLM was using its default `max_num_seqs=256` instead of the configured value of 64.

**Files modified:**

1. `src/gaius/engine/config.py:27-32`:
   - Added `max_num_seqs` field to `EndpointConfig` dataclass
   - Added parsing in `_parse_config` (line 301)

2. `src/gaius/engine/backends/vllm_controller.py`:
   - Added `max_num_seqs` field to `VLLMProcess` dataclass (line 74)
   - Added extraction from `agent_config.endpoint.max_num_seqs` (lines 262-265)
   - Added `--max-num-seqs` to vLLM command line (lines 312-313)

### 2. Previous Session: Per-endpoint `context_length` Support

Similar fix was already applied for `context_length` in the previous session.

## Current State

### GPU Allocation
```
GPU 0: 22.6 GB - Mistral-7B (fast endpoint)
GPUs 1-4: 23.2 GB each - DeepSeek-R1-Distill-Qwen-32B (reasoning, 4-way TP)
GPU 5: 4 MB - Available for evolution
```

### Endpoints
- **fast** (port 8080): Mistral-7B-Instruct-v0.3
  - 1 GPU, 32K context, 256 max_num_seqs
  - Status: HEALTHY

- **reasoning** (port 8081): DeepSeek-R1-Distill-Qwen-32B
  - 4 GPUs (tensor-parallel=4), 32K context, 64 max_num_seqs
  - Status: HEALTHY

### Services Running
- Cognition daemon: Started
- Engine PID: 3140622
- Log: `/tmp/gaius-logs/engine-maxnumseqs.log`

## Verification

Both endpoints tested successfully:
```bash
# Fast endpoint
curl http://localhost:8080/v1/chat/completions ...
# Response: "Hello there! How can I help you today?"

# Reasoning endpoint
curl http://localhost:8081/v1/chat/completions ...
# Response: Chain-of-thought reasoning visible
```

## Config Reference

```hocon
# config/agents.conf - reasoning endpoint
reasoning {
  model = "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B"
  resources {
    gpus = 4
    context-length = 32768
  }
  endpoint {
    port = 8081
    tensor-parallel = 4
    max-num-seqs = 64  # Critical for 32B model
  }
}
```
