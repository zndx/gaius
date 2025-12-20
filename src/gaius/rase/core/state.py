"""SystemState protocol for RASE domains.

Defines the interface that all domain-specific state models must
implement to be usable with the generic RASE infrastructure.

This is a structural protocol (duck typing) - any class that has
these methods/properties is considered a valid SystemState without
needing to explicitly inherit.

Example:
    @runtime_checkable allows isinstance checks:

    if isinstance(my_state, SystemState):
        tid = my_state.to_traceable_id()
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, TypeVar, runtime_checkable

# Forward reference for TraceableId to avoid circular imports
TYPE_CHECKING = False
if TYPE_CHECKING:
    from gaius.rase.traceability import TraceableId


@runtime_checkable
class SystemState(Protocol):
    """Protocol for domain-specific system state.

    All domain state models (NiFiInstance, MetabaseInstance, TUIState, etc.)
    must implement this protocol to be usable with the generic RASE
    constraint and verification infrastructure.

    The protocol uses structural subtyping - any class with these methods
    is automatically considered a SystemState without explicit inheritance.

    Attributes:
        captured_at: When this state snapshot was captured

    Methods:
        to_traceable_id: Generate a TraceableId for this state snapshot
        get_component: Navigate to a component by path (optional)
    """

    @property
    def captured_at(self) -> datetime:
        """When this state snapshot was captured.

        Used for temporal tracking in DigitalThread and for
        detecting stale state in verification.
        """
        ...

    def to_traceable_id(self) -> "TraceableId":
        """Generate a TraceableId for this state snapshot.

        The ID should uniquely identify this snapshot and be
        suitable for inclusion in DigitalThread provenance chains.

        Returns:
            TraceableId with appropriate scheme for the domain
        """
        ...

    def get_component(self, path: str) -> Any | None:
        """Navigate to a component by path.

        This method enables generic constraint evaluation by
        allowing path-based access to nested components.

        Args:
            path: Dot-separated path to component (e.g., "root.processors.GetFile")

        Returns:
            The component at the path, or None if not found
        """
        ...


# Type variable bound to SystemState for generic constraints/oracles
S = TypeVar("S", bound=SystemState)


class StateSnapshot:
    """Mixin providing common snapshot functionality.

    Domain state classes can inherit from this to get standard
    implementations of snapshot-related functionality.

    This is optional - domains can implement SystemState directly
    without using this mixin.
    """

    _captured_at: datetime

    @property
    def captured_at(self) -> datetime:
        """When this state was captured."""
        return self._captured_at

    def age_seconds(self) -> float:
        """How old this snapshot is in seconds."""
        return (datetime.now() - self._captured_at).total_seconds()

    def is_stale(self, max_age_seconds: float = 60.0) -> bool:
        """Check if this snapshot is older than max_age_seconds."""
        return self.age_seconds() > max_age_seconds
