# RASE Domain Refactoring Summary

Date: 2025-12-20

## Overview

Refactored the RASE metamodel to support multiple domains (NiFi, Metabase, TUI, Engine) while maintaining backward compatibility. This establishes the foundation for Atropos RL training and Engine Federation.

## Changes Made

### Phase 1: Core Abstractions

Created `src/gaius/rase/core/` with domain-agnostic types:

- **`state.py`**: `SystemState` protocol with `S` TypeVar
- **`constraints.py`**: Generic `Constraint[S]`, `ConstraintResult`, composites (`AllOf`, `AnyOf`, `Not`), `TransitionConstraint[S]`
- **`vm.py`**: Generic `Oracle[S]`, `VerificationCase[S]`, `VerificationResult`, reward strategies

### Phase 2: Domain Registry

Created `src/gaius/rase/domains/`:

- **`base.py`**: `DomainSpec` dataclass and `DomainRegistry` for capability-based routing
- **`nifi/`**: Complete NiFi domain implementation
  - `state.py`: `NiFiInstance`, `Processor`, `ProcessorGroup`, etc. implementing `SystemState`
  - `constraints.py`: NiFi-specific constraints (`ProcessorExists`, `GroupExists`, etc.)
  - `oracle.py`: `NiFiOracle` and `CurriculumNiFiOracle`

### Phase 3: BDD Features Reorganization

Reorganized features by domain (copy-then-delete approach):

```
features/
├── tui/          # TUI features (navigation, panels, views, etc.)
├── engine/       # Engine features (health, grpc, self-healing)
├── kb/           # KB features (operations, mcp)
├── content/      # Content features (pipeline, workflow, model library)
├── nifi/         # NiFi curriculum for MetaAgent training
│   └── curriculum/
│       ├── level0_basic.feature
│       └── level1_flows.feature
└── shared/       # Shared fixtures and steps
```

### Phase 4: Proto Definitions

Created `src/gaius/engine/proto/rase_types.proto`:

- `TraceableId`: Traceability spine message
- `VerdictKind`: Verification outcome enum
- `ConstraintResult`: Individual constraint evaluation
- `VerificationResult`: Complete verification outcome
- `DigitalThread`: Provenance chain linking requirement → verification → result → reward
- `TrainingExample` and `TrainingBatch`: Atropos training types

## Backward Compatibility

All existing imports work unchanged:

```python
# Legacy style (still works)
from gaius.rase import (
    NiFiInstance, ProcessorGroup, Processor,
    ProcessorExists, GroupExists,
    NiFiOracle, VerdictKind, compute_reward,
)

# New style (domain-aware)
from gaius.rase.core import SystemState, Constraint, Oracle
from gaius.rase.domains.nifi import NiFiInstance, ProcessorExists
from gaius.rase.domains import DomainRegistry
```

## Domain Registry Usage

```python
from gaius.rase.domains import DomainRegistry

# Auto-discover all domains
DomainRegistry.discover()

# Get domain specification
nifi_spec = DomainRegistry.get("nifi")
oracle = nifi_spec.oracle_type()

# List constraints
for name in nifi_spec.list_constraints():
    constraint_class = nifi_spec.get_constraint(name)
```

## Key Design Decisions

1. **Generic Type Parameters**: Using `Constraint[S]` and `Oracle[S]` where `S` is bound to `SystemState` protocol
2. **Structural Protocol**: `SystemState` uses `@runtime_checkable` protocol for duck typing
3. **Domain Registration**: Domains register via `DOMAIN_SPEC` attribute in their `__init__.py`
4. **BDD Curriculum**: NiFi curriculum organized by difficulty level for progressive training

## Next Steps

1. Add domain stubs for Metabase, TUI, Engine
2. Implement proto-to-Python converters for `rase_types.proto`
3. Create curriculum generator from BDD features
4. Integrate with Atropos training infrastructure
5. Implement Engine Federation for distributed verification
