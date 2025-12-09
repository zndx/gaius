# Health Check Remediation System Complete

## Summary

Implemented a comprehensive self-healing health check system with automated remediation capabilities.

## Changes Made

### New Files Created

1. **`src/gaius/health/remediation.py`** - Core remediation infrastructure
   - `RemediationAction`: Single action with command or Python code
   - `RemediationPlan`: Collection of actions for a service
   - `RemediationExecutor`: Executes plans with safety controls (dry-run, force)
   - `RemediationPlanner`: Creates plans from health checks and heuristics
   - `SafetyLevel` enum: SAFE, CAUTION, DESTRUCTIVE

2. **`src/gaius/health/service_fixes.py`** - Service-specific fix strategies
   - `EngineFixStrategy`: Start devenv, reset gRPC singleton
   - `PostgresFixStrategy`: Start postgres via devenv
   - `QdrantFixStrategy`: Start qdrant via devenv
   - `MinioFixStrategy`: Start minio via devenv
   - `SingletonFixStrategy`: Reset client singletons
   - `AllServicesFixStrategy`: Start all devenv services
   - `EndpointFixStrategy`: Reconcile inference endpoints via orchestrator

3. **New Heuristics in KB**:
   - `build/dev/current/heuristics/gaius/engine/engine_not_started.md`
   - `build/dev/current/heuristics/gaius/data/qdrant_not_running.md`
   - `build/dev/current/heuristics/gaius/data/minio_not_running.md`

### CLI Commands Added

- `/health diagnose [service]` - Deep diagnostic with heuristic info
- `/health fix [service] [--dry-run] [--force]` - Execute remediation

### Bug Fixes

1. **Missing proto exports**: Added `CognitionStatusResponse` and related types to `generated/__init__.py`
2. **Wrong port defaults**: Fixed Qdrant (6339) and MinIO (9010) health check ports

## Current Health Status

```
🟡 Health: 9/11 passed, 2 warnings, 0 failures

gRPC Connection: pass - Connected to engine via gRPC
Engine Endpoints: pass - All 4 endpoints healthy
optillm Service: pass - Connected at http://localhost:8080
vLLM Service: pass - All 3 endpoints available
Database Connection: pass - Connected, 42 tables in schema
Qdrant: pass - Connected, 2 collection(s)
S3/MinIO: pass - Connected at http://localhost:9010
Cognition Daemon: pass - Running, 0 cycles completed
Recent Thoughts: warn - 10 thoughts, newest is 47.7h old
GPU Memory: pass - 6 GPUs, memory OK
Disk Space: warn - Low: 90.7GB free (86% used)
```

## TUI Verification

- ThinkPanel correctly shows `engine_healthy: True`
- Info panels cycle correctly with 'g' key
- No fallbacks being used

## Design Principles

1. **devenv as baseline**: All services managed via `devenv up -d`
2. **Safety levels**: SAFE (auto-execute), CAUTION (warn), DESTRUCTIVE (require --force)
3. **Dry-run support**: Preview actions before execution
4. **Heuristic integration**: Links diagnose output to KB heuristics
5. **Singleton awareness**: Reset stale client connections after service restart
