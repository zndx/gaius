# E2E-CI: End-to-End Continuous Integration Validation

**Date**: 2025-12-20
**Status**: Design Document + Live Testing
**Shorthand Options**:
- **E2E-CI** (formal) - End-to-End Continuous Integration
- **GAIUS-E2E** (branded) - Gaius E2E validation
- **LLMOps-Check** (descriptive) - LLM Operations healthcheck
- **Pre-flight** (NASA-inspired) - Pre-flight check before mission

**Recommended**: **Pre-flight** - short, memorable, conveys the "check before launch" intent

## Overview

E2E-CI is a comprehensive validation framework for the Gaius system that tests the complete pipeline from infrastructure to inference. The name reflects the integration testing approach needed for complex LLMOps environments with multiple interdependent services.

## Why the Engine is Central

### The Problem: Operational Drift

Resource-constrained GPU environments suffer from a critical failure mode: **operational drift** - where the documented architecture diverges from runtime state. This manifests as:

1. **Orphaned Processes**: vLLM endpoints that were killed externally but still tracked by internal state
2. **Port Conflicts**: Multiple services binding to the same ports (e.g., Tilt and vLLM on 8080)
3. **Configuration Mismatch**: Environment variables not propagating correctly (e.g., `OPTILLM_BASE_URL=` being empty)
4. **Stale State**: ResourceManager thinking GPUs are allocated when they're actually free

### The Solution: Engine as Single Source of Truth

The Gaius Engine (`gaius-engine`) implements **agent-first architecture** where:

1. **Capability-Based Routing**: Requests declare capabilities (reasoning, coding, embedding), not endpoints
2. **Dynamic GPU Scheduling**: Engine swaps models based on workload (e.g., stop coding to enable reasoning)
3. **Resource Reconciliation**: Engine detects and cleans up orphaned processes
4. **Health Monitoring**: Continuous health checks with automated remediation

### Engine gRPC Interface

All inference should route through the engine's gRPC interface:

```python
from gaius.client import get_engine_client

async with get_engine_client() as client:
    # Request capability, not specific endpoint
    result = await client.call("Scheduler", "submit", {
        "prompt": "...",
        "capability": "reasoning",
        "priority": "normal"
    })
```

## E2E-CI Validation Matrix

### Infrastructure Layer

| Check | Method | Pass Criteria |
|-------|--------|---------------|
| PostgreSQL | `pg_isready` | Returns 0 |
| Qdrant | `/health` endpoint | Status 200 |
| MinIO | `mc ls` | Lists buckets |
| NiFi | `/nifi-api/system-diagnostics` | Status 200 |
| Prometheus | `/api/v1/status/config` | Status 200 |

### GPU Layer

| Check | Method | Pass Criteria |
|-------|--------|---------------|
| GPU Memory | `nvidia-smi` | < 90% per GPU |
| Orphan Detection | `pgrep -f vllm` vs engine state | Counts match |
| Port Availability | `ss -tlnp` | No conflicts |

### Inference Layer

| Check | Method | Pass Criteria |
|-------|--------|---------------|
| Engine gRPC | Port 50051 | Single listener |
| optillm | `/health` | Status 200 |
| optillm Backend | Inference test | Returns local model |
| vLLM Endpoints | `/v1/models` | Model loaded |

### Application Layer

| Check | Method | Pass Criteria |
|-------|--------|---------------|
| MCP Server | Tool registration | All tools available |
| CLI | `/health` command | Returns OK |
| Dataset Pipeline | Selenium capture | Screenshots generated |

## Critical Failure Modes

### 1. Engine Can't Recover from External Kills

**Symptom**: Engine reports 0 free GPUs but `nvidia-smi` shows all clear

**Cause**: Processes killed externally (pkill, OOM) don't notify engine

**Remediation**:
```bash
# Restart engine to reconcile state
process-compose process restart gaius-engine
```

**Long-term Fix**: Add reconciliation loop that periodically validates GPU state against `nvidia-smi`

### 2. optillm Falls Back to OpenAI

**Symptom**: Inference requests return gpt-4o-mini responses

**Cause**: `OPTILLM_BASE_URL` environment variable empty

**Remediation**:
```bash
# Set environment and restart
OPTILLM_BASE_URL=http://localhost:8080/v1 process-compose process restart optillm
```

**Long-term Fix**: Engine should manage optillm configuration dynamically

### 3. Multiple Engine Instances

**Symptom**: Multiple processes on port 50051

**Cause**: Old engine instances not cleaned up on restart

**Remediation**:
```bash
# Find and kill orphaned engines
ps -eo pid,ppid,etime,command | grep "gaius.engine" | grep -v grep
# Kill processes with PPID=1 (orphaned)
```

