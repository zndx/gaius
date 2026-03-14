# Four Coupled Models

The RASE metamodel consists of four tightly coupled models. They form a coherent verification framework where changes to one model often require updates to others.

## Coupling Matrix

| If you change... | Also update... |
|------------------|----------------|
| SSM (system state) | VM constraints that reference state structure |
| OSM (scenarios) | VM requirements derived from scenarios |
| UOM (marks/traces) | VM verification cases that consume traces |
| VM (verification) | Ensure reward strategies align with constraint semantics |

## SSM -- System State Model

The SSM represents the system under test as a typed graph. The primary domain is NiFi, modeled as `NiFiInstance` containing `ProcessorGroup`, `Processor`, `FlowConnection`, and `ControllerService` nodes.

```python
from gaius.rase.domains.nifi import NiFiInstance, Processor, ProcessorGroup

state = NiFiInstance(
    root_group=ProcessorGroup(id="root", name="NiFi Flow", processors=[
        Processor(id="abc", name="GetFile", type="org.apache.nifi.GetFile"),
    ])
)
```

SSM constraints are declarative, composable, and immutable. Examples: `ProcessorExists`, `AllProcessorsRunning`, `NoBackpressure`, `FlowIsEquivalent`. Compose with `AllOf`, `AnyOf`, `Not`.

## OSM -- Operational Scenario Model

The OSM captures BDD (Behavior-Driven Development) scenarios as executable specifications. Each scenario is a sequence of `Given`/`When`/`Then` steps that map to SysML v2 action definitions.

```python
from gaius.rase.osm import Scenario, StepType, StepUsage

scenario = Scenario(
    name="CreateBasicFlow",
    steps=[
        StepUsage(step_type=StepType.GIVEN, text="NiFi is running"),
        StepUsage(step_type=StepType.WHEN,  text="I create a processor group named 'ETL'"),
        StepUsage(step_type=StepType.THEN,  text="the group 'ETL' exists"),
    ],
)
```

Step definitions (`StepDef`) are reusable patterns with `{param}` placeholders. The `StepRegistry` maps step text to executable actions via `@given`, `@when`, `@then` decorators.

## UOM -- UI Observation Model

The UOM provides grounding between language and UI actions using two complementary structures:

- **SoM (Set-of-Mark)**: A `ScreenshotWithSoM` annotates a screenshot with numbered `Mark` objects, each with a `BoundingBox`, `UIRole`, and optional mapping to an SSM element.
- **ToM (Trace-of-Mark)**: A `TraceOfMarks` records a sequence of `ActionFrame` entries (click, type, scroll) referencing marks by number, forming the agent's action trajectory.

```python
from gaius.rase.uom import Mark, BoundingBox, PixelCoord, UIRole

mark = Mark(
    mark_id=1,
    bbox=BoundingBox.from_xywh(100, 200, 50, 30),
    ui_role=UIRole.BUTTON,
    label="Add Processor",
)
```

The SoM/ToM pattern enables precise UI grounding: agents reference elements by mark number rather than pixel coordinates.

## VM -- Verifier Model

The VM implements RLVR verification. It connects OSM scenarios to executable verification cases with oracle-based reward computation. See [Verification](./verification.md) for full details.

Key components:
- **Requirements**: `StepRequirement` (atomic, from a BDD step) and `ScenarioRequirement` (composite, grouping steps with invariants)
- **Verification Cases**: `APIVerificationCase` (ground truth via API) and `UIVerificationCase` (agent UI actions, final state checked via API)
- **Oracle**: `NiFiOracle` queries the NiFi REST API for authoritative state verification
- **Reward Strategies**: `BinaryReward` (sparse) and `GradedReward` (partial credit)
