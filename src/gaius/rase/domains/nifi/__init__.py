"""NiFi Domain for RASE.

Provides NiFi-specific implementations of the RASE metamodel:
- NiFiInstance: System state model implementing SystemState protocol
- NiFi constraints: Constraint[NiFiInstance] implementations
- NiFiOracle: Oracle[NiFiInstance] for verification

This domain enables MetaAgent training for NiFi flow creation.

Usage:
    from gaius.rase.domains.nifi import (
        NiFiInstance, Processor, ProcessorGroup,
        ProcessorExists, GroupExists,
        NiFiOracle,
    )

    # Create state
    state = NiFiInstance(
        base_url="http://localhost:8080",
        root=ProcessorGroup(id="root", name="root"),
    )

    # Evaluate constraint
    constraint = ProcessorExists(processor_name="GetFile")
    result = constraint.evaluate(state)

    # Use oracle
    oracle = NiFiOracle()
    verification = await oracle.verify_constraints([constraint], state)
"""

from gaius.rase.domains.base import DomainSpec
from gaius.rase.traceability import IdScheme

# State model
from .state import (
    NiFiInstance,
    Processor,
    ProcessorGroup,
    FlowConnection,
    ControllerService,
    ProcessorRunState,
    ProcessorState,  # Backward compat alias
    semantic_processor_match,
    semantic_connection_match,
    semantic_group_match,
)

# Constraints
from .constraints import (
    Constraint,
    TransitionConstraint,
    GroupExists,
    ProcessorExists,
    ConnectionExists,
    ProcessorHasType,
    ProcessorHasProperty,
    FlowIsEquivalent,
    AllProcessorsRunning,
    NoBackpressure,
    ProcessorCreated,
    ConnectionCreated,
)

# Oracle
from .oracle import NiFiOracle, CurriculumNiFiOracle

# Domain specification for registry
DOMAIN_SPEC = DomainSpec(
    name="nifi",
    state_type=NiFiInstance,
    oracle_type=NiFiOracle,
    constraints={
        "GroupExists": GroupExists,
        "ProcessorExists": ProcessorExists,
        "ConnectionExists": ConnectionExists,
        "ProcessorHasType": ProcessorHasType,
        "ProcessorHasProperty": ProcessorHasProperty,
        "FlowIsEquivalent": FlowIsEquivalent,
        "AllProcessorsRunning": AllProcessorsRunning,
        "NoBackpressure": NoBackpressure,
        "ProcessorCreated": ProcessorCreated,
        "ConnectionCreated": ConnectionCreated,
    },
    id_scheme=IdScheme.NIFI,
    features_dir="features/nifi",
    description="NiFi flow creation and management domain for MetaAgent training",
)

__all__ = [
    # Domain spec
    "DOMAIN_SPEC",
    # State model
    "NiFiInstance",
    "Processor",
    "ProcessorGroup",
    "FlowConnection",
    "ControllerService",
    "ProcessorRunState",
    "ProcessorState",
    "semantic_processor_match",
    "semantic_connection_match",
    "semantic_group_match",
    # Constraints
    "Constraint",
    "TransitionConstraint",
    "GroupExists",
    "ProcessorExists",
    "ConnectionExists",
    "ProcessorHasType",
    "ProcessorHasProperty",
    "FlowIsEquivalent",
    "AllProcessorsRunning",
    "NoBackpressure",
    "ProcessorCreated",
    "ConnectionCreated",
    # Oracle
    "NiFiOracle",
    "CurriculumNiFiOracle",
]
