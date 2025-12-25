# Gaius Health

Health monitoring, diagnostics, and self-healing for the Gaius platform. Implements FMEA (Failure Mode and Effects Analysis) for quantitative risk-based remediation.

## Architecture

```mermaid
graph TB
    subgraph "Detection Layer"
        HC[Health Checker]
        HEUR[Heuristics<br/>KB Rules]
        WATCH[Watcher<br/>Continuous]
    end

    subgraph "Analysis Layer"
        FMEA[FMEA Engine]
        RPN[RPN Calculation<br/>S × O × D]
        CAT[Failure Mode<br/>Catalog]
    end

    subgraph "Remediation Layer"
        SH[Self-Healing<br/>Coordinator]
        T0[Tier 0<br/>Procedural]
        T1[Tier 1<br/>Agent-Assisted]
        T2[Tier 2<br/>Approval Required]
    end

    subgraph "Learning Layer"
        LEARN[Adaptive Learner]
        HIST[Historical Data]
    end

    HC --> FMEA
    HEUR --> HC
    WATCH --> HC

    FMEA --> RPN
    CAT --> RPN
    RPN --> SH

    SH --> T0
    SH --> T1
    SH --> T2

    T0 --> LEARN
    T1 --> LEARN
    LEARN --> HIST
    HIST --> FMEA
```

## Module Structure

```
health/
├── checker.py          # Health check definitions and execution
├── heuristics.py       # KB-based diagnostic heuristics
├── watcher.py          # Continuous health monitoring
├── self_healing.py     # Tiered self-healing coordinator
├── remediation.py      # Remediation action definitions
├── service_fixes.py    # Service-specific fix strategies
└── fmea/
    ├── __init__.py
    ├── models.py       # RPNScore, FailureMode, ActionPolicy
    ├── engine.py       # FMEAEngine core
    ├── loader.py       # Health check → failure mode mapping
    └── learning.py     # Adaptive S/O/D updates
```

## FMEA (Failure Mode and Effects Analysis)

FMEA replaces simple severity classification with quantitative risk assessment using Risk Priority Numbers (Stamatis, 2003).

### Risk Priority Number

$$\text{RPN} = S \times O \times D$$

where:
- **S (Severity)**: Impact on system availability (1–10)
- **O (Occurrence)**: Probability of recurrence (1–10)
- **D (Detection)**: Ability to detect before impact (1–10, lower is better)

Maximum RPN = 1000 (10 × 10 × 10).

### Action Thresholds

| RPN Range | Tier | Action |
|-----------|------|--------|
| 1–100 | Tier 0 | Automatic procedural remediation |
| 101–200 | Tier 1 | Agent-assisted remediation |
| 201–400 | Tier 2 | Requires user approval |
| 401–1000 | Manual | Human intervention required |

### Conservative Overrides

Certain conditions always escalate to higher tiers:
- Detection $D \geq 8$: Poor observability requires approval
- `SafetyLevel.DESTRUCTIVE`: Data-modifying actions require approval
- Multiple correlated failures: Escalate to next tier

### Failure Mode Catalog

34 failure modes across 7 categories:

**GPU (6 modes)**:
| ID | Failure Mode | S | O | D | RPN |
|----|--------------|---|---|---|-----|
| GPU_001 | Memory Exhaustion | 8 | 6 | 4 | 192 |
| GPU_002 | Temperature Critical | 9 | 3 | 2 | 54 |
| GPU_003 | Hardware Error | 10 | 2 | 3 | 60 |
| GPU_004 | Driver Crash | 8 | 3 | 4 | 96 |
| GPU_005 | Memory Fragmentation | 7 | 5 | 4 | 140 |
| GPU_006 | Power Throttling | 5 | 4 | 3 | 60 |

**vLLM Endpoint (6 modes)**:
| ID | Failure Mode | S | O | D | RPN |
|----|--------------|---|---|---|-----|
| VLLM_001 | Stuck Starting | 6 | 5 | 5 | 150 |
| VLLM_002 | Stuck Stopping | 4 | 4 | 4 | 64 |
| VLLM_003 | Health Check Failure | 7 | 6 | 3 | 126 |
| VLLM_004 | Orphan Process | 5 | 5 | 4 | 100 |
| VLLM_005 | OOM Crash | 8 | 5 | 3 | 120 |
| VLLM_006 | KV-Cache Exhaustion | 5 | 6 | 5 | 150 |

**Model Quality (5 modes)**:
| ID | Failure Mode | S | O | D | RPN |
|----|--------------|---|---|---|-----|
| MQ_001 | Hallucination Increase | 7 | 4 | 6 | 168 |
| MQ_002 | Latency Degradation | 4 | 5 | 3 | 60 |
| MQ_003 | Output Quality Drift | 5 | 6 | 7 | 210 |
| MQ_004 | Semantic Drift | 6 | 4 | 8 | 192 |
| MQ_005 | Context Exhaustion | 6 | 5 | 4 | 120 |

