"""OSM - Operational Scenario Model for RASE.

The Operational Scenario Model represents BDD features and scenarios as
executable behavior specifications. This maps directly to SysML v2:

    package RASE_NiFi::OSM {
        action def Given_NiFiIsRunning { ... }
        action def Scenario_CreateBasicFlow { ... }
    }

Key concepts:
- Feature: A collection of related scenarios (maps to .feature file)
- Scenario: A composite action sequence (Given/When/Then)
- Step: An atomic action with preconditions and effects
- StepDef: Reusable step pattern that can be parameterized

The OSM serves two purposes:
1. Executable specification: Steps can be executed against real systems
2. Requirement source: Steps derive VM requirements for verification

This is "BDD as the authoritative scenario model" - feature files are
the controlling specification, not just tests.
"""

from .scenario import (
    StepType,
    StepDef,
    StepUsage,
    Scenario,
    Feature,
    Background,
    ScenarioOutline,
    Examples,
)
from .registry import StepRegistry, step_def, given, when, then

__all__ = [
    # Core types
    "StepType",
    "StepDef",
    "StepUsage",
    "Scenario",
    "Feature",
    "Background",
    "ScenarioOutline",
    "Examples",
    # Registry
    "StepRegistry",
    "step_def",
    "given",
    "when",
    "then",
]
