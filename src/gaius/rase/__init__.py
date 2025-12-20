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

Traceability Spine:
    TraceableId links all artifacts in a digital thread from requirement
    to training sample. Mirrors SysML v2's human id <'scheme:path'>.

Package Structure:
    gaius/rase/
    ├── traceability.py      # TraceableId, DigitalThread
    ├── ssm/                  # System State Model
    │   ├── nifi.py          # NiFi as typed graph
    │   └── constraints.py   # Declarative constraints
    ├── osm/                  # Operational Scenario Model
    │   ├── scenario.py      # BDD scenarios, steps
    │   └── registry.py      # Step registry (@given, @when, @then)
    ├── uom/                  # UI Observation Model
    │   ├── marks.py         # SoM (Set-of-Mark)
    │   └── traces.py        # ToM (Trace-of-Mark)
    └── vm/                   # Verifier Model
        ├── requirements.py  # Requirements with assume/require
        ├── verification.py  # Verification cases
        └── oracle.py        # RLVR oracle

Example:
    from gaius.rase import (
        TraceableId, DigitalThread,
        NiFiInstance, ProcessorGroup, Processor,
        Scenario, Feature, StepType,
        ScreenshotWithSoM, TraceOfMarks,
        ScenarioRequirement, VerdictKind, NiFiOracle,
    )

    # Create a scenario requirement
    scenario_req = ScenarioRequirement.from_scenario(
        scenario, feature_name="basic_flows"
    )

    # Verify against current state
    oracle = NiFiOracle(nifi_client=client)
    result, reward = await oracle.verify_and_reward(scenario_req)

    # Create digital thread
    thread = DigitalThread(
        requirement_id=scenario_req.id,
        verification_case_id=result.case_id,
        verification_result_id=result.id,
        reward_outcome=reward,
    )
"""

from .traceability import (
    IdScheme,
    TraceableId,
    DigitalThread,
    TraceabilityGraph,
)

from .ssm import (
    # NiFi model
    ProcessorRunState,
    Processor,
    ControllerService,
    FlowConnection,
    ProcessorGroup,
    NiFiInstance,
    SystemState,
    # Constraints
    Constraint,
    ConstraintResult,
    CompositeConstraint,
    GroupExists,
    ProcessorExists,
    ProcessorHasType,
    ProcessorHasProperty,
    ConnectionExists,
    FlowIsEquivalent,
    AllProcessorsRunning,
    NoBackpressure,
    AllOf,
    AnyOf,
    Not,
)

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

from .vm import (
    # Requirements
    Requirement,
    StepRequirement,
    ScenarioRequirement,
    FeatureRequirement,
    derive_requirements_from_scenario,
    # Verification
    VerdictKind,
    VerificationObjective,
    VerificationCase,
    APIVerificationCase,
    UIVerificationCase,
    VerificationResult,
    VerificationRun,
    # Oracle
    Oracle,
    NiFiOracle,
    RewardStrategy,
    BinaryReward,
    GradedReward,
    compute_reward,
)

__all__ = [
    # Traceability
    "IdScheme",
    "TraceableId",
    "DigitalThread",
    "TraceabilityGraph",
    # SSM - NiFi model
    "ProcessorRunState",
    "Processor",
    "ControllerService",
    "FlowConnection",
    "ProcessorGroup",
    "NiFiInstance",
    "SystemState",
    # SSM - Constraints
    "Constraint",
    "ConstraintResult",
    "CompositeConstraint",
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
    "RewardStrategy",
    "BinaryReward",
    "GradedReward",
    "compute_reward",
]