**Emergent Behavior (4 modes)**:
| ID | Failure Mode | S | O | D | RPN |
|----|--------------|---|---|---|-----|
| EB_001 | Swarm Consensus Failure | 6 | 4 | 6 | 144 |
| EB_002 | Cognition Loop | 5 | 4 | 7 | 140 |
| EB_003 | Embedding Drift | 6 | 5 | 8 | 240 |
| EB_004 | Self-Observation Bias | 6 | 5 | 9 | 270 |

Note: Emergent behavior modes have high Detection scores (poor observability), reflecting the difficulty of detecting these failure modes automatically.

## Self-Healing System

### 3-Tier Architecture

```mermaid
sequenceDiagram
    participant HC as Health Check
    participant FMEA as FMEA Engine
    participant SH as Self-Healer
    participant T0 as Tier 0
    participant T1 as Tier 1
    participant T2 as Tier 2

    HC->>FMEA: Detect Issue
    FMEA->>FMEA: Calculate RPN
    FMEA->>SH: Issue + RPN Score

    alt RPN < 100
        SH->>T0: Procedural restart
        T0-->>SH: Result
    else RPN 100-200
        SH->>T1: Agent intervention
        T1-->>SH: Result
    else RPN > 200
        SH->>T2: Queue for approval
        T2-->>SH: Pending
    end

    SH-->>FMEA: Record outcome
```

### Tier 0: Procedural Restart

Code-only remediation without agent involvement:

```python
async def tier0_restart(self, issue: HealthIssue) -> HealingResult:
    """Simple restart sequence."""
    await self.orchestrator.stop_endpoint(issue.endpoint)
    await asyncio.sleep(5)  # Cool-down period
    await self.orchestrator.start_endpoint(issue.endpoint)
    return HealingResult(success=True, tier=0, action="restart")
```

### Tier 1: Agent-Assisted

Uses healthy endpoints to diagnose and remediate:

```python
async def tier1_agent(self, issue: HealthIssue) -> HealingResult:
    """Agent-assisted recovery."""
    diagnosis = await self.inference.analyze(issue.to_dict())

    if diagnosis.action == "clear_cache":
        await self.clear_kv_cache(issue.endpoint)
    elif diagnosis.action == "rollback":
        await self.rollback_config(issue.endpoint)

    return HealingResult(success=True, tier=1, action=diagnosis.action)
```

### Tier 2: Approval Required

Creates approval record for user review:

```python
async def tier2_escalate(self, issue: HealthIssue, rpn: RPNScore) -> HealingResult:
    """Escalate for user approval."""
    approval_id = await self.db.insert_approval_request(
        failure_mode_id=rpn.failure_mode_id,
        rpn_score=rpn.rpn,
        recommended_action=self.get_recommended_action(rpn),
    )
    return HealingResult(
        success=False,
        tier=2,
        action="pending_approval",
        approval_id=approval_id,
    )
```

## Adaptive Learning

### S/O/D Score Updates

The adaptive learner adjusts base scores based on remediation outcomes using exponential moving average:

$$S_{\text{new}} = (1 - \alpha) \cdot S_{\text{current}} + \alpha \cdot S_{\text{target}}$$

where $\alpha = 0.2$ (learning rate).

```python
class AdaptiveLearner:
    LEARNING_RATE = 0.2

    async def update_from_outcome(
        self,
        failure_mode_id: str,
        rpn_score: RPNScore,
        outcome: HealingResult,
    ) -> None:
        # Update Occurrence based on success rate
        if outcome.success and outcome.duration_ms < 30000:
            new_o = self._ema(rpn_score.occurrence, target=3)
        elif not outcome.success:
            new_o = self._ema(rpn_score.occurrence, target=8)

        # Update Detection based on discovery method
        if outcome.detected_by == "user_report":
            new_d = min(10, rpn_score.detection + 1)
        elif outcome.lead_time_seconds > 300:
            new_d = max(1, rpn_score.detection - 1)

        await self._save_adjustment(failure_mode_id, new_s, new_o, new_d)
```

## Health Check Categories

| Category | Checks | Purpose |
|----------|--------|---------|
| Infrastructure | grpc_connection, postgresql, qdrant, minio | Core service connectivity |
| GPU | gpu_memory, gpu_temperature | Hardware health |
| Endpoints | endpoints, stuck_endpoints, stale_processes | vLLM/optillm health |
| Evolution | evolution_daemon, cognition_daemon | Background services |
| Resources | disk_space, scheduler_queue, xai_budget | Resource limits |

## CLI Commands

