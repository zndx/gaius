# GPU Orchestrator Implementation

## Overview

Implemented a complete GPU orchestrator for Gaius that enables autonomous management of vLLM instances across 6x RTX 4090 GPUs. This is the foundation for dynamic model deployment based on pending work queues.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     SchedulerService                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ GPUOrchestrator│  │GPUHealthMonitor│ │RecoveryManager│         │
│  │              │  │              │  │              │          │
│  │ - vLLM procs │  │ - pynvml     │  │ - 4 levels   │          │
│  │ - on-demand  │  │ - thresholds │  │ - patterns   │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                          │                                      │
│                    ┌──────────────┐                             │
│                    │JobPersistence│                             │
│                    │ - PostgreSQL │                             │
│                    │ - crash safe │                             │
│                    └──────────────┘                             │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. GPUOrchestrator (`src/gaius/inference/orchestrator.py`)
- Manages vLLM subprocess lifecycle with asyncio
- On-demand model loading via `ensure_model_loaded()`
- CUDA_VISIBLE_DEVICES isolation per endpoint
- Graceful shutdown with SIGTERM → SIGKILL escalation

### 2. GPUHealthMonitor (`src/gaius/inference/health.py`)
- Real-time GPU metrics via pynvml
- Tracks: VRAM usage, temperature, power, utilization
- Configurable thresholds from HOCON config
- Warning and critical alerts

### 3. RecoveryManager (`src/gaius/inference/recovery.py`)
- 4-level escalation:
  1. SOFT_RESET - Reduce load, brief cooldown
  2. WARM_RESTART - Restart process, same model
  3. COLD_RESTART - Full restart with cleanup
  4. FAILOVER - Disable endpoint, redistribute
- Error pattern matching (OOM, CUDA errors, etc.)

### 4. JobPersistence (`src/gaius/inference/persistence.py`)
- PostgreSQL job queue with asyncpg
- Crash-safe job recovery on restart
- Tracks: pending, running, completed, failed jobs

## Interface Points

### CLI Commands (`/gpu`)
```
/gpu status        - Show all endpoints and GPU health
/gpu start [name]  - Start endpoint(s)
/gpu stop [name]   - Stop endpoint(s)
/gpu restart <name> - Restart endpoint
/gpu logs <name>   - Show endpoint logs
/gpu health        - Detailed GPU metrics
```

### MCP Tools
- `orchestrator_status` - Get endpoint and health status
- `orchestrator_start` - Start vLLM endpoint
- `orchestrator_stop` - Stop vLLM endpoint
- `orchestrator_restart` - Restart endpoint
- `orchestrator_logs` - Get endpoint logs
- `gpu_health` - Detailed GPU metrics

## Configuration

Added to `config/base.conf`:
```hocon
inference.orchestrator {
  enabled = true
  auto_start = false  # On-demand only
  health_check_interval = 15
  startup_timeout = 120
  max_consecutive_failures = 3
  max_recovery_attempts = 3

  vllm {
    binary = "vllm"
    gpu_memory_utilization = 0.9
    max_model_len = 32768
  }

  thresholds {
    vram_warning_percent = 85
    vram_critical_percent = 95
    temp_warning_c = 75
    temp_critical_c = 85
  }
}
```

## Database Migration

`db/migrations/20251201000001_scheduler_jobs.sql`:
- `scheduler_jobs` table with job persistence
- Indexes for status-based queries
- Automatic retry tracking

## Dependencies

Added to `pyproject.toml`:
```toml
[project.optional-dependencies]
gpu = ["pynvml>=12.0.0"]
orchestrator = ["gaius[scheduler]", "gaius[gpu]"]
```

## Lifecycle Integration

```
app.py on_mount()
    └─> _start_scheduler()
            └─> scheduler.start()
                    └─> _init_orchestrator_components()
                            ├─> GPUOrchestrator()
                            ├─> GPUHealthMonitor()
                            ├─> RecoveryManager()
                            └─> JobPersistence()
                    └─> _restore_pending_jobs()
```

## Next Steps

1. **Gang Scheduling** - Dynamic model swapping based on job queue
2. **Model Preemption** - Unload idle models for higher-priority work
3. **Cross-GPU Load Balancing** - Distribute work across GPUs
4. **Prometheus Metrics** - Export GPU metrics for monitoring dashboards
