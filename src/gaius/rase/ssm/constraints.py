"""SSM Constraint definitions for RASE.

Constraints are declarative predicates over system state, used in VM
requirements to specify what conditions must hold.

Maps to SysML v2 constraint definitions:
    constraint def GroupExists {
        in nifi : NiFiInstance;
        in groupName : String;
    }

Design principles:
1. Declarative: Describe what to check, not how
2. Composable: Can combine with AllOf, AnyOf, Not
3. Debuggable: Rich failure messages for diagnosis
4. Serializable: Can persist constraint definitions

Constraints are used in two contexts:
- assume constraints: Preconditions that must hold before a step
- require constraints: Postconditions that must hold after a step
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Generic, TypeVar

from pydantic import BaseModel, Field

from .nifi import (
    NiFiInstance,
    ProcessorGroup,
    Processor,
    FlowConnection,
    ProcessorState,
    semantic_group_match,
)


class ConstraintResult(BaseModel):
    """Result of evaluating a constraint.

    Provides rich information for debugging verification failures.

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
        """Create a failure result."""
        return cls(
            satisfied=False,
            constraint_name=name,
            message=message,
            details=details or {},
        )


class Constraint(BaseModel, ABC):
    """Base class for SSM constraints.

    All constraints must implement evaluate() which takes system state
    and returns a ConstraintResult.

    Subclasses should be immutable (frozen=True) for safe use in
    verification case definitions.
    """

    model_config = {"frozen": True}

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable constraint name."""
        ...

    @abstractmethod
    def evaluate(self, state: NiFiInstance) -> ConstraintResult:
        """Evaluate constraint against system state.

        Args:
            state: Current system state snapshot

        Returns:
            ConstraintResult indicating satisfaction and any details
        """
        ...

    def __and__(self, other: "Constraint") -> "AllOf":
        """Combine with AND: self & other."""
        return AllOf(constraints=[self, other])

    def __or__(self, other: "Constraint") -> "AnyOf":
        """Combine with OR: self | other."""
        return AnyOf(constraints=[self, other])

    def __invert__(self) -> "Not":
        """Negate: ~self."""
        return Not(constraint=self)


# --- Structural Constraints ---


class GroupExists(Constraint):
    """Constraint: A process group with the given name exists.

    Maps to SysML v2:
        constraint def GroupExists {
            in nifi : NiFiInstance;
            in groupName : String;
        }
    """

    group_name: str
    parent_path: str = ""  # Path to parent group (empty = root)

    @property
    def name(self) -> str:
        if self.parent_path:
            return f"GroupExists({self.parent_path}/{self.group_name})"
        return f"GroupExists({self.group_name})"

    def evaluate(self, state: NiFiInstance) -> ConstraintResult:
        # Navigate to parent
        if self.parent_path:
            parent = state.get_group(self.parent_path)
            if parent is None:
                return ConstraintResult.failure(
                    self.name,
                    f"Parent path not found: {self.parent_path}",
                    {"parent_path": self.parent_path},
                )
        else:
            parent = state.root

        # Check for group
        group = parent.get_child_group(self.group_name)
        if group is not None:
            return ConstraintResult.success(
                self.name,
                f"Group '{self.group_name}' exists with {len(group.processors)} processors",
            )
        else:
            available = [g.name for g in parent.child_groups]
            return ConstraintResult.failure(
                self.name,
                f"Group '{self.group_name}' not found",
                {"available_groups": available},
            )


class ProcessorExists(Constraint):
    """Constraint: A processor with the given name exists in the group."""

    processor_name: str
    group_path: str = ""  # Path to containing group

    @property
    def name(self) -> str:
        if self.group_path:
            return f"ProcessorExists({self.group_path}/{self.processor_name})"
        return f"ProcessorExists({self.processor_name})"

    def evaluate(self, state: NiFiInstance) -> ConstraintResult:
        group = state.get_group(self.group_path) if self.group_path else state.root
        if group is None:
            return ConstraintResult.failure(
                self.name,
                f"Group path not found: {self.group_path}",
            )

        proc = group.get_processor(self.processor_name)
        if proc is not None:
            return ConstraintResult.success(
                self.name,
                f"Processor '{self.processor_name}' exists (type: {proc.type_short_name})",
            )
        else:
            available = [p.name for p in group.processors]
            return ConstraintResult.failure(
                self.name,
                f"Processor '{self.processor_name}' not found",
                {"available_processors": available},
            )


class ConnectionExists(Constraint):
    """Constraint: A connection exists between source and destination."""

    source_name: str
    destination_name: str
    group_path: str = ""
    relationships: list[str] | None = None  # Optional: specific relationships

    @property
    def name(self) -> str:
        conn_desc = f"{self.source_name}->{self.destination_name}"
        if self.group_path:
            return f"ConnectionExists({self.group_path}/{conn_desc})"
        return f"ConnectionExists({conn_desc})"

    def evaluate(self, state: NiFiInstance) -> ConstraintResult:
        group = state.get_group(self.group_path) if self.group_path else state.root
        if group is None:
            return ConstraintResult.failure(
                self.name,
                f"Group path not found: {self.group_path}",
            )

        conn = group.get_connection(self.source_name, self.destination_name)
        if conn is None:
            return ConstraintResult.failure(
                self.name,
                f"Connection {self.source_name}->{self.destination_name} not found",
                {"available_connections": [c.semantic_key for c in group.connections]},
            )

        # Check relationships if specified
        if self.relationships:
            missing = set(self.relationships) - set(conn.selected_relationships)
            if missing:
                return ConstraintResult.failure(
                    self.name,
                    f"Connection missing relationships: {missing}",
                    {
                        "expected": self.relationships,
                        "actual": conn.selected_relationships,
                    },
                )

        return ConstraintResult.success(
            self.name,
            f"Connection exists with relationships: {conn.selected_relationships}",
        )


# --- Type and Configuration Constraints ---


class ProcessorHasType(Constraint):
    """Constraint: A processor has the expected NiFi type."""

    processor_name: str
    expected_type: str  # Full or short type name
    group_path: str = ""

    @property
    def name(self) -> str:
        return f"ProcessorHasType({self.processor_name}, {self.expected_type})"

    def evaluate(self, state: NiFiInstance) -> ConstraintResult:
        group = state.get_group(self.group_path) if self.group_path else state.root
        if group is None:
            return ConstraintResult.failure(self.name, "Group not found")

        proc = group.get_processor(self.processor_name)
        if proc is None:
            return ConstraintResult.failure(
                self.name,
                f"Processor '{self.processor_name}' not found",
            )

        # Match full type or short name
        if (
            proc.nifi_type == self.expected_type or
            proc.type_short_name == self.expected_type
        ):
            return ConstraintResult.success(self.name)
        else:
            return ConstraintResult.failure(
                self.name,
                f"Type mismatch: expected {self.expected_type}, got {proc.nifi_type}",
                {"expected": self.expected_type, "actual": proc.nifi_type},
            )


class ProcessorHasProperty(Constraint):
    """Constraint: A processor has a property with expected value."""

    processor_name: str
    property_name: str
    expected_value: Any
    group_path: str = ""

    @property
    def name(self) -> str:
        return f"ProcessorHasProperty({self.processor_name}.{self.property_name})"

    def evaluate(self, state: NiFiInstance) -> ConstraintResult:
        group = state.get_group(self.group_path) if self.group_path else state.root
        if group is None:
            return ConstraintResult.failure(self.name, "Group not found")

        proc = group.get_processor(self.processor_name)
        if proc is None:
            return ConstraintResult.failure(
                self.name,
                f"Processor '{self.processor_name}' not found",
            )

        actual = proc.properties.get(self.property_name)
        if actual == self.expected_value:
            return ConstraintResult.success(self.name)
        elif actual is None:
            return ConstraintResult.failure(
                self.name,
                f"Property '{self.property_name}' not set",
                {"available_properties": list(proc.properties.keys())},
            )
        else:
            return ConstraintResult.failure(
                self.name,
                f"Property value mismatch",
                {"expected": self.expected_value, "actual": actual},
            )


# --- Semantic Equivalence Constraints ---


class FlowIsEquivalent(Constraint):
    """Constraint: Actual flow matches expected flow semantically.

    This is the core verification constraint for BDD scenarios:
    it checks that the flow created by the agent matches the
    expected specification.

    Maps to SysML v2:
        constraint def FlowIsEquivalent {
            in expected : ProcessorGroup;
            in actual : ProcessorGroup;
        }
    """

    expected: ProcessorGroup
    group_path: str = ""  # Path to actual group in state
    recursive: bool = True

    @property
    def name(self) -> str:
        return f"FlowIsEquivalent({self.expected.name})"

    def evaluate(self, state: NiFiInstance) -> ConstraintResult:
        actual = state.get_group(self.group_path) if self.group_path else state.root
        if actual is None:
            return ConstraintResult.failure(
                self.name,
                f"Actual group not found at path: {self.group_path}",
            )

        is_match, differences = semantic_group_match(
            self.expected,
            actual,
            recursive=self.recursive,
        )

        if is_match:
            return ConstraintResult.success(
                self.name,
                f"Flow matches with {len(actual.processors)} processors, "
                f"{len(actual.connections)} connections",
            )
        else:
            return ConstraintResult.failure(
                self.name,
                f"Flow mismatch: {len(differences)} differences",
                {"differences": differences},
            )


# --- Operational Constraints ---


class AllProcessorsRunning(Constraint):
    """Constraint: All processors in a group are in RUNNING state."""

    group_path: str = ""
    recursive: bool = True

    @property
    def name(self) -> str:
        return f"AllProcessorsRunning({self.group_path or 'root'})"

    def evaluate(self, state: NiFiInstance) -> ConstraintResult:
        group = state.get_group(self.group_path) if self.group_path else state.root
        if group is None:
            return ConstraintResult.failure(self.name, "Group not found")

        all_procs = group.all_processors(recursive=self.recursive)
        not_running = [
            p.name for p in all_procs
            if p.run_state != ProcessorState.RUNNING
        ]

        if not not_running:
            return ConstraintResult.success(
                self.name,
                f"All {len(all_procs)} processors running",
            )
        else:
            return ConstraintResult.failure(
                self.name,
                f"{len(not_running)} processors not running",
                {"not_running": not_running},
            )


class NoBackpressure(Constraint):
    """Constraint: No connections have backpressure."""

    group_path: str = ""
    recursive: bool = True

    @property
    def name(self) -> str:
        return f"NoBackpressure({self.group_path or 'root'})"

    def evaluate(self, state: NiFiInstance) -> ConstraintResult:
        group = state.get_group(self.group_path) if self.group_path else state.root
        if group is None:
            return ConstraintResult.failure(self.name, "Group not found")

        all_conns = group.all_connections(recursive=self.recursive)
        backpressured = [c.semantic_key for c in all_conns if c.is_backpressured]

        if not backpressured:
            return ConstraintResult.success(self.name)
        else:
            return ConstraintResult.failure(
                self.name,
                f"{len(backpressured)} connections have backpressure",
                {"backpressured": backpressured},
            )


# --- Composite Constraints ---


class CompositeConstraint(Constraint, ABC):
    """Base class for constraints that combine other constraints."""

    constraints: list[Constraint]


class AllOf(CompositeConstraint):
    """All constraints must be satisfied (AND)."""

    @property
    def name(self) -> str:
        names = [c.name for c in self.constraints]
        return f"AllOf({', '.join(names)})"

    def evaluate(self, state: NiFiInstance) -> ConstraintResult:
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


class AnyOf(CompositeConstraint):
    """At least one constraint must be satisfied (OR)."""

    @property
    def name(self) -> str:
        names = [c.name for c in self.constraints]
        return f"AnyOf({', '.join(names)})"

    def evaluate(self, state: NiFiInstance) -> ConstraintResult:
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


class Not(Constraint):
    """Negation of a constraint."""

    constraint: Constraint

    @property
    def name(self) -> str:
        return f"Not({self.constraint.name})"

    def evaluate(self, state: NiFiInstance) -> ConstraintResult:
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
                message=f"Constraint correctly not satisfied",
                sub_results=[inner],
            )


# --- Transition Constraints (for step verification) ---


class TransitionConstraint(BaseModel, ABC):
    """Constraint over state transitions (before → after).

    Used for verifying that a step produced the expected change.
    """

    model_config = {"frozen": True}

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def evaluate(
        self,
        before: NiFiInstance,
        after: NiFiInstance,
    ) -> ConstraintResult:
        """Evaluate constraint against state transition."""
        ...


class ProcessorCreated(TransitionConstraint):
    """Transition constraint: A processor was created by this step."""

    processor_name: str
    group_path: str = ""

    @property
    def name(self) -> str:
        return f"ProcessorCreated({self.processor_name})"

    def evaluate(
        self,
        before: NiFiInstance,
        after: NiFiInstance,
    ) -> ConstraintResult:
        group_before = (
            before.get_group(self.group_path) if self.group_path else before.root
        )
        group_after = (
            after.get_group(self.group_path) if self.group_path else after.root
        )

        if group_after is None:
            return ConstraintResult.failure(self.name, "Group not found after")

        # Check it didn't exist before
        existed_before = (
            group_before is not None and
            group_before.get_processor(self.processor_name) is not None
        )

        # Check it exists after
        exists_after = group_after.get_processor(self.processor_name) is not None

        if existed_before:
            return ConstraintResult.failure(
                self.name,
                f"Processor '{self.processor_name}' already existed",
            )
        elif exists_after:
            return ConstraintResult.success(
                self.name,
                f"Processor '{self.processor_name}' created",
            )
        else:
            return ConstraintResult.failure(
                self.name,
                f"Processor '{self.processor_name}' was not created",
            )


class ConnectionCreated(TransitionConstraint):
    """Transition constraint: A connection was created by this step."""

    source_name: str
    destination_name: str
    group_path: str = ""

    @property
    def name(self) -> str:
        return f"ConnectionCreated({self.source_name}->{self.destination_name})"

    def evaluate(
        self,
        before: NiFiInstance,
        after: NiFiInstance,
    ) -> ConstraintResult:
        group_before = (
            before.get_group(self.group_path) if self.group_path else before.root
        )
        group_after = (
            after.get_group(self.group_path) if self.group_path else after.root
        )

        if group_after is None:
            return ConstraintResult.failure(self.name, "Group not found after")

        # Check it didn't exist before
        existed_before = (
            group_before is not None and
            group_before.get_connection(self.source_name, self.destination_name)
            is not None
        )

        # Check it exists after
        exists_after = (
            group_after.get_connection(self.source_name, self.destination_name)
            is not None
        )

        if existed_before:
            return ConstraintResult.failure(
                self.name,
                "Connection already existed",
            )
        elif exists_after:
            return ConstraintResult.success(self.name, "Connection created")
        else:
            return ConstraintResult.failure(
                self.name,
                "Connection was not created",
            )


__all__ = [
    "ConstraintResult",
    "Constraint",
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
    "TransitionConstraint",
    "ProcessorCreated",
    "ConnectionCreated",
]