```bash
# FMEA summary
uv run gaius-cli --cmd "/fmea" --format json

# List failure modes
uv run gaius-cli --cmd "/fmea catalog" --format json

# Show failure mode details
uv run gaius-cli --cmd "/fmea detail GPU_001" --format json

# Recent incidents
uv run gaius-cli --cmd "/fmea history" --format json

# Approve pending remediation
uv run gaius-cli --cmd "/fmea approve <id>" --format json

# General health check
uv run gaius-cli --cmd "/health check" --format json
```

## Database Schema

```sql
-- Failure mode catalog
CREATE TABLE fmea_catalog (
    failure_mode_id VARCHAR(32) PRIMARY KEY,
    category VARCHAR(32) NOT NULL,
    name VARCHAR(128) NOT NULL,
    base_severity INT CHECK (base_severity BETWEEN 1 AND 10),
    base_occurrence INT CHECK (base_occurrence BETWEEN 1 AND 10),
    base_detection INT CHECK (base_detection BETWEEN 1 AND 10),
    recommended_actions TEXT[],
    preventive_controls TEXT[],
    detective_controls TEXT[],
    mitigative_controls TEXT[]
);

-- Occurrence history (for O calculation)
CREATE TABLE fmea_occurrences (
    id SERIAL PRIMARY KEY,
    failure_mode_id VARCHAR(32) REFERENCES fmea_catalog,
    occurred_at TIMESTAMPTZ DEFAULT NOW(),
    endpoint VARCHAR(64),
    context JSONB
);

-- Remediation outcomes (for learning)
CREATE TABLE fmea_outcomes (
    id SERIAL PRIMARY KEY,
    failure_mode_id VARCHAR(32) REFERENCES fmea_catalog,
    rpn_score INT NOT NULL,
    severity INT, occurrence INT, detection INT,
    action_taken VARCHAR(128),
    success BOOLEAN,
    duration_ms INT,
    downtime_seconds INT
);
```

## References

- Stamatis, D. H. (2003). *Failure Mode and Effect Analysis: FMEA from Theory to Execution*. ASQ Quality Press.

## Call Graph

```
# Health Check Path
mcp_server.py:aiops_report()
  └─→ health.checker.HealthChecker.run_all()
      ├─→ check_grpc_connection()
      ├─→ check_postgresql()
      ├─→ check_qdrant()
      ├─→ check_gpu_memory()
      ├─→ check_endpoints()
      └─→ check_evolution_daemon()

# FMEA Calculation Path
health.checker.HealthChecker.diagnose()
  └─→ fmea.engine.FMEAEngine.calculate_rpn()
      ├─→ fmea.loader.map_check_to_failure_mode()
      ├─→ fmea.catalog.get_base_scores(failure_mode_id)
      └─→ fmea.learning.AdaptiveLearner.get_adjustments()
          └─→ RPN = S × O × D

# Self-Healing Path
health.watcher.HealthWatcher.on_issue()
  └─→ health.self_healing.SelfHealer.heal()
      ├─→ fmea.engine.calculate_rpn(issue)
      ├─→ [RPN < 100] tier0_restart(issue)
      ├─→ [RPN 100-200] tier1_agent(issue)
      └─→ [RPN > 200] tier2_escalate(issue)
          └─→ database.insert(fmea_approvals)

# Fix Strategy Path
cli.py:/health fix <service>
  └─→ health.service_fixes.apply_fix(service)
      └─→ SERVICE_STRATEGIES[service].execute()
          └─→ multi-step remediation with verification
```

## Data Flow

```mermaid
flowchart TB
    DETECT["Detection Sources<br/>Scheduled Checks | Continuous Watcher | User Reports"]
    HC["HealthChecker<br/>run_all() → list[HealthIssue]"]
    FMEA["FMEA Engine<br/>calculate_rpn() → RPNScore(severity, occurrence, detection)"]
    T0["Tier 0<br/>Procedural<br/>(RPN<100)"]
    T1["Tier 1<br/>Agent-Assisted<br/>(RPN 100-200)"]
    T2["Tier 2<br/>Approval<br/>(RPN>200)"]
    LEARN["Adaptive Learner<br/>update S/O/D from outcomes → PostgreSQL"]

    DETECT --> HC
    HC --> FMEA
    FMEA --> T0
    FMEA --> T1
    FMEA --> T2
    T0 --> LEARN
    T1 --> LEARN
    T2 --> LEARN
```

## ACP Escalation (Claude Code Integration)

When the self-healing system encounters issues beyond its capability, it can
escalate to Claude Code via the Agent Client Protocol (ACP). This enables
**meta-level maintenance**—Claude Code evolves the `/health fix` framework
itself rather than just fixing individual issues.

### HealthObserver Daemon

