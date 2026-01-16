# ACP Incident Resolution: 2026-01-01

*A milestone in autonomous self-healing: Claude Code resolves GPU allocation conflicts using Gaius MCP tools.*

## Overview

On January 1, 2026, the Gaius HealthObserver daemon detected GPU memory exhaustion and escalated to Claude Code via the Agent Client Protocol (ACP). This document captures the complete investigation and resolution session, demonstrating the first successful end-to-end ACP escalation workflow.

## Key Achievements

1. **Autonomous Root Cause Analysis**: Claude Code identified overlapping GPU allocations between multiple endpoints
2. **MCP Tool Integration**: Used `gpu_status`, `health_check`, and orchestrator commands via gRPC
3. **Self-Healing Validation**: Monitored recovery and verified resolution through the same tooling
4. **Multiple Incident Cascade**: Handled a follow-on incident caused by the same GPU contention pattern

---

## Incident 1: GPU_001:gpu_1_health

```
 ▐▛███▜▌   Claude Code v2.0.54
▝▜█████▛▘  Opus 4.5 · Claude Max
  ▘▘ ▝▝    ~/local/src/zndx/gaius
```

### Health Incident Context

**Fingerprint**: `GPU_001:gpu_1_health`
**Endpoint**: gpu_1_health
**Failure Mode**: GPU_001
**RPN Score**: 125 (S:5 × O:5 × D:5)
**Escalation Tier**: 2
**Attempts**: 3

### Initial State

| GPU | Memory Used | Memory % | Healthy |
|-----|-------------|----------|---------|
| 0   | 1.29 GB     | 5.4%     | ✓       |
| 1   | 23.6 GB     | 98.4%    | ✗       |
| 2   | 22.89 GB    | 95.4%    | ✓       |
| 3   | 22.89 GB    | 95.4%    | ✓       |
| 4   | 22.89 GB    | 95.4%    | ✓       |
| 5   | 0.56 GB     | 2.3%     | ✓       |

### Endpoints at Incident Time

| Endpoint      | Model                    | GPUs      | Status   | Issue                     |
|---------------|--------------------------|-----------|----------|---------------------------|
| cap_reasoning | Qwen/QwQ-32B             | [1,2,3,4] | healthy  | Consuming GPU 1           |
| orchestrator  | nvidia/Orchestrator-8B   | [0,1]     | starting | "Insufficient GPU memory" |

### Root Cause Analysis

Claude Code identified the issue immediately:

> **Root Cause**: GPU allocation conflict between two endpoints trying to use GPU 1:
>
> 1. `cap_reasoning` (Qwen/QwQ-32B) - Uses GPUs [1, 2, 3, 4], status: healthy
> 2. `orchestrator` (nvidia/Orchestrator-8B) - Uses GPUs [0, 1], status: starting with "Insufficient GPU memory"
>
> The `cap_reasoning` endpoint loaded first and consumed GPU 1's memory (~23.6 GB of 24 GB). When orchestrator tries to start on GPUs [0, 1], GPU 0 has memory available (1.29 GB used) but GPU 1 is already exhausted.

### Investigation Commands

```bash
# Check endpoint status
uv run gaius-cli --cmd "/gpu status" --format json

# Stop the stuck orchestrator
uv run gaius-cli --cmd "/gpu stop orchestrator" --format json

# Monitor recovery
uv run gaius-cli --cmd "/health gpu" --format json
```

### Resolution

After stopping the orchestrator endpoint, the scheduler automatically rebalanced:

| GPU | Before  | After   |
|-----|---------|---------|
| 0   | 5.4%    | 0.01%   |
| 1   | 98.4%   | 0.01% ✓ |
| 2   | 95.4%   | 92.2%   |
| 3   | 95.4%   | 94.3%   |
| 4   | 95.4%   | 94.3%   |
| 5   | 2.3%    | 0.01%   |

**Final State**:
- orchestrator: HEALTHY (port 8094)
- coding: HEALTHY (port 8093)
- cap_reasoning: STOPPING
- fast: STARTING (port 8095)

---

## Incident 2: VLLM_001:coding

Immediately after resolving the first incident, a second cascaded incident appeared.

### Health Incident Context

**Fingerprint**: `VLLM_001:coding`
**Endpoint**: coding
**Failure Mode**: VLLM_001
**RPN Score**: 125 (S:5 × O:5 × D:5)
**Escalation Tier**: 2
**Attempts**: 3

### Conflict Analysis

| Endpoint      | GPUs      | Status   | Memory on GPU 1  |
|---------------|-----------|----------|------------------|
| cap_reasoning | [1,2,3,4] | healthy  | 22.89 GB (95.4%) |
| orchestrator  | [0,1]     | stopping | competing        |
| coding        | [1]       | failed   | can't allocate   |
| fast          | [0]       | healthy  | -                |

### Resolution

The scheduler handled this automatically:

1. Stopped `cap_reasoning` to free GPUs [1,2,3,4]
2. Stopped `orchestrator` and `coding`
3. Cleared all GPU memory (95%+ → 0%)
4. Restarted endpoints with non-overlapping allocations

**Final State**:

| Endpoint     | Status   |
|--------------|----------|
| orchestrator | HEALTHY ✓ |
| coding       | HEALTHY ✓ |
| reasoning    | STOPPING  |
| fast         | STARTING  |

---

## Observations

### What Worked

1. **FMEA-Based Escalation**: RPN scoring correctly identified severity (125 = S:5 × O:5 × D:5)
2. **MCP Tool Chain**: All diagnostic commands worked through gRPC proxying
3. **Scheduler Self-Healing**: Automatic GPU reallocation after conflicts cleared
4. **Cascading Incident Detection**: Second incident properly tracked with separate fingerprint

### Identified Gaps

1. **GPU Overlap Detection**: Scheduler allowed conflicting GPU assignments (`cap_reasoning` and `orchestrator` both claimed GPU 1)
2. **Startup Ordering**: No precedence constraints ensured larger models claim GPUs first
3. **Runtime Validation**: GPU allocations only validated at scheduling time, not continuously

### Order 3+ RCA Observations

These connect to CP-SAT constraints in `makespan_scheduler.py`:

| Constraint | Gap Identified |
|------------|----------------|
| `GPU_MUTUAL_EXCLUSION` | Enforced at planning time, not at runtime |
| `CONTIGUITY_REQUIREMENT` | TP endpoints need contiguous GPU blocks |
| `PRECEDENCE` | Large models should claim GPUs before small ones |

---

## Significance

This incident represents a milestone in Gaius's self-healing capabilities:

1. **First Successful ACP Escalation**: HealthObserver → Claude Code → MCP tools → Resolution
2. **Closed-Loop Verification**: Claude Code verified resolution using same tools that detected the issue
3. **RCA Framework Validation**: Order 3+ observations identified scheduler constraint gaps
4. **Multi-Incident Handling**: Cascading incidents tracked and resolved in sequence

The GPU allocation conflict exposed architectural issues that led to the RCA (Root Cause Analysis) framework development, enabling future incidents to be classified as OPERATIONAL (transient) or ARCHITECTURAL (needs code fix).

---

*Captured from ACP session on 2026-01-01 04:11-04:45 UTC*
