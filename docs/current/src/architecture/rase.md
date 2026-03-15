# RASE Metamodel

RASE (Rapid Agentic Systems Engineering) is a Python-native MBSE metamodel for verifiable agent training. It implements SysML v2-like semantics (Friedenthal et al., 2014) using Pydantic models, without requiring external MBSE tooling.

## Core Principle: RLVR

The reward signal comes from **verifiable computation**, not human feedback or learned approximations. The verifier is a first-class artifact — specified, reviewed, tested, and versioned alongside the agent it trains.

**Oracle invariant**: The oracle uses API ground truth (system state from NiFi REST API), never UI observations. UI traces (screenshots with Set-of-Mark annotations) are the *training target* — what the agent learns to produce. The oracle verifies whether the system reached the desired state, not whether the UI looked correct.

## Four Coupled Models

RASE consists of four tightly coupled models. Changes to one often require updates to others:

| Model | Purpose | Package |
|-------|---------|---------|
| [SSM](./rase-models.md#ssm) | System State Model — system as typed graph | `gaius.rase.domains.nifi` |
| [OSM](./rase-models.md#osm) | Operational Scenario Model — BDD scenarios | `gaius.rase.osm` |
| [UOM](./rase-models.md#uom) | UI Observation Model — SoM/ToM grounding | `gaius.rase.uom` |
| [VM](./rase-models.md#vm) | Verifier Model — requirements, oracle, rewards | `gaius.rase.vm` |

The [TraceableId](./traceability.md) spine links artifacts across all four models via URI-based identification (`bdd://features/basic_flows#Scenario:CreateFlow`, `nifi://root/processors/abc123`). The `DigitalThread` captures provenance relationships between artifacts.

## Constraint System

Constraints are declarative, composable, and immutable (`frozen=True`). They evaluate against a `SystemState` and return structured `ConstraintResult` objects with rich failure messages:

```python
# Atomic constraints
ProcessorExists(name="Generate Data")
ProcessorHasType(name="Generate Data", type_pattern="GenerateFlowFile")

# Composition via AllOf, AnyOf, Not
AllOf([
    ProcessorExists(name="Generate Data"),
    ProcessorHasType(name="Generate Data", type_pattern="GenerateFlowFile"),
    Not(ProcessorExists(name="Obsolete Processor")),
])
```

The constraint system is generic over `SystemState` via `Constraint[S]` — the NiFi domain provides `NiFiInstance` as the concrete state type, but the composition operators (`AllOf`, `AnyOf`, `Not`) work with any domain registered in the `DomainRegistry`.

## Reward Computation

Verification produces a `VerdictKind` (PASS, FAIL, INCONCLUSIVE, ERROR) and an accuracy score (0.0–1.0, proportion of constraints satisfied). Two reward strategies translate this into RL training signals:

| Strategy | Signal | Use Case |
|----------|--------|----------|
| `BinaryReward` | 0.0 or 1.0 | Sparse signal — all-or-nothing. Suitable when partial credit is meaningless |
| `GradedReward` | Continuous, with configurable pass_reward and fail_penalty | Dense signal with partial credit based on accuracy. Suitable for multi-constraint scenarios where incremental progress matters |

The `compute_reward()` function is the single entry point: it takes a `VerificationResult` and a reward strategy, returning a scalar suitable for policy gradient updates.

## SysML v2 Alignment

| SysML v2 Concept | RASE Implementation |
|------------------|---------------------|
| `requirement def` | `Requirement`, `ScenarioRequirement` |
| `verification def` | `VerificationCase`, `APIVerificationCase` |
| `constraint def` | `Constraint` subclasses (composable via `AllOf`, `AnyOf`, `Not`) |
| `action def` | `StepDef` with `@given`, `@when`, `@then` |
| `part def` | `Processor`, `ProcessorGroup`, `NiFiInstance` |
| Human ID `<'scheme:path'>` | `TraceableId.uri` |

## Package Structure

```
src/gaius/rase/
├── core/                 # Domain-agnostic: SystemState, Constraint[S], Oracle[S]
├── domains/              # Domain-specific implementations
│   ├── base.py           # DomainSpec, DomainRegistry
│   └── nifi/             # NiFi domain (state, constraints, oracle)
├── traceability.py       # TraceableId, DigitalThread
├── osm/                  # Operational Scenario Model (BDD)
├── uom/                  # UI Observation Model (SoM/ToM)
└── vm/                   # Verifier Model (requirements, oracle, rewards)
```

## Safety-Critical Infrastructure

The verifier is maintained with the same rigor as production code. All constraints are immutable, return structured results, and support declarative composition. The oracle is the single source of truth for reward computation — it consults the system API, not the UI observation trace. This separation ensures that UI-level errors in the training data do not corrupt the reward signal.

See [Verification](./verification.md) for the full reward computation pipeline, and [RASE Models](./rase-models.md) for detailed model documentation.
