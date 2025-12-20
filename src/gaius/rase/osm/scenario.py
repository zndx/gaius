"""OSM Scenario and Step definitions.

Provides the data structures for representing BDD scenarios as
operational behavior specifications.

Maps to SysML v2 action definitions:
    action def Given_NiFiIsRunning {
        in nifi : NiFiInstance;
    }

    action def Scenario_CreateBasicFlow {
        in nifi : NiFiInstance;
        first start;
        then perform Given_NiFiIsRunning;
        then perform When_CreateProcessorGroup;
        then done;
    }

Design:
- StepDef: Reusable step pattern (action definition)
- StepUsage: Instance of a step with bound parameters
- Scenario: Ordered sequence of step usages
- Feature: Collection of scenarios with optional background
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Callable, Awaitable, TypeVar

from pydantic import BaseModel, Field

from gaius.rase.traceability import TraceableId, IdScheme
from gaius.rase.ssm import NiFiInstance, Constraint


class StepType(str, Enum):
    """BDD step keyword types."""
    GIVEN = "Given"
    WHEN = "When"
    THEN = "Then"
    AND = "And"
    BUT = "But"
    STAR = "*"  # Gherkin allows * as neutral step

    def canonical(self) -> "StepType":
        """Get the canonical type (And/But inherit from previous step)."""
        if self in (StepType.AND, StepType.BUT, StepType.STAR):
            # In context, these inherit from the previous Given/When/Then
            # For standalone use, treat as WHEN
            return StepType.WHEN
        return self


# Type for step action functions
StepAction = Callable[..., Awaitable[None]]


class StepDef(BaseModel):
    """Reusable step definition (action def in SysML v2).

    A StepDef is a pattern that matches step text and can be executed.
    It serves as both documentation and executable specification.

    Attributes:
        id: Traceable identifier
        step_type: Given/When/Then
        pattern: Text pattern with {param} placeholders
        description: Documentation for the step
        parameters: Expected parameter names and types
        assume_constraints: Preconditions that must hold
        ensure_constraints: Postconditions that will hold after

    Example:
        StepDef(
            pattern="a processor group named {group_name}",
            step_type=StepType.GIVEN,
            parameters={"group_name": str},
        )
    """

    id: TraceableId
    step_type: StepType
    pattern: str
    description: str = ""

    # Parameter specification
    parameters: dict[str, type] = Field(default_factory=dict)

    # Contract (assume/ensure)
    assume_constraints: list[Constraint] = Field(default_factory=list)
    ensure_constraints: list[Constraint] = Field(default_factory=list)

    # Execution (set by registry)
    _action: StepAction | None = None

    model_config = {"frozen": True, "arbitrary_types_allowed": True}

    @property
    def pattern_regex(self) -> str:
        """Convert pattern to regex for matching.

        Replaces {param} with named capture groups.
        """
        import re
        # Escape regex special chars except {}
        escaped = re.escape(self.pattern)
        # Replace escaped \{param\} with named capture group
        result = re.sub(
            r'\\{(\w+)\\}',
            r'(?P<\1>.+?)',
            escaped,
        )
        return f"^{result}$"

    def matches(self, text: str) -> dict[str, str] | None:
        """Try to match step text, returning captured parameters or None."""
        import re
        match = re.match(self.pattern_regex, text, re.IGNORECASE)
        if match:
            return match.groupdict()
        return None

    def with_action(self, action: StepAction) -> "StepDef":
        """Create a new StepDef with an action bound."""
        # Create a mutable copy, set action, return frozen
        data = self.model_dump()
        new_def = StepDef(**data)
        object.__setattr__(new_def, '_action', action)
        return new_def


class StepUsage(BaseModel):
    """An instance of a step with bound parameters.

    This is a step as it appears in a scenario, with actual parameter
    values filled in.

    Attributes:
        step_def_id: Reference to the StepDef being used
        step_type: The keyword used (may be And/But)
        text: The actual step text as written
        parameters: Bound parameter values
        line_number: Line in source file (for traceability)
        doc_string: Optional doc string content
        data_table: Optional data table rows
    """

    step_def_id: TraceableId | None = None  # None if step not yet matched
    step_type: StepType
    text: str
    parameters: dict[str, Any] = Field(default_factory=dict)

    # Source location
    line_number: int = 0

    # Optional Gherkin attachments
    doc_string: str | None = None
    data_table: list[dict[str, str]] | None = None

    model_config = {"frozen": True}

    @property
    def id(self) -> TraceableId:
        """Generate traceable ID based on line number and type."""
        return TraceableId(
            scheme=IdScheme.BDD,
            path=f"step/L{self.line_number}:{self.step_type.value}",
        )


class Background(BaseModel):
    """Background steps that run before each scenario.

    Background provides common setup steps that apply to all scenarios
    in a feature.
    """

    name: str = "Background"
    steps: list[StepUsage] = Field(default_factory=list)

    model_config = {"frozen": True}


class Examples(BaseModel):
    """Examples table for scenario outlines.

    Provides data for parameterized scenario execution.
    """

    name: str = ""
    tags: list[str] = Field(default_factory=list)
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)

    model_config = {"frozen": True}

    def as_dicts(self) -> list[dict[str, str]]:
        """Convert rows to list of parameter dictionaries."""
        return [dict(zip(self.headers, row)) for row in self.rows]


class Scenario(BaseModel):
    """A BDD scenario - a sequence of steps.

    Maps to SysML v2:
        action def Scenario_X {
            first start;
            then perform Given_...;
            then perform When_...;
            then perform Then_...;
            then done;
        }

    Attributes:
        id: Traceable identifier
        name: Scenario title
        description: Optional description
        steps: Ordered list of step usages
        tags: Gherkin tags (e.g., @smoke, @wip)
    """

    id: TraceableId
    name: str
    description: str = ""
    steps: list[StepUsage] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    model_config = {"frozen": True}

    @classmethod
    def from_gherkin(
        cls,
        feature_name: str,
        name: str,
        steps: list[StepUsage],
        tags: list[str] | None = None,
        description: str = "",
    ) -> "Scenario":
        """Create scenario from Gherkin components."""
        return cls(
            id=TraceableId.from_bdd(feature_name, scenario=name),
            name=name,
            description=description,
            steps=steps,
            tags=tags or [],
        )

    @property
    def given_steps(self) -> list[StepUsage]:
        """Get all Given steps (setup)."""
        return [
            s for s in self.steps
            if s.step_type in (StepType.GIVEN, StepType.AND, StepType.BUT)
            and self._is_in_given_section(s)
        ]

    @property
    def when_steps(self) -> list[StepUsage]:
        """Get all When steps (actions)."""
        result = []
        in_when = False
        for s in self.steps:
            if s.step_type == StepType.WHEN:
                in_when = True
            elif s.step_type == StepType.THEN:
                in_when = False
            if in_when:
                result.append(s)
        return result

    @property
    def then_steps(self) -> list[StepUsage]:
        """Get all Then steps (assertions)."""
        result = []
        in_then = False
        for s in self.steps:
            if s.step_type == StepType.THEN:
                in_then = True
            if in_then:
                result.append(s)
        return result

    def _is_in_given_section(self, step: StepUsage) -> bool:
        """Check if step is in the Given section."""
        for s in self.steps:
            if s == step:
                return True
            if s.step_type == StepType.WHEN:
                return False
        return False


class ScenarioOutline(BaseModel):
    """A parameterized scenario with examples.

    Scenario outlines are templates that produce multiple scenarios
    when combined with an Examples table.
    """

    id: TraceableId
    name: str
    description: str = ""
    steps: list[StepUsage] = Field(default_factory=list)
    examples: list[Examples] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    model_config = {"frozen": True}

    def expand(self) -> list[Scenario]:
        """Expand outline into concrete scenarios."""
        scenarios = []
        for example_set in self.examples:
            for i, params in enumerate(example_set.as_dicts()):
                # Substitute parameters into step text
                expanded_steps = []
                for step in self.steps:
                    text = step.text
                    for key, value in params.items():
                        text = text.replace(f"<{key}>", value)
                    expanded_steps.append(
                        StepUsage(
                            step_type=step.step_type,
                            text=text,
                            line_number=step.line_number,
                            parameters=params,
                        )
                    )

                scenarios.append(Scenario(
                    id=TraceableId.from_bdd(
                        feature="outline",
                        scenario=f"{self.name}_{i+1}",
                    ),
                    name=f"{self.name} (Example {i+1})",
                    steps=expanded_steps,
                    tags=self.tags,
                ))
        return scenarios


class Feature(BaseModel):
    """A BDD feature - a collection of related scenarios.

    Maps to a package in SysML v2:
        package features_X {
            action def Scenario_Y { ... }
            action def Scenario_Z { ... }
        }

    Attributes:
        id: Traceable identifier
        name: Feature title
        description: Feature description/narrative
        background: Optional background steps
        scenarios: List of scenarios
        scenario_outlines: List of parameterized scenarios
        tags: Feature-level tags
        source_file: Original .feature file path
    """

    id: TraceableId
    name: str
    description: str = ""
    background: Background | None = None
    scenarios: list[Scenario] = Field(default_factory=list)
    scenario_outlines: list[ScenarioOutline] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source_file: str = ""

    model_config = {"frozen": True}

    @classmethod
    def from_file(cls, filename: str) -> "Feature":
        """Parse a .feature file into a Feature model.

        Note: This is a placeholder - actual parsing requires a
        Gherkin parser like behave.parser or gherkin-official.
        """
        # Extract feature name from filename
        name = filename.replace(".feature", "").replace("_", " ").title()
        return cls(
            id=TraceableId.from_bdd(filename),
            name=name,
            source_file=filename,
        )

    def all_scenarios(self) -> list[Scenario]:
        """Get all scenarios including expanded outlines."""
        result = list(self.scenarios)
        for outline in self.scenario_outlines:
            result.extend(outline.expand())
        return result

    def get_scenario(self, name: str) -> Scenario | None:
        """Find scenario by name."""
        for s in self.scenarios:
            if s.name == name:
                return s
        return None


__all__ = [
    "StepType",
    "StepDef",
    "StepUsage",
    "Scenario",
    "Feature",
    "Background",
    "ScenarioOutline",
    "Examples",
]
