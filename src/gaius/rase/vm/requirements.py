"""VM Requirement definitions.

Requirements are constraints with assume/require semantics, derived from
BDD scenarios. They form the specification against which agents are verified.

Maps to SysML v2:
    requirement def BDDStepRequirement {
        subject nifi : NiFiInstance;
        assume constraint { preconditions }
        require constraint { postconditions }
    }

    requirement <'bdd:...#Scenario:X'> scn_X : BDDScenarioRequirement {
        require step_Given_...;
        require step_When_...;
        require step_Then_...;
    }

Design:
- Requirement: Base class with assume/require constraints
- StepRequirement: Atomic requirement from a single BDD step
- ScenarioRequirement: Groups step requirements with invariants
- FeatureRequirement: Groups scenarios

The requirements form a compositional verification structure where
each level can be verified independently or together.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from gaius.rase.traceability import TraceableId, IdScheme
from gaius.rase.ssm import Constraint, NiFiInstance, TransitionConstraint
from gaius.rase.osm import StepType, Scenario, Feature, StepUsage


class Requirement(BaseModel):
    """Base requirement with assume/require constraints.

    A requirement specifies:
    - assume: Conditions that must hold before the step (preconditions)
    - require: Conditions that must hold after the step (postconditions)

    Maps to SysML v2:
        requirement def X {
            subject s : Type;
            assume constraint { ... }
            require constraint { ... }
        }

    Attributes:
        id: Traceable identifier
        doc: Documentation/description
        subject_type: Type of the subject being constrained
        assume_constraints: Preconditions
        require_constraints: Postconditions
        tags: Classification tags
    """

    id: TraceableId
    doc: str = ""
    subject_type: str = "NiFiInstance"

    assume_constraints: list[Constraint] = Field(default_factory=list)
    require_constraints: list[Constraint] = Field(default_factory=list)

    # For transition verification
    transition_constraints: list[TransitionConstraint] = Field(default_factory=list)

    tags: list[str] = Field(default_factory=list)
    priority: int = 0  # Higher = more important

    model_config = {"frozen": True}

    def verify_assume(self, state: NiFiInstance) -> bool:
        """Check if all assume constraints are satisfied."""
        return all(c.evaluate(state).satisfied for c in self.assume_constraints)

    def verify_require(self, state: NiFiInstance) -> bool:
        """Check if all require constraints are satisfied."""
        return all(c.evaluate(state).satisfied for c in self.require_constraints)

    def verify_transition(
        self,
        before: NiFiInstance,
        after: NiFiInstance,
    ) -> bool:
        """Check if all transition constraints are satisfied."""
        return all(
            c.evaluate(before, after).satisfied
            for c in self.transition_constraints
        )


class StepRequirement(Requirement):
    """Atomic requirement for a single BDD step.

    Each BDD step (Given/When/Then) becomes a StepRequirement with:
    - Given steps: Primarily assume constraints (setup)
    - When steps: Transition constraints (actions)
    - Then steps: Primarily require constraints (assertions)

    Attributes:
        step_type: Given/When/Then
        step_text: The original step text
        line_number: Line in the feature file
    """

    step_type: StepType
    step_text: str
    line_number: int = 0

    # Link back to scenario
    scenario_id: TraceableId | None = None

    @classmethod
    def from_step(
        cls,
        step: StepUsage,
        feature_name: str,
        scenario_name: str,
    ) -> "StepRequirement":
        """Create a StepRequirement from a step usage."""
        return cls(
            id=TraceableId.from_bdd(
                feature_name,
                scenario=scenario_name,
                step_line=step.line_number,
                step_type=step.step_type.value,
            ),
            doc=step.text,
            step_type=step.step_type,
            step_text=step.text,
            line_number=step.line_number,
            scenario_id=TraceableId.from_bdd(feature_name, scenario=scenario_name),
        )


class ScenarioRequirement(Requirement):
    """Composite requirement grouping step requirements.

    A scenario requirement represents a complete test case with:
    - Step requirements for each Given/When/Then
    - Invariants that must hold throughout
    - End-state constraints that must hold at completion

    Maps to SysML v2:
        requirement <'bdd:...#Scenario:X'> scn_X : BDDScenarioRequirement {
            require step_Given_...;
            require step_When_...;
            require step_Then_...;
        }

    Attributes:
        name: Scenario name
        step_requirements: Ordered list of step requirements
        invariants: Constraints that must hold at all times
        end_state_constraints: Constraints for final state
    """

    name: str
    step_requirements: list[StepRequirement] = Field(default_factory=list)
    invariants: list[Constraint] = Field(default_factory=list)
    end_state_constraints: list[Constraint] = Field(default_factory=list)

    # Source information
    feature_name: str = ""

    @classmethod
    def from_scenario(
        cls,
        scenario: Scenario,
        feature_name: str,
    ) -> "ScenarioRequirement":
        """Create a ScenarioRequirement from an OSM Scenario."""
        step_reqs = [
            StepRequirement.from_step(step, feature_name, scenario.name)
            for step in scenario.steps
        ]

        return cls(
            id=scenario.id,
            name=scenario.name,
            doc=scenario.description,
            step_requirements=step_reqs,
            tags=scenario.tags,
            feature_name=feature_name,
        )

    @property
    def given_requirements(self) -> list[StepRequirement]:
        """Get Given step requirements (setup)."""
        return [
            r for r in self.step_requirements
            if r.step_type == StepType.GIVEN
        ]

    @property
    def when_requirements(self) -> list[StepRequirement]:
        """Get When step requirements (actions)."""
        return [
            r for r in self.step_requirements
            if r.step_type == StepType.WHEN
        ]

    @property
    def then_requirements(self) -> list[StepRequirement]:
        """Get Then step requirements (assertions)."""
        return [
            r for r in self.step_requirements
            if r.step_type == StepType.THEN
        ]

    def verify_setup(self, state: NiFiInstance) -> bool:
        """Verify all Given (setup) requirements."""
        return all(
            r.verify_assume(state) and r.verify_require(state)
            for r in self.given_requirements
        )

    def verify_end_state(self, state: NiFiInstance) -> bool:
        """Verify Then requirements and end-state constraints."""
        then_ok = all(
            r.verify_require(state)
            for r in self.then_requirements
        )
        end_ok = all(
            c.evaluate(state).satisfied
            for c in self.end_state_constraints
        )
        return then_ok and end_ok

    def verify_invariants(self, state: NiFiInstance) -> bool:
        """Verify invariant constraints hold."""
        return all(c.evaluate(state).satisfied for c in self.invariants)


class FeatureRequirement(Requirement):
    """Requirement grouping all scenarios in a feature.

    Maps to SysML v2:
        requirement <'bdd:features/X.feature'> feature_X {
            require scn_Scenario1;
            require scn_Scenario2;
        }

    Attributes:
        name: Feature name
        scenario_requirements: List of scenario requirements
        source_file: Original .feature file path
    """

    name: str
    scenario_requirements: list[ScenarioRequirement] = Field(default_factory=list)
    source_file: str = ""

    @classmethod
    def from_feature(cls, feature: Feature) -> "FeatureRequirement":
        """Create a FeatureRequirement from an OSM Feature."""
        scenario_reqs = [
            ScenarioRequirement.from_scenario(scenario, feature.name)
            for scenario in feature.all_scenarios()
        ]

        return cls(
            id=feature.id,
            name=feature.name,
            doc=feature.description,
            scenario_requirements=scenario_reqs,
            tags=feature.tags,
            source_file=feature.source_file,
        )

    def get_scenario(self, name: str) -> ScenarioRequirement | None:
        """Find scenario requirement by name."""
        for sr in self.scenario_requirements:
            if sr.name == name:
                return sr
        return None


def derive_requirements_from_scenario(
    scenario: Scenario,
    feature_name: str = "unknown",
) -> ScenarioRequirement:
    """Derive VM requirements from an OSM scenario.

    This is the key transformation from operational scenarios to
    verification requirements. Each step becomes a requirement with
    appropriate assume/require constraints based on step type.

    Args:
        scenario: The OSM scenario
        feature_name: Name of the containing feature

    Returns:
        ScenarioRequirement with derived step requirements
    """
    return ScenarioRequirement.from_scenario(scenario, feature_name)


__all__ = [
    "Requirement",
    "StepRequirement",
    "ScenarioRequirement",
    "FeatureRequirement",
    "derive_requirements_from_scenario",
]
