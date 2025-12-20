# RASE Metamodel Implementation Complete

## Summary

Implemented a Python-native metamodel for **RASE (Rapid Agentic Systems Engineering)** using Pydantic, following SysML v2 semantics without external tooling dependencies.

## Package Structure

```
src/gaius/rase/
├── __init__.py           # Top-level exports
├── traceability.py       # TraceableId, DigitalThread, TraceabilityGraph
├── ssm/                  # System State Model
│   ├── __init__.py
│   ├── nifi.py          # NiFiInstance, ProcessorGroup, Processor, FlowConnection
│   └── constraints.py   # Constraint, GroupExists, ProcessorExists, FlowIsEquivalent, ...
├── osm/                  # Operational Scenario Model
│   ├── __init__.py
│   ├── scenario.py      # Scenario, Feature, StepUsage, StepType
│   └── registry.py      # StepRegistry, @given, @when, @then decorators
├── uom/                  # UI Observation Model
│   ├── __init__.py
│   ├── marks.py         # Mark, BoundingBox, ScreenshotWithSoM, SoMGenerator
│   └── traces.py        # UIAction, ActionFrame, TraceOfMarks, TraceRecorder
└── vm/                   # Verifier Model
    ├── __init__.py
    ├── requirements.py  # Requirement, StepRequirement, ScenarioRequirement
    ├── verification.py  # VerdictKind, VerificationCase, VerificationResult
    └── oracle.py        # Oracle, NiFiOracle, RewardStrategy, BinaryReward, GradedReward
```

## Four Coupled Models

### 1. OSM (Operational Scenario Model)
BDD scenarios as executable behavior specifications:
- `Scenario`: Composite action sequence (Given/When/Then steps)
- `Feature`: Collection of related scenarios
- `StepDef`: Reusable step patterns with constraints
- `StepRegistry`: Decorator-based registration (@given, @when, @then)

### 2. SSM (System State Model)
NiFi as typed graph (API ground truth):
- `NiFiInstance`: Top-level NiFi representation
- `ProcessorGroup`: Container with processors, connections, child groups
- `Processor`: Data processing node with type, properties, run state
- `FlowConnection`: Edge between processors with relationship routing
- `Constraint`: Declarative predicates (GroupExists, ProcessorExists, FlowIsEquivalent, ...)
- `TransitionConstraint`: Before/after verification (ProcessorCreated, ConnectionCreated)

### 3. UOM (UI Observation Model)
Screenshots with SoM/ToM grounding:
- `Mark`: Bounding box with ID, role, and SSM grounding
- `ScreenshotWithSoM`: Screenshot with mark annotations
- `UIAction`: Typed action targeting a mark ID
- `TraceOfMarks`: Sequence of action frames for training
- `TraceRecorder`: Context manager for recording traces

### 4. VM (Verifier Model)
Requirements + verification (RLVR oracle):
- `Requirement`: Base with assume/require constraints
- `ScenarioRequirement`: Groups step requirements with invariants
- `VerificationCase`: API or UI-based verification
- `VerdictKind`: PASS/FAIL/INCONCLUSIVE/ERROR
- `VerificationResult`: Verdict with accuracy and evidence
- `Oracle`: Ground-truth verification using API
- `RewardStrategy`: Binary, graded, stepwise, trajectory shaping

## Traceability Spine

`TraceableId` provides URI-based identifiers linking all artifacts:
```
bdd://features/basic_flows.feature#Scenario:CreateFlow
nifi://root/BasicFlow/GetFile
som://screenshot_001#mark_3
rase://verify_CreateFlow
```

`DigitalThread` captures complete provenance:
- Requirement → Verification Case → Result
- Before/After state snapshots
- UI trace and screenshots
- Reward outcome

## Key Design Decisions

1. **Pydantic models with frozen=True**: Immutable data structures for safe concurrent use
2. **Semantic comparison**: Match by name/type, not UUID/position
3. **Compositional constraints**: AllOf, AnyOf, Not for complex specifications
4. **Partial credit**: Graded rewards from constraint accuracy (0-1)
5. **Two verification modes**: API (oracle) and UI (training target)

## Usage Example

```python
from gaius.rase import (
    TraceableId, DigitalThread,
    NiFiInstance, ProcessorGroup, Processor, ProcessorExists,
    Scenario, StepType, StepUsage,
    ScreenshotWithSoM, Mark, TraceOfMarks, UIAction,
    ScenarioRequirement, VerdictKind, NiFiOracle, GradedReward,
)

# Create scenario requirement from OSM
scenario_req = ScenarioRequirement.from_scenario(scenario, "basic_flows")

# Verify against current state
oracle = NiFiOracle(nifi_client=client, reward_strategy=GradedReward())
result, reward = await oracle.verify_and_reward(scenario_req)

# Create digital thread for lineage
thread = DigitalThread(
    requirement_id=scenario_req.id,
    verification_case_id=result.case_id,
    verification_result_id=result.id,
    reward_outcome=reward,
)
```

## Next Steps

1. **Integration with NiFi client**: Connect `NiFiOracle` to actual NiFi REST API
2. **BDD parser**: Parse `.feature` files into OSM `Feature` objects
3. **SoM generator**: Implement computer vision or accessibility-based mark detection
4. **Training pipeline**: Generate ToM datasets for Magma-style agent training
5. **RLVR loop**: Connect verification results to model training
