"""SSM - System State Model for RASE.

The System State Model represents the "ground truth" state of the system
under test (NiFi) as a typed graph. This is the authoritative model that
verification cases check against.

Package structure mirrors SysML v2:
    package RASE_NiFi::SSM {
        part def NiFiInstance { ... }
        part def ProcessorGroup { ... }
        constraint def GroupExists { ... }
    }

Key concepts:
- NiFiInstance: Top-level container (the NiFi cluster/instance)
- ProcessorGroup: Container for processors and connections
- Processor: A data processing node with type and configuration
- FlowConnection: Edge between processors with relationship routing
- Constraint: Declarative predicate over system state

The SSM is "API truth" - it represents what the NiFi REST API reports,
which is the oracle for verification against UI-based agent actions.
"""

from .nifi import (
    NiFiInstance,
    ProcessorGroup,
    Processor,
    ControllerService,
    FlowConnection,
    ProcessorState as ProcessorRunState,
    SystemState,
)
from .constraints import (
    Constraint,
    ConstraintResult,
    GroupExists,
    ProcessorExists,
    ConnectionExists,
    ProcessorHasType,
    ProcessorHasProperty,
    FlowIsEquivalent,
    AllProcessorsRunning,
    NoBackpressure,
    CompositeConstraint,
    AllOf,
    AnyOf,
    Not,
    TransitionConstraint,
    ProcessorCreated,
    ConnectionCreated,
)

__all__ = [
    # Core state model
    "NiFiInstance",
    "ProcessorGroup",
    "Processor",
    "ControllerService",
    "FlowConnection",
    "ProcessorRunState",
    "SystemState",
    # Constraints
    "Constraint",
    "ConstraintResult",
    "GroupExists",
    "ProcessorExists",
    "ConnectionExists",
    "ProcessorHasType",
    "ProcessorHasProperty",
    "FlowIsEquivalent",
    "AllProcessorsRunning",
    "NoBackpressure",
    "CompositeConstraint",
    "AllOf",
    "AnyOf",
    "Not",
    # Transition constraints
    "TransitionConstraint",
    "ProcessorCreated",
    "ConnectionCreated",
]
