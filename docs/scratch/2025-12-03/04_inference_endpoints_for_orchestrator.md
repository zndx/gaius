# Inference Endpoints for Orchestrator Agent

**Date**: 2025-12-03
**Purpose**: Document inference endpoint configuration for the orchestrator agent to manage.

## Available Endpoints

The GPU orchestrator manages 4 vLLM endpoints across 6 RTX 4090 GPUs:

| Endpoint | Model | GPUs | Purpose |
|----------|-------|------|---------|
| `reasoning` | Qwen/QwQ-32B | 0, 1 (TP=2) | Complex analysis, chain-of-thought |
| `coding` | Qwen/Qwen3-Coder-30B-A3B-Instruct | 2 | Code generation, debugging |
| `fast` | mistralai/Mistral-7B-Instruct-v0.3 | 3 | Quick responses, simple tasks |
| `orchestration` | nvidia/Orchestrator-8B | 4, 5 (TP=2) | Task routing, agent coordination |

**Note**: Orchestration uses TP=2 (tensor parallelism across 2 GPUs) to support the full 40960 context window. A single RTX 4090 only supports ~31k context for this model.

## Endpoint Management Commands

### TUI Commands

```
/inference status              # Show all endpoint states
/inference start <endpoint>    # Start specific endpoint
/inference stop <endpoint>     # Stop specific endpoint
/inference restart <endpoint>  # Restart specific endpoint
/inference ensure              # Ensure nvidia/Orchestrator-8B running
```

### MCP Tools

```python
# Status
mcp__gaius__orchestrator_status()  # Full orchestrator state
mcp__gaius__scheduler_status()     # Scheduler queue state

# Control
mcp__gaius__orchestrator_start(endpoint="reasoning")
mcp__gaius__orchestrator_stop(endpoint="reasoning")
mcp__gaius__orchestrator_restart(endpoint="reasoning")

# Logs
mcp__gaius__orchestrator_logs(endpoint="reasoning", lines=50)

# Health
mcp__gaius__gpu_health()           # GPU VRAM, temp, utilization
mcp__gaius__scheduler_health_check()
```

### CLI Commands

```bash
uv run gaius-cli --cmd "/inference status"
uv run gaius-cli --cmd "/inference start reasoning"
```

## Endpoint States

```
STOPPED    → Not running, no process
STARTING   → Process launched, loading model into VRAM
HEALTHY    → Ready to serve requests
UNHEALTHY  → Running but failing health checks
FAILED     → Process crashed or couldn't start
```

## Orchestrator Agent Responsibilities

The orchestrator agent (nvidia/Orchestrator-8B) should:

### 1. Health Monitoring
- Periodically check endpoint health via `orchestrator_status`
- Detect unhealthy or failed endpoints
- Auto-restart failed endpoints (with backoff)

### 2. Task Routing
- Route tasks to appropriate endpoints based on type:
  - Reasoning tasks → `reasoning` endpoint
  - Code tasks → `coding` endpoint
  - Quick queries → `fast` endpoint
  - Coordination → `orchestration` endpoint

### 3. Resource Management
- Monitor GPU health (VRAM, temperature)
- Scale endpoints up/down based on load
- Use `standby` GPU for overflow or failover

### 4. Startup Sequence
```yaml
startup_sequence:
  1. Check GPU health (all 6 GPUs available)
  2. Start orchestration endpoint (self)
  3. Start fast endpoint (quick responses)
  4. Start reasoning endpoint (if needed)
  5. Start coding endpoint (if needed)
  6. Keep standby available
```

## Configuration

Endpoints are configured in `config/base.conf`:

```hocon
orchestrator {
  endpoints {
    reasoning {
      models = ["Qwen/QwQ-32B"]
      gpus = [0, 1]
      tensor_parallel = 2
      max_model_len = 32768
    }
    coding {
      models = ["Qwen/Qwen3-Coder-30B-A3B-Instruct"]
      gpus = [2]
      tensor_parallel = 1
      max_model_len = 200000
    }
    fast {
      models = ["mistralai/Mistral-7B-Instruct-v0.3"]
      gpus = [3]
      tensor_parallel = 1
    }
    orchestration {
      models = ["nvidia/Orchestrator-8B"]
      gpus = [4]
      tensor_parallel = 1
    }
    standby {
      models = []
      gpus = [5]
      tensor_parallel = 1
    }
  }
}
```

## Error Handling

### Common Issues

| Error | Cause | Remediation |
|-------|-------|-------------|
| "vLLM binary not found" | vLLM not installed | `pip install vllm` |
| "CUDA out of memory" | Model too large | Reduce max_model_len or use TP |
| "Connection refused" | Endpoint not started | `/inference start <endpoint>` |
| Timeout on health check | Model loading slowly | Wait or check GPU utilization |

### Automatic Recovery

The orchestrator should implement:
```python
recovery_policy:
  max_restarts: 3
  backoff_seconds: [10, 30, 60]
  alert_on_failure: true
  failover_to_standby: true
```

## Integration with Swarm

When running swarm analysis (`mcp__gaius__run_swarm`), the orchestrator:

1. Checks which endpoints are healthy
2. Distributes specialist agent tasks across endpoints
3. Uses scheduler for load balancing
4. Collects and synthesizes results

## Metrics to Track

```yaml
metrics:
  - endpoint_uptime_seconds
  - requests_per_endpoint
  - avg_latency_ms
  - gpu_utilization_percent
  - vram_usage_gb
  - queue_depth
  - failed_requests
```

## Future: Scale-to-Zero

For cost optimization, the orchestrator can implement scale-to-zero:
- Shut down idle endpoints after N minutes
- Keep `fast` always running (quick startup)
- Start `reasoning`/`coding` on demand
- Track cold start latency for capacity planning