### 4. Tilt Port Conflicts

**Symptom**: vLLM can't start on expected ports (8080, 8083)

**Cause**: Tilt (K8s dev tool) claims these ports

**Remediation**:
```bash
pkill -f tilt
```

**Long-term Fix**: Move Tilt to 9xxx port range in Tiltfile

## GPU Swap Protocol

The engine implements dynamic GPU swapping between configurations:

**Default State (6 GPUs)**:
- orchestrator: 2 GPUs (0,1)
- fast: 1 GPU (2)
- embedding: 1 GPU (3)
- coding: 2 GPUs (4,5)

**Reasoning State (6 GPUs)**:
- orchestrator: 2 GPUs (0,1)
- reasoning: 4 GPUs (2,3,4,5)

Transition triggered by:
```python
await engine.call("Orchestrator", "swap_to_reasoning", {})
```

## Validation Script

```python
#!/usr/bin/env python
"""E2E-CI validation script."""

import subprocess
import httpx
import asyncio

async def validate_e2e():
    """Run full E2E-CI validation."""
    results = {}

    # 1. Infrastructure
    results["postgres"] = subprocess.run(
        ["pg_isready", "-h", "localhost", "-p", "5438"],
        capture_output=True
    ).returncode == 0

    async with httpx.AsyncClient() as client:
        # 2. Engine
        try:
            r = await client.get("http://localhost:50051/health")
            results["engine"] = r.status_code == 200
        except:
            results["engine"] = False

        # 3. optillm
        try:
            r = await client.get("http://localhost:8000/health")
            results["optillm"] = r.status_code == 200
        except:
            results["optillm"] = False

        # 4. vLLM endpoints
        for port in [8080, 8081, 8083]:
            try:
                r = await client.get(f"http://localhost:{port}/v1/models")
                results[f"vllm_{port}"] = r.status_code == 200
            except:
                results[f"vllm_{port}"] = False

    # 5. GPU check
    smi = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader"],
        capture_output=True, text=True
    )
    results["gpu_available"] = "MiB" in smi.stdout

    return results

if __name__ == "__main__":
    results = asyncio.run(validate_e2e())
    for check, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {check}")
```

## Related Documentation

- `docs/scratch/2025-12-20/193000_operational_drift_diagnostic.md` - Infrastructure drift diagnosis
- `docs/scratch/2025-12-08/100000_agent_first_engine_architecture.md` - Engine-first architecture
- `docs/scratch/2025-12-08/001500_dynamic_gpu_allocation.md` - GPU swap plans
- `docs/scratch/2025-12-09/140000_port_config_audit.md` - Port configuration

## Live Testing Results (2025-12-20)

### What Worked

1. **optillm to vLLM routing**: After setting `OPTILLM_BASE_URL=http://localhost:8080/v1`, inference correctly routes to local nvidia/Orchestrator-8B
2. **Orphan cleanup**: Manual `pkill` cleaned up stale processes
3. **Port conflict resolution**: Killing Tilt freed ports 8080/8083

### What Didn't Work

1. **Engine state reconciliation**: Engine can't detect externally-killed processes
2. **process-compose restart**: Didn't actually restart the engine process
3. **DatasetService initialization**: gRPC calls timeout waiting for service
4. **gunicorn raw_env**: Environment variables from config not applied

### Key Insight: Engine is Central

The single most important lesson: **All LLM operations MUST route through the engine**. When processes are started/killed outside the engine (manual vLLM, Tilt, etc.), the engine's ResourceManager becomes stale and the entire system enters an inconsistent state.

The engine provides:
1. **Single source of truth** for GPU allocations
2. **Capability-based routing** (request "reasoning", get appropriate model)
3. **Automatic reconciliation** (planned: periodic nvidia-smi sync)
4. **Graceful swap** between configurations (default ↔ reasoning)

## Next Steps

1. **CRITICAL**: Implement reconciliation loop in ResourceManager that syncs with nvidia-smi
2. Add optillm dynamic configuration via engine (not gunicorn config)
3. Create BDD scenarios for pre-flight checks in `features/preflight.feature`
4. Add `/preflight` CLI command for quick system validation
5. Integrate with CI pipeline for pre-merge validation

## The "Pre-flight" Command

```bash
# Quick system check before starting work
uv run gaius-cli --cmd "/preflight"

# Expected output:
# [PASS] PostgreSQL responsive
# [PASS] Qdrant healthy
# [PASS] MinIO buckets accessible
# [PASS] NiFi API responsive
# [PASS] Engine gRPC listening on 50051
# [PASS] optillm routing to local vLLM
# [PASS] GPU 0-3 loaded with models
# [PASS] GPU 4-5 available for reasoning swap
#
# Pre-flight complete: 8/8 checks passed
```
