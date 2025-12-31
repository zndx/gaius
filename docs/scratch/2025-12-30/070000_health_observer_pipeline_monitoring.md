# HealthObserverService Pipeline Monitoring

## Summary

Added pipeline backlog detection to the HealthObserverService, enabling ACP escalation when the content pipeline has critical backlogs.

## Changes Made

### 1. Fixed Status Comparison Bug (checker.py:556-580)

**Problem**: Health checker reported "No healthy endpoints (0/3)" even when all endpoints were healthy.

**Root Cause**: The gRPC protobuf returns `PROCESS_STATUS_HEALTHY` but checker compared against `"healthy"`.

**Fix**:
- Added `healthy_statuses = {"healthy", "PROCESS_STATUS_HEALTHY"}` set for comparison
- Also added normalization in `grpc_client.py` to convert protobuf enum names to simple strings at the client layer

### 2. Added Pipeline Monitoring to HealthObserverService

**Problem**: HealthObserverService only monitored GPU health and vLLM endpoints. Pipeline backlogs (1458 items waiting for LLM triage) were never detected or escalated.

**Architecture Fix**:
- Removed circular dependency attempt (HealthObserverService -> HealthChecker -> gRPC -> Engine)
- Added direct database query for pipeline status via `self._db_pool`
- Pipeline check queries `v_pipeline_status` view directly

**New Method**: `_check_pipeline_backlog()` in `health_observer_service.py`
- Queries `v_pipeline_status` for backlogs exceeding critical threshold
- Creates PIPELINE_001 incidents with proper fingerprinting
- Returns FAIL status for critical backlogs, WARN for warning thresholds

### 3. Added PIPELINE_001 Remediation Handler

**File**: `health_observer_service.py:_tier0_remediate()`

Pipeline backlogs are capacity issues, not restartable services. Tier 0 returns False immediately, allowing escalation to ACP for analysis.

### 4. Created KB Heuristic

**File**: `build/dev/current/heuristics/gaius/pipeline/stage_backlog.md`

Documents PIPELINE_001 failure mode:
- Symptom, Cause, Observation, Solution
- FMEA mapping (S=5, O=6, D=3, RPN=90)

### 5. Wired GPU Metrics to HealthStream

**File**: `server.py:_collect_health_metrics()`

Replaced placeholder implementation with actual metrics collection:
- GPU metrics from HealthService.get_gpu_health()
- Endpoint metrics from OrchestratorService.get_status()
- Evolution daemon status

### 6. Added gpu_detailed Handler to gRPC Client

**File**: `grpc_client.py:_call_health()`

Added handler for `gpu_detailed` action that uses HealthStream to get GPU metrics.

## Verification

After engine restart, the HealthObserverService immediately:
1. Detected pipeline backlog: `PIPELINE_001:pipeline_llm_triage`
2. Created incident
3. Attempted Tier 0 remediation (returned False - capacity issue)
4. Escalated to Tier 1 (returned False)
5. Escalated to Tier 2 (connected to ACP/Claude Code)

```
06:50:04 [INFO] gaius.engine.server: HealthObserver connected to shared db_pool for pipeline monitoring
06:50:04 [INFO] gaius.engine.services.health_observer_service: Created incident 83c4a772-bba8-4e49-a0b7-df89ca25e351: PIPELINE_001:pipeline_llm_triage (RPN=125, tier=0)
06:50:04 [INFO] gaius.engine.services.health_observer_service: Escalating PIPELINE_001:pipeline_llm_triage to tier 2
06:50:17 [INFO] gaius.acp.client: ACP connected, session_id=e1aec923-7333-4d02-9295-5bb749a261b5
```

## Files Changed

- `src/gaius/health/checker.py` - Status comparison fix
- `src/gaius/client/grpc_client.py` - Status normalization + gpu_detailed handler
- `src/gaius/engine/services/health_observer_service.py` - Pipeline monitoring + PIPELINE_001 handler
- `src/gaius/engine/server.py` - db_pool instance variable + HealthMetrics collection
- `build/dev/current/heuristics/gaius/pipeline/stage_backlog.md` - New KB heuristic
