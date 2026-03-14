# RASE Metamodel

RASE (Rapid Agentic Systems Engineering) is a Python-native MBSE metamodel for verifiable agent training. It implements SysML v2-like semantics using Pydantic models, without requiring external MBSE tooling.

## Core Principle: RLVR

The reward signal comes from **verifiable computation**, not human feedback or learned approximations. The verifier is a first-class artifact -- specified, reviewed, tested, and versioned alongside the agent it trains.

## Four Coupled Models

RASE consists of four tightly coupled models. Changes to one often require updates to others:

| Model | Purpose | Package |
|-------|---------|---------|
| [SSM](./rase-models.md#ssm) | System State Model -- system as typed graph | `gaius.rase.domains.nifi` |
| [OSM](./rase-models.md#osm) | Operational Scenario Model -- BDD scenarios | `gaius.rase.osm` |
| [UOM](./rase-models.md#uom) | UI Observation Model -- SoM/ToM grounding | `gaius.rase.uom` |
| [VM](./rase-models.md#vm) | Verifier Model -- requirements, oracle, rewards | `gaius.rase.vm` |

The [TraceableId](./traceability.md) spine links artifacts across all four models, enabling full traceability from BDD scenario to training reward.

## SysML v2 Alignment

RASE mirrors SysML v2 semantics without requiring external tooling:

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
│   ├── nifi/             # NiFi domain (state, constraints, oracle)
│   └── kb/               # Knowledge Base domain
├── traceability.py       # TraceableId, DigitalThread
├── osm/                  # Operational Scenario Model (BDD)
├── uom/                  # UI Observation Model (SoM/ToM)
└── vm/                   # Verifier Model (requirements, oracle, rewards)
```

## Safety-Critical Infrastructure

The verifier is maintained with the same rigor as production code. All constraints are immutable (`frozen=True`), return structured `ConstraintResult` objects with rich failure messages, and support declarative composition. See [Verification](./verification.md) for details on the reward computation pipeline.
