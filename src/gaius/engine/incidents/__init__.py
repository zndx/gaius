"""Agenda-centric incident tracking for Gaius HealthObserver.

This module implements the Agenda-Centric Incident Model where:
- Agenda (scheduled capability phases) is the unit of health
- Makespan fulfillment is the success metric
- Positive control is required for resolution
- Endpoints are diagnostic detail, not goals

Usage:
    from gaius.engine.incidents import (
        AgendaIncident, AgendaStatus, ControlMode, AgendaType,
        AgendaPhase, AgendaPhaseEvent,
    )

    incident = AgendaIncident(
        agenda_id="evolution-2025-01-02-001",
        agenda_type=AgendaType.EVOLUTION,
        phases=[
            AgendaPhase(name="BASELINE_EVICTION", required_capabilities=["cap_reasoning"]),
            AgendaPhase(name="REASONING_WORKLOAD", required_capabilities=["cap_reasoning"]),
            AgendaPhase(name="BASELINE_RESTORATION", required_capabilities=[]),
        ],
    )
"""

from .agenda_incident import (
    AgendaIncident,
    AgendaPhase,
    AgendaPhaseEvent,
    AgendaStatus,
    AgendaType,
    ControlMode,
    EndpointTransition,
    PhaseEventType,
    calculate_agenda_severity,
    detect_control_mode,
)

__all__ = [
    "AgendaIncident",
    "AgendaPhase",
    "AgendaPhaseEvent",
    "AgendaStatus",
    "AgendaType",
    "ControlMode",
    "EndpointTransition",
    "PhaseEventType",
    "calculate_agenda_severity",
    "detect_control_mode",
]