The `HealthObserver` daemon (`observe.py`) provides continuous health monitoring
with ACP escalation:

```python
from gaius.health.observe import HealthObserver

observer = HealthObserver()
await observer.start()  # Begins continuous monitoring
```

**Features**:
- Configurable poll interval (default 60s)
- FMEA/RPN-based incident prioritization
- Automatic escalation when RPN exceeds threshold
- Incident tracking with healing history
- GitHub issue integration via ACP

### ACP Escalation Flow

```mermaid
sequenceDiagram
    participant HO as HealthObserver
    participant FMEA as FMEA Engine
    participant SH as Self-Healer
    participant ACP as ACP Client
    participant CC as Claude Code

    HO->>FMEA: Detect issue, calculate RPN
    FMEA-->>HO: RPN > 300 (high risk)

    alt Self-healing attempted
        HO->>SH: Try local fix
        SH-->>HO: Failed after 3 attempts
    end

    HO->>ACP: Escalate incident
    ACP->>CC: Connect via claude-code-acp

    CC->>CC: Analyze with MCP tools
    CC->>CC: Identify framework gap

    alt Gap found
        CC->>CC: Implement FixStrategy
        CC->>CC: Add KB heuristic
        CC->>CC: Commit to acp-claude/health-fix
    end

    CC-->>ACP: Resolution report
    ACP-->>HO: Mark incident resolved
```

### Escalation Triggers

| Condition | Threshold | Action |
|-----------|-----------|--------|
| High RPN score | RPN > 300 | Escalate to ACP |
| Repeated failures | 3+ failed attempts | Escalate to ACP |
| Unknown failure mode | No matching FMEA | Escalate to ACP |
| Manual request | User `/health escalate` | Escalate to ACP |

### ACP Workflow Modes

| Mode | Purpose |
|------|---------|
| `OBSERVE` | Diagnose issue, identify framework gaps |
| `INTERVENE` | Implement fixes, create heuristics |
| `REPORT` | Generate coverage analysis |

### Security

ACP escalation enforces mandatory security checks:
- GitHub repo must be in HOCON allowlist
- Repo must have private visibility
- Content is sanitized before issue creation
- All changes go to `acp-claude/health-fix` branch

See [ACP README](../acp/README.md) for full security documentation.

## Integration Points

| Component | Uses | Used By | Integration |
|-----------|------|---------|-------------|
| `HealthChecker` | client, database, pynvml | watcher, mcp_server | `run_all()`, `diagnose()` |
| `FMEAEngine` | fmea.catalog, fmea.learning | checker, self_healing | `calculate_rpn()` |
| `SelfHealer` | orchestrator, inference, database | watcher | `heal()` |
| `AdaptiveLearner` | database | fmea.engine | `update_from_outcome()` |
| `SERVICE_STRATEGIES` | various services | cli, mcp_server | `/health fix <service>` |
| `HealthObserver` | health, acp, database | mcp_server | `start()`, `stop()` |
| `GaiusACPClient` | claude-code-acp | HealthObserver | `prompt()` |

## See Also

- [Parent README](../README.md) — Module overview
- [Engine README](../engine/README.md) — Orchestrator integration
- [Client README](../client/README.md) — Health proxy
- [Observability README](../observability/README.md) — Metrics for health

---

<!-- GAI:META
module: gaius.health
layer: L5-orchestration
key_types: [HealthChecker, HealthIssue, FMEAEngine, RPNScore, FailureMode, SelfHealer, HealingResult, AdaptiveLearner]
key_funcs: [run_all_checks, diagnose, calculate_rpn, heal, apply_fix]
submodules: [fmea]
depends: [client, storage.database, engine.orchestrator, pynvml]
dependents: [mcp_server, engine.services.health_service, cli]
config_keys: [health.check_interval, health.fmea.learning_rate, health.self_healing.enabled]
env_vars: []
grpc_services: []
postgres_tables: [fmea_catalog, fmea_occurrences, fmea_outcomes, fmea_approvals]
external_deps: [pynvml, asyncpg]
call_paths:
  check: mcp.aiops_report→HealthChecker.run_all→[checks]→list[HealthIssue]
  fmea: HealthChecker.diagnose→FMEAEngine.calculate_rpn→RPNScore
  heal: HealthWatcher.on_issue→SelfHealer.heal→tier0|tier1|tier2
  fix: cli./health_fix→service_fixes.apply_fix→FixStrategy.execute
test_cmds:
  health: 'uv run gaius-cli --cmd "/health" --format json'
  fmea: 'uv run gaius-cli --cmd "/fmea" --format json'
guru_codes: [HL.00001.GRPC_DOWN, HL.00002.GPU_OOM, HL.00003.STUCK_ENDPOINT]
fail_fast: true
-->
