"""RASE - Rapid Agentic Systems Engineering.

A Python-native metamodel for MBSE + agentic synthesis with verifiable
closed-loop learning. Implements SysML v2-like semantics in Pydantic.

Core Principle: RLVR (Reinforcement Learning with Verifiable Reward)
    The reward signal comes from verifiable computation, not human
    feedback or learned approximations. The verifier is a first-class
    artifact—specified, reviewed, tested, and versioned.

Four Coupled Models:
    1. OSM (Operational Scenario Model): BDD scenarios as executable specs
    2. SSM (System State Model): System as typed graph (API truth)
    3. UOM (UI Observation Model): Screenshots with SoM/ToM grounding
    4. VM (Verifier Model): Requirements + verification (RLVR oracle)

Package Structure (v2 - Domain-Based):
    gaius/rase/
    ├── core/                 # Domain-agnostic abstractions
    │   ├── state.py         # SystemState protocol, S TypeVar
    │   ├── constraints.py   # Generic Constraint[S], composites
    │   └── vm.py            # Generic Oracle[S], VerdictKind, rewards
    ├── domains/              # Domain-specific implementations
    │   ├── base.py          # DomainSpec, DomainRegistry
    │   └── nifi/            # NiFi domain
    │       ├── state.py     # NiFiInstance, Processor, etc.
    │       ├── constraints.py  # NiFi constraints
    │       └── oracle.py    # NiFiOracle
    ├── traceability.py      # TraceableId, DigitalThread
    ├── ssm/                  # Legacy SSM (backward compat)
    ├── osm/                  # Operational Scenario Model
    ├── uom/                  # UI Observation Model
    └── vm/                   # Legacy VM (backward compat)

Example:
    # New style - use domains
    from gaius.rase.core import SystemState, Constraint, Oracle
    from gaius.rase.domains.nifi import NiFiInstance, ProcessorExists, NiFiOracle

    # Legacy style - still works
    from gaius.rase import (
        TraceableId, DigitalThread,
        NiFiInstance, ProcessorGroup, Processor,
        Scenario, Feature, StepType,
        ScreenshotWithSoM, TraceOfMarks,
        ScenarioRequirement, VerdictKind, NiFiOracle,
    )
"""

# --- Core Abstractions (new) ---
from .core import (
    SystemState,
    S,
    Constraint as GenericConstraint,
    ConstraintResult,
    CompositeConstraint,
    AllOf as GenericAllOf,
    AnyOf as GenericAnyOf,
    Not as GenericNot,
    TransitionConstraint as GenericTransitionConstraint,
    Oracle as GenericOracle,
    RewardStrategy,
    BinaryReward,
    GradedReward,
    VerdictKind,
    VerificationResult,
    VerificationCase,
    VerificationObjective,
)

# --- Domain Registry ---
from .domains import DomainSpec, DomainRegistry

# --- Traceability Spine ---
from .traceability import (
    IdScheme,
    TraceableId,
    DigitalThread,
    TraceabilityGraph,
)

# --- NiFi Domain (backward compatible re-exports) ---
from .domains.nifi import (
    # State model
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
    # Constraints
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
    # Oracle
    NiFiOracle,
    CurriculumNiFiOracle,
)

# Re-export composite constraints from NiFi domain (they work generically)
from .core import AllOf, AnyOf, Not

# Alias SystemState to NiFiInstance for legacy code
# (was: SystemState = NiFiInstance in ssm/nifi.py)

# --- OSM (Operational Scenario Model) ---
from .osm import (
    # Core types
    StepType,
    StepUsage,
    Scenario,
    ScenarioOutline,
    Feature,
    Background,
    Examples,
    # Step definitions
    StepDef,
    StepRegistry,
    step_def,
    given,
    when,
    then,
)

# --- UOM (UI Observation Model) ---
from .uom import (
    # SoM (Set-of-Mark)
    PixelCoord,
    BoundingBox,
    UIRole,
    Mark,
    ScreenshotWithSoM,
    SoMGenerator,
    # ToM (Trace-of-Mark)
    UIActionType,
    UIAction,
    ActionFrame,
    TraceOfMarks,
    TraceRecorder,
)

# --- VM (Verifier Model) - Legacy imports for backward compat ---
from .vm import (
    # Requirements
    Requirement,
    StepRequirement,
    ScenarioRequirement,
    FeatureRequirement,
    derive_requirements_from_scenario,
    # Verification (use core versions where possible)
    APIVerificationCase,
    UIVerificationCase,
    VerificationRun,
    # Oracle
    Oracle,
    compute_reward,
)

__all__ = [
    # Core Abstractions
    "SystemState",
    "S",
    "GenericConstraint",
    "GenericOracle",
    "GenericTransitionConstraint",
    # Domain Registry
    "DomainSpec",
    "DomainRegistry",
    # Traceability
    "IdScheme",
    "TraceableId",
    "DigitalThread",
    "TraceabilityGraph",
    # SSM - NiFi model (from domains.nifi)
    "ProcessorRunState",
    "ProcessorState",
    "Processor",
    "ControllerService",
    "FlowConnection",
    "ProcessorGroup",
    "NiFiInstance",
    "semantic_processor_match",
    "semantic_connection_match",
    "semantic_group_match",
    # SSM - Constraints (from domains.nifi)
    "Constraint",
    "ConstraintResult",
    "CompositeConstraint",
    "TransitionConstraint",
    "GroupExists",
    "ProcessorExists",
    "ProcessorHasType",
    "ProcessorHasProperty",
    "ConnectionExists",
    "FlowIsEquivalent",
    "AllProcessorsRunning",
    "NoBackpressure",
    "AllOf",
    "AnyOf",
    "Not",
    "ProcessorCreated",
    "ConnectionCreated",
    # OSM - Scenarios
    "StepType",
    "StepUsage",
    "Scenario",
    "ScenarioOutline",
    "Feature",
    "Background",
    "Examples",
    "StepDef",
    "StepRegistry",
    "step_def",
    "given",
    "when",
    "then",
    # UOM - SoM
    "PixelCoord",
    "BoundingBox",
    "UIRole",
    "Mark",
    "ScreenshotWithSoM",
    "SoMGenerator",
    # UOM - ToM
    "UIActionType",
    "UIAction",
    "ActionFrame",
    "TraceOfMarks",
    "TraceRecorder",
    # VM - Requirements
    "Requirement",
    "StepRequirement",
    "ScenarioRequirement",
    "FeatureRequirement",
    "derive_requirements_from_scenario",
    # VM - Verification
    "VerdictKind",
    "VerificationObjective",
    "VerificationCase",
    "APIVerificationCase",
    "UIVerificationCase",
    "VerificationResult",
    "VerificationRun",
    # VM - Oracle
    "Oracle",
    "NiFiOracle",
    "CurriculumNiFiOracle",
    "RewardStrategy",
    "BinaryReward",
    "GradedReward",
    "compute_reward",
]
