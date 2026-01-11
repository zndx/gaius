"""Health FSM - Finite State Machine for incident lifecycle.

This module provides Python-side utilities for working with the proto-defined
Health FSM enums. The proto enums in gaius_service.proto are the authoritative
source of truth for state definitions.

Fail Open Principle:
    - Unknown states are allowed through (don't filter to known values)
    - Terminal states (RESOLVED, MANUAL_REQUIRED) are the only filter criteria
    - When in doubt, surface the incident rather than hide it

OTel Integration:
    - State transitions emit spans with transition type and context
    - Failed transitions emit error events
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from gaius.engine.generated import (
    INCIDENT_STATUS_ACTIVE,
    INCIDENT_STATUS_HEALING,
    INCIDENT_STATUS_MANUAL_REQUIRED,
    INCIDENT_STATUS_RECOVERING,
    INCIDENT_STATUS_RESOLVED,
    INCIDENT_STATUS_UNSPECIFIED,
    INCIDENT_TRANSITION_ACTIVE_TO_HEALING,
    INCIDENT_TRANSITION_ACTIVE_TO_RECOVERING,
    INCIDENT_TRANSITION_HEALING_TO_MANUAL,
    INCIDENT_TRANSITION_HEALING_TO_RECOVERING,
    INCIDENT_TRANSITION_RECOVERING_TO_ACTIVE,
    INCIDENT_TRANSITION_RECOVERING_TO_RESOLVED,
    INCIDENT_TRANSITION_UNSPECIFIED,
    IncidentStatus,
    IncidentTransition,
)

if TYPE_CHECKING:
    from opentelemetry.trace import Span


# Terminal states - these are the only ones we filter OUT (Fail Open)
TERMINAL_STATES: frozenset[int] = frozenset({
    INCIDENT_STATUS_RESOLVED,
    INCIDENT_STATUS_MANUAL_REQUIRED,
})

# Valid state transitions (from -> to -> transition enum)
VALID_TRANSITIONS: dict[tuple[int, int], int] = {
    (INCIDENT_STATUS_ACTIVE, INCIDENT_STATUS_HEALING): INCIDENT_TRANSITION_ACTIVE_TO_HEALING,
    (INCIDENT_STATUS_ACTIVE, INCIDENT_STATUS_RECOVERING): INCIDENT_TRANSITION_ACTIVE_TO_RECOVERING,
    (INCIDENT_STATUS_HEALING, INCIDENT_STATUS_RECOVERING): INCIDENT_TRANSITION_HEALING_TO_RECOVERING,
    (INCIDENT_STATUS_HEALING, INCIDENT_STATUS_MANUAL_REQUIRED): INCIDENT_TRANSITION_HEALING_TO_MANUAL,
    (INCIDENT_STATUS_RECOVERING, INCIDENT_STATUS_RESOLVED): INCIDENT_TRANSITION_RECOVERING_TO_RESOLVED,
    (INCIDENT_STATUS_RECOVERING, INCIDENT_STATUS_ACTIVE): INCIDENT_TRANSITION_RECOVERING_TO_ACTIVE,
}

# String mappings for status (from proto enum names, lowercased)
STATUS_TO_PROTO: dict[str, int] = {
    "active": INCIDENT_STATUS_ACTIVE,
    "healing": INCIDENT_STATUS_HEALING,
    "recovering": INCIDENT_STATUS_RECOVERING,
    "resolved": INCIDENT_STATUS_RESOLVED,
    "manual_required": INCIDENT_STATUS_MANUAL_REQUIRED,
    "unspecified": INCIDENT_STATUS_UNSPECIFIED,
}

PROTO_TO_STATUS: dict[int, str] = {v: k for k, v in STATUS_TO_PROTO.items()}


@dataclass(frozen=True)
class TransitionResult:
    """Result of attempting a state transition."""

    valid: bool
    from_status: int
    to_status: int
    transition: int
    error: str | None = None

    @property
    def from_name(self) -> str:
        return PROTO_TO_STATUS.get(self.from_status, f"unknown({self.from_status})")

    @property
    def to_name(self) -> str:
        return PROTO_TO_STATUS.get(self.to_status, f"unknown({self.to_status})")


def is_terminal(status: int | str) -> bool:
    """Check if a status is terminal (should be filtered out).

    Fail Open: Only RESOLVED and MANUAL_REQUIRED are terminal.
    Any unknown status is NOT terminal (it surfaces for investigation).
    """
    if isinstance(status, str):
        status = STATUS_TO_PROTO.get(status.lower(), INCIDENT_STATUS_UNSPECIFIED)
    return status in TERMINAL_STATES


def is_active(status: int | str) -> bool:
    """Check if a status is active (should be shown in reports).

    Fail Open: Anything that's not terminal is active.
    This means unknown states are shown rather than hidden.
    """
    return not is_terminal(status)


def validate_transition(from_status: int | str, to_status: int | str) -> TransitionResult:
    """Validate a state transition and return the transition enum if valid.

    Args:
        from_status: Current status (proto enum or string name)
        to_status: Target status (proto enum or string name)

    Returns:
        TransitionResult with validity, transition enum, and error if invalid
    """
    # Normalize to proto enum values
    if isinstance(from_status, str):
        from_proto = STATUS_TO_PROTO.get(from_status.lower(), INCIDENT_STATUS_UNSPECIFIED)
    else:
        from_proto = from_status

    if isinstance(to_status, str):
        to_proto = STATUS_TO_PROTO.get(to_status.lower(), INCIDENT_STATUS_UNSPECIFIED)
    else:
        to_proto = to_status

    # Check if transition is valid
    transition = VALID_TRANSITIONS.get((from_proto, to_proto), INCIDENT_TRANSITION_UNSPECIFIED)

    if transition != INCIDENT_TRANSITION_UNSPECIFIED:
        return TransitionResult(
            valid=True,
            from_status=from_proto,
            to_status=to_proto,
            transition=transition,
        )

    # Invalid transition
    from_name = PROTO_TO_STATUS.get(from_proto, f"unknown({from_proto})")
    to_name = PROTO_TO_STATUS.get(to_proto, f"unknown({to_proto})")

    return TransitionResult(
        valid=False,
        from_status=from_proto,
        to_status=to_proto,
        transition=INCIDENT_TRANSITION_UNSPECIFIED,
        error=f"Invalid transition: {from_name} -> {to_name}",
    )


def get_valid_next_states(current_status: int | str) -> list[int]:
    """Get all valid next states from the current status.

    Args:
        current_status: Current status (proto enum or string name)

    Returns:
        List of valid next status proto enum values
    """
    if isinstance(current_status, str):
        current_proto = STATUS_TO_PROTO.get(current_status.lower(), INCIDENT_STATUS_UNSPECIFIED)
    else:
        current_proto = current_status

    return [to_status for (from_status, to_status) in VALID_TRANSITIONS if from_status == current_proto]


def transition_with_otel(
    from_status: int | str,
    to_status: int | str,
    span: "Span | None" = None,
    incident_fingerprint: str = "",
) -> TransitionResult:
    """Validate transition and emit OTel span events.

    Args:
        from_status: Current status
        to_status: Target status
        span: Optional OTel span to add events to
        incident_fingerprint: Incident identifier for context

    Returns:
        TransitionResult with validity and transition info
    """
    result = validate_transition(from_status, to_status)

    if span is not None:
        if result.valid:
            span.add_event(
                "health.incident.transition",
                attributes={
                    "incident.fingerprint": incident_fingerprint,
                    "transition.from": result.from_name,
                    "transition.to": result.to_name,
                    "transition.type": result.transition,
                },
            )
        else:
            span.add_event(
                "health.incident.invalid_transition",
                attributes={
                    "incident.fingerprint": incident_fingerprint,
                    "transition.from": result.from_name,
                    "transition.to": result.to_name,
                    "transition.error": result.error or "Unknown error",
                },
            )
            # Don't modify span status - Fail Open principle.
            # Invalid transitions are logged as events but don't mark the span as error.

    return result


def filter_active_incidents(incidents: list[dict]) -> list[dict]:
    """Filter incidents to only those that are active (Fail Open).

    This implements the Fail Open principle: we filter OUT known terminal
    states rather than filtering IN known active states. Any unknown state
    is included for investigation.

    Args:
        incidents: List of incident dicts with 'status' key

    Returns:
        List of incidents that are not in terminal states
    """
    return [inc for inc in incidents if is_active(inc.get("status", "unknown"))]
