# Operational Infrastructure Drift Diagnostic

**Date**: 2025-12-20
**Status**: Analysis Complete, Fixes Required

## Summary

Comprehensive audit revealed significant drift between documented architecture and runtime state. The NiFi Selenium dataset generation pipeline failed due to LLM endpoint misconfiguration.

## Observed Issues

### 1. optillm Backend Mismatch (CRITICAL)

**Expected** (per `base.conf`):
- optillm at port 8000 proxies to vLLM at port 8088
- `OPENAI_API_BASE=http://localhost:8088/v1/`

**Actual**:
- optillm running at port 8000 (gunicorn workers: 219119, 219127, 219151)
- Environment: `OPENAI_API_BASE=http://localhost:8088/v1/`
- **Nothing listening on port 8088**
- optillm falls back to gpt-4o-mini (unintended OpenAI usage)

**Root Cause**: The gaius-engine started optillm with backend port 8088, but no vLLM process was started on that port.

### 2. Endpoint Port Confusion

**Documented ports** (per `agents.conf` and `2025-12-09/140000_port_config_audit.md`):

| Endpoint | Port | Model |
|----------|------|-------|
| orchestrator | 8080 | nvidia/Orchestrator-8B |
| reasoning | 8081 | DeepSeek-R1-Distill-Qwen-32B |
| coding | 8082 | deepseek-coder-6.7b-instruct |
| fast | 8083 | Mistral-7B-Instruct-v0.3 |

**Actually running**:

| Port | Process | Model |
|------|---------|-------|
| 8000 | optillm-gunicorn | (proxy to non-existent 8088) |
| 8080 | Tilt (K8s) | N/A |
| 8083 | Tilt (K8s) | N/A |
| 8085 | vLLM | Mistral-7B-Instruct-v0.3 |

### 3. GPU Memory Saturated

All 6 GPUs at ~93% VRAM usage (22-23GB of 24GB):

```
GPU 0,1: 22686 MiB / 24564 MiB
GPU 2-5: 23216 MiB / 24564 MiB
```

**Observation**: Memory is allocated but endpoints are not responding. Likely orphaned vLLM processes.

### 4. gaius-engine State Inconsistency

Orchestrator status shows:
- `orchestrator`: unhealthy (port 8093)
- `embedding`: stopping (port 8082)
- `coding`: stopping (port 8083)
- `fast`: failed (port 8092)
- `reasoning`: stopping (port 8095)

**Note**: These ports (809x) don't match documented ports (808x).

### 5. Tilt Occupying Reserved Ports

Tilt (K8s local dev) is listening on ports 8080 and 8083, which conflicts with expected vLLM endpoint ports.

## Configuration Hierarchy Confusion

Multiple config sources with conflicting values:

1. **`config/agents.conf`**: Canonical agent definitions (should be source of truth)
2. **`config/base.conf`**: HOCON config with some endpoint settings
3. **`devenv.nix`**: Process definitions with environment variables
4. **Engine runtime state**: Actual allocations (drifted from config)

## Fixes Required

### Immediate (Manual)

```bash
# 1. Kill orphaned vLLM processes
pkill -9 -f vllm

# 2. Stop Tilt if not needed for K8s
# (or move to non-conflicting ports)

# 3. Restart gaius-engine with clean state
devenv processes down
devenv processes up

# 4. Verify optillm has correct backend
curl http://localhost:8088/health  # Should be vLLM
curl http://localhost:8000/health  # optillm proxy
```

### Configuration Consolidation

1. **Single source of truth**: `config/agents.conf` for all endpoint definitions
2. **Dynamic port assignment**: Engine should assign ports, not use hardcoded values
3. **Tilt port isolation**: Move K8s services to 9xxx range

### Monitoring Additions

Add health checks that detect:
- Port conflicts (multiple processes on same port)
- optillm→vLLM connectivity
- GPU memory vs. running processes correlation

## Architecture Reminders

Per `2025-12-08/100000_agent_first_engine_architecture.md`:

> "The engine is now the single source of truth for GPU resources and model lifecycle."

All inference should go through engine, not direct vLLM access. The dataset generation pipeline needs to use engine-managed endpoints.

## Default GPU Layout (Expected)

Per `2025-12-08/001500_dynamic_gpu_allocation.md`:

| Endpoint | Model | GPUs | Port |
|----------|-------|------|------|
| orchestrator | nvidia/Orchestrator-8B | 2 (TP=2) | 8084 |
| fast | Mistral-7B-Instruct-v0.3 | 1 | 8083 |
| fast-2 | Mistral-7B-Instruct-v0.3 | 1 | 8085 |
| coding | Qwen/Qwen2.5-Coder-32B-Instruct | 2 (TP=2) | 8082 |

When reasoning (4-GPU) is needed, swap: stop coding+fast+fast-2, start reasoning.

## Related Documentation

- `docs/scratch/2025-12-09/140000_port_config_audit.md` - Port configuration standards
- `docs/scratch/2025-12-08/100000_agent_first_engine_architecture.md` - Engine-first architecture
- `docs/scratch/2025-12-08/001500_dynamic_gpu_allocation.md` - GPU swap plans
- `docs/scratch/2025-12-19/143000_metaagent_design_roadmap.md` - MetaAgent/NiFi pipeline
