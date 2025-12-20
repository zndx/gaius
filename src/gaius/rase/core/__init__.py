"""RASE Core - Domain-agnostic metamodel abstractions.

This module provides the abstract base types that all RASE domains
must implement. The core is completely domain-agnostic - it knows
nothing about NiFi, Metabase, TUI, or any specific system.

Key abstractions:
- SystemState: Protocol for domain-specific state snapshots
- Constraint[S]: Generic constraint parameterized by state type
- Oracle[S]: Generic verification oracle
- VerificationCase[S]: Generic verification case

Usage:
    from gaius.rase.core import SystemState, Constraint, Oracle

    class MyState(SystemState):
        ...

    class MyConstraint(Constraint[MyState]):
        def evaluate(self, state: MyState) -> ConstraintResult:
            ...
"""

from .state import SystemState, S
from .constraints import (
    Constraint,
    ConstraintResult,
    CompositeConstraint,
    AllOf,
    AnyOf,
    Not,
    TransitionConstraint,
)
from .vm import (
    Oracle,
    RewardStrategy,
    BinaryReward,
    GradedReward,
    VerdictKind,
    VerificationResult,
    VerificationCase,
    VerificationObjective,
)

__all__ = [
    # State
    "SystemState",
    "S",
    # Constraints
    "Constraint",
    "ConstraintResult",
    "CompositeConstraint",
    "AllOf",
    "AnyOf",
    "Not",
    "TransitionConstraint",
    # Verification
    "Oracle",
    "RewardStrategy",
    "BinaryReward",
    "GradedReward",
    "VerdictKind",
    "VerificationResult",
    "VerificationCase",
    "VerificationObjective",
]
