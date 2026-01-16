"""Generic constraint framework for RASE.

Provides domain-agnostic constraint base classes that can be
parameterized by any SystemState type. Each domain (NiFi, Metabase, etc.)
creates concrete constraints by specifying their state type.

Example:
    # Domain-agnostic base
    class Constraint(Generic[S]):
        def evaluate(self, state: S) -> ConstraintResult: ...

    # NiFi-specific constraint
    class ProcessorExists(Constraint[NiFiInstance]):
        def evaluate(self, state: NiFiInstance) -> ConstraintResult: ...

Design principles:
1. Declarative: Describe what to check, not how
2. Composable: AllOf, AnyOf, Not for complex specifications
3. Debuggable: Rich ConstraintResult with failure details
4. Immutable: frozen=True for safe concurrent use
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from .state import S


class ConstraintResult(BaseModel):
    """Result of evaluating a constraint.

    Provides rich information for debugging verification failures
    and for computing partial credit in graded rewards.

    Attributes:
        satisfied: Whether the constraint was satisfied
        constraint_name: Name of the constraint that was evaluated
        message: Human-readable explanation
        details: Structured data for programmatic analysis
        sub_results: Results from nested constraints (for composites)
    """

    satisfied: bool
    constraint_name: str
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    sub_results: list["ConstraintResult"] = Field(default_factory=list)

    def __bool__(self) -> bool:
        """Allow using ConstraintResult in boolean context."""
        return self.satisfied

    @classmethod
    def success(cls, name: str, message: str = "") -> "ConstraintResult":
        """Create a successful result."""
        return cls(satisfied=True, constraint_name=name, message=message)

    @classmethod
    def failure(
        cls,
        name: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> "ConstraintResult":
        """Create a failure result with details."""
        return cls(
            satisfied=False,
            constraint_name=name,
            message=message,
            details=details or {},
        )

    def count_satisfied(self) -> int:
        """Count satisfied constraints (including sub-results)."""
        count = 1 if self.satisfied else 0
        for sub in self.sub_results:
            count += sub.count_satisfied()
        return count

    def count_total(self) -> int:
        """Count total constraints (including sub-results)."""
        count = 1
        for sub in self.sub_results:
            count += sub.count_total()
        return count

    def accuracy(self) -> float:
        """Compute accuracy as ratio of satisfied to total."""
        total = self.count_total()
        if total == 0:
            return 1.0
        return self.count_satisfied() / total


class Constraint(BaseModel, ABC, Generic[S]):
    """Base class for generic constraints.

    Type parameter S specifies what state type this constraint
    evaluates against. Domain-specific constraints specify their
    concrete state type when inheriting.

    Example:
        class ProcessorExists(Constraint[NiFiInstance]):
            processor_name: str

            def evaluate(self, state: NiFiInstance) -> ConstraintResult:
                ...
    """

    model_config = {"frozen": True}

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable constraint name for debugging."""
        ...

    @abstractmethod
    def evaluate(self, state: S) -> ConstraintResult:
        """Evaluate constraint against system state.

        Args:
            state: Current system state snapshot

        Returns:
            ConstraintResult indicating satisfaction and details
        """
        ...

    def __and__(self, other: "Constraint[S]") -> "AllOf[S]":
        """Combine with AND: self & other."""
        return AllOf(constraints=[self, other])

    def __or__(self, other: "Constraint[S]") -> "AnyOf[S]":
        """Combine with OR: self | other."""
        return AnyOf(constraints=[self, other])

    def __invert__(self) -> "Not[S]":
        """Negate: ~self."""
        return Not(constraint=self)


class CompositeConstraint(Constraint[S], ABC, Generic[S]):
    """Base class for constraints that combine other constraints."""

    constraints: list[Constraint[S]]


class AllOf(CompositeConstraint[S], Generic[S]):
    """All constraints must be satisfied (AND).

    Short-circuits on first failure for efficiency when evaluating
    expensive constraints.
    """

    @property
    def name(self) -> str:
        if len(self.constraints) <= 3:
            names = [c.name for c in self.constraints]
            return f"AllOf({', '.join(names)})"
        return f"AllOf({len(self.constraints)} constraints)"

    def evaluate(self, state: S) -> ConstraintResult:
        sub_results = [c.evaluate(state) for c in self.constraints]
        all_satisfied = all(r.satisfied for r in sub_results)

        if all_satisfied:
            return ConstraintResult(
                satisfied=True,
                constraint_name=self.name,
                message=f"All {len(self.constraints)} constraints satisfied",
                sub_results=sub_results,
            )
        else:
            failed = [r for r in sub_results if not r.satisfied]
            return ConstraintResult(
                satisfied=False,
                constraint_name=self.name,
                message=f"{len(failed)}/{len(self.constraints)} constraints failed",
                sub_results=sub_results,
            )


class AnyOf(CompositeConstraint[S], Generic[S]):
    """At least one constraint must be satisfied (OR).

    Short-circuits on first success for efficiency.
    """

    @property
    def name(self) -> str:
        if len(self.constraints) <= 3:
            names = [c.name for c in self.constraints]
            return f"AnyOf({', '.join(names)})"
        return f"AnyOf({len(self.constraints)} constraints)"

    def evaluate(self, state: S) -> ConstraintResult:
        sub_results = [c.evaluate(state) for c in self.constraints]
        any_satisfied = any(r.satisfied for r in sub_results)

        if any_satisfied:
            return ConstraintResult(
                satisfied=True,
                constraint_name=self.name,
                message="At least one constraint satisfied",
                sub_results=sub_results,
            )
        else:
            return ConstraintResult(
                satisfied=False,
                constraint_name=self.name,
                message="No constraints satisfied",
                sub_results=sub_results,
            )


class Not(Constraint[S], Generic[S]):
    """Negation of a constraint."""

    constraint: Constraint[S]

    @property
    def name(self) -> str:
        return f"Not({self.constraint.name})"

    def evaluate(self, state: S) -> ConstraintResult:
        inner = self.constraint.evaluate(state)

        if inner.satisfied:
            return ConstraintResult(
                satisfied=False,
                constraint_name=self.name,
                message=f"Constraint unexpectedly satisfied: {inner.message}",
                sub_results=[inner],
            )
        else:
            return ConstraintResult(
                satisfied=True,
                constraint_name=self.name,
                message="Constraint correctly not satisfied",
                sub_results=[inner],
            )


class TransitionConstraint(BaseModel, ABC, Generic[S]):
    """Constraint over state transitions (before -> after).

    Used for verifying that a step produced the expected change.
    Transition constraints compare two state snapshots.
    """

    model_config = {"frozen": True}

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable constraint name."""
        ...

    @abstractmethod
    def evaluate(self, before: S, after: S) -> ConstraintResult:
        """Evaluate constraint against state transition.

        Args:
            before: State before the action
            after: State after the action

        Returns:
            ConstraintResult indicating whether transition was valid
        """
        ...
