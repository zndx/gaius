# Daemon Registry Implementation

**Date:** 2025-12-30 05:15
**Updated:** 2025-12-30
**Status:** COMPLETE

## Summary

Implemented comprehensive daemon lifecycle management with FAIL-FAST semantics per the plan in `.claude/plans/playful-greeting-goldwasser.md`.

## What Was Implemented

### Part 1: Daemon Lifecycle Management (Complete)

#### 1.1 BaseDaemon Protocol (`src/gaius/engine/services/base_daemon.py`)

Created new file with:
- `DaemonCriticality` enum: CRITICAL, REQUIRED, OPTIONAL
- `EngineState` enum: STARTING, READY, DEGRADED, STOPPING
- `DaemonHealth` dataclass for health check results
- `DaemonStartupError` and `DaemonDependencyError` exceptions
- `BaseDaemon` abstract base class with required properties/methods
- Comprehensive Guru Meditation codes dictionary

#### 1.2 DaemonRegistry (`src/gaius/engine/daemon_registry.py`)

Created new file with:
- `DaemonRegistration` dataclass for tracking daemon state
- `StartupResult` dataclass for startup outcomes
- `RegistryStatus` dataclass for overall status reporting
- `DaemonRegistry` class with:
  - `register()` - register daemons with dependency ordering
  - `start_all()` - topological sort startup (Kahn's algorithm)
  - `stop_all()` - reverse order shutdown
  - `check_all_health()` - continuous health monitoring
  - `get_status()` - status reporting for gRPC/CLI

#### 1.3 Daemon Implementations

Updated existing daemons to implement `BaseDaemon`:

| Daemon | File | Criticality |
|--------|------|-------------|
| HealthObserver | `health_observer_service.py` | CRITICAL |
| Cognition | `cognition_service.py` | CRITICAL |
| Reconciliation | `reconciliation.py` | REQUIRED |

Each adds:
- `name` property
- `criticality` property
- `health_check()` method with Guru codes

#### 1.4 Engine Server Integration (`src/gaius/engine/server.py`)

- Added `_daemon_registry` attribute
- Added `_init_daemon_registry()` method for coordinated startup
- Added `_create_health_observer_daemon()`, `_create_cognition_daemon()`, `_create_reconciliation_daemon()`
- Updated `stop()` to use `_daemon_registry.stop_all()`
- Wired cross-references: `Reconciliation → HealthObserver` escalation path

### Part 2: ACP Integration (Complete)

#### 2.1 ACP Prerequisites Validation

Added `_validate_acp_prerequisites()` method in server.py:
- Checks for `~/.config/gaius/acp.conf` in standard locations
- Validates config via `load_security_config()`
- Warns if no allowed repos configured
- Logs Guru codes for configuration issues

#### 2.2 GitHub Issue Creation (`health_observer_service.py`)

Implemented via `gh` CLI for flexibility with ACP-Claude:
- `_create_github_issue()` - creates issues with sanitized content
- `_build_issue_body()` - Markdown-formatted issue body
- `_find_existing_issue()` - searches for existing open issues
- `_update_issue_recurrence()` - adds comments for recurring incidents

#### 2.3 Cadence Policy

Rate limiting to prevent runaway automation:
- `max_issues_per_day: int = 3` - max GitHub issues per 24 hours
- `_issues_created_today` counter with daily reset
- `_can_create_issue()` - checks cadence policy

### Part 3: PID Tracking (Complete)

#### 3.1 GPUAllocation Enhancement (`allocations.py`)

Added process tracking for orphan detection:
- `process_pid: Optional[int]` - tracks vLLM process PID
- `mark_active(port, pid=None)` - accepts PID on activation
- `is_process_alive()` - checks if process exists via `os.kill(..., 0)`
- `is_orphaned()` - detects active allocations with dead processes

#### 3.2 vLLM Controller Integration (`vllm_controller.py`)

Updated to pass PID when marking allocation active:
```python
allocation.mark_active(port, pid=proc.pid)
```

#### 3.3 Reconciliation PID Usage (`reconciliation.py`)

- `_get_expected_endpoints()` now uses `alloc.process_pid`
- Enables proper orphan detection for crashed processes

### Part 4: Escalation Path (Complete)

#### 4.1 Reconciliation → HealthObserver Escalation

Implemented in `reconciliation.py`:
- `set_health_observer()` - sets reference for escalation
- `_escalate_to_health_observer()` - creates synthetic incident
- Triggers after `_high_drift_threshold` (10) consecutive failures
- Creates incident at Tier 2 (ACP) for immediate escalation

#### 4.2 Wiring in Server

In `_init_daemon_registry()`:
```python
if self._reconciliation_service and self._health_observer_service:
    self._reconciliation_service.set_health_observer(self._health_observer_service)
```

## Design Decisions

1. **CRITICAL failures → DEGRADED mode**: Engine stays running so ACP-Claude can investigate. Error states are preserved for analysis.

2. **Topological startup**: Daemons start in dependency order (health_observer first, then cognition and reconciliation).

3. **Reverse shutdown**: Daemons stop in reverse order to respect dependencies.

4. **ACP not strictly required**: ACP config missing logs WARNING but doesn't fail startup (engine can function without escalation).

5. **gh CLI for GitHub**: Uses `gh issue create` for flexibility with ACP-Claude's existing GitHub workflow.

6. **PID tracking in allocation**: Enables reconciliation to detect orphaned processes (allocation active but process dead).

## Guru Meditation Codes Added

| Code | Description |
|------|-------------|
| `#DM.00000001.STARTFAIL` | Daemon failed to start |
| `#DM.00000002.HEALTHFAIL` | Health check failed |
| `#DM.00000003.TIMEOUT` | Startup timed out |
| `#DM.00000004.DEPFAIL` | Dependency not available |
| `#HO.00000001.NOTRUNNING` | HealthObserver not running |
| `#HO.00000003.STALLED` | HealthObserver poll stalled |
| `#COG.00000003.CRASHED` | Cognition task crashed |
| `#COG.00000004.STALLED` | Cognition processing stalled |
| `#RC.00000001.NOTRUNNING` | Reconciliation not running |
| `#RC.00000002.CRASHED` | Reconciliation task crashed |
| `#RC.00000003.HIGHDRIFT` | High drift with low remediation |
| `#RC.00000004.NOOBSERVER` | HealthObserver not configured for escalation |
| `#RC.00000005.ESCALATIONFAIL` | Failed to escalate to HealthObserver |
| `#ACP.00000011.NOCONFIG` | ACP config file not found |
| `#ACP.00000012.NOREPOS` | No allowed repos in ACP config |
| `#ACP.00000013.CONFIGFAIL` | ACP config validation failed |
| `#ACP.00000014.GHISSUEFAIL` | GitHub issue creation failed |
| `#ACP.00000015.CADENCEBLOCKED` | Cadence policy rate limited |

## Escalation Flow

```
Drift Detected → Reconciliation Remediates → Fails → Consecutive Failures++
                                                          ↓
                                              Threshold Exceeded (10)?
                                                          ↓ Yes
                                    Create Synthetic Incident at Tier 2
                                                          ↓
                                    HealthObserver._attempt_remediation()
                                                          ↓
                                        Tier 2: ACP Escalation
                                                          ↓
                                     Claude Code Investigation
                                                          ↓
                                     Tier 3: GitHub Issue Creation
```

## Testing

Verified via:
1. Python imports: All modules import successfully
2. DaemonRegistry unit test: Topological startup/shutdown works correctly
3. CLI health checks: Daemon health checks visible in `/health` output
4. GPUAllocation PID tracking: `is_orphaned()` correctly detects dead processes

## Files Changed

| File | Action |
|------|--------|
| `src/gaius/engine/services/base_daemon.py` | CREATE |
| `src/gaius/engine/daemon_registry.py` | CREATE |
| `src/gaius/engine/server.py` | MODIFY |
| `src/gaius/engine/services/health_observer_service.py` | MODIFY |
| `src/gaius/engine/services/cognition_service.py` | MODIFY |
| `src/gaius/engine/resources/reconciliation.py` | MODIFY |
| `src/gaius/engine/resources/allocations.py` | MODIFY |
| `src/gaius/engine/backends/vllm_controller.py` | MODIFY |
