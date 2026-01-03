"""Agenda-centric incident model for tracking workload health.

This module defines the core data structures for tracking Agenda incidents,
where an Agenda is a scheduled sequence of capability phases with makespan
projections from OR-Tools.

Key concepts:
- Agenda: Unit of health tracking (not individual endpoints)
- Makespan: OR-Tools projected timeline for capability transitions
- Positive Control: Intentional orchestrated transitions (not failures/restarts)
- Resolution: Return to baseline under positive control only
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class AgendaType(Enum):
    """Types of agendas that drive endpoint configuration.

    Maps to WorkloadType but focused on scheduling/makespan semantics.
    """

    AMBIENT_CYCLE = "ambient_cycle"  # Ambient workload service maintenance
    SWARM = "swarm"  # Multi-agent swarm analysis
    EVOLUTION = "evolution"  # Agent evolution/optimization
    INFERENCE = "inference"  # Direct inference request
    FLOW = "flow"  # Metaflow pipeline execution


class AgendaStatus(Enum):
    """Lifecycle status of an agenda incident.

    Progression: SCHEDULING -> ON_TRACK -> (DELAYED|BLOCKED) -> (FULFILLED|FAILED|DEGRADED)
    """

    SCHEDULING = "scheduling"  # Waiting for OR-Tools plan
    ON_TRACK = "on_track"  # Within makespan tolerance
    DELAYED = "delayed"  # Behind makespan, still recoverable
    BLOCKED = "blocked"  # Cannot proceed without intervention
    FULFILLED = "fulfilled"  # Completed under positive control
    FAILED = "failed"  # Could not fulfill, gave up
    DEGRADED = "degraded"  # Completed but via failure/restart path


class ControlMode(Enum):
    """How state transitions occurred.

    Only POSITIVE control is acceptable for agenda fulfillment.
    FAILURE_RECOVERY and RESTART_RECOVERY degrade the agenda.
    """

    POSITIVE = "positive"  # Intentional orchestrated transition
    FAILURE_RECOVERY = "failure_recovery"  # Endpoint failed, recovered automatically
    RESTART_RECOVERY = "restart_recovery"  # Engine restart caused transition


class PhaseEventType(Enum):
    """Types of phase events in the agenda lifecycle."""

    AGENDA_STARTED = "agenda_started"
    SCHEDULING_COMPLETE = "scheduling_complete"
    BASELINE_DEPARTED = "baseline_departed"
    PHASE_STARTED = "phase_started"
    PHASE_COMPLETED = "phase_completed"
    TRANSITION_STARTED = "transition_started"
    TRANSITION_COMPLETED = "transition_completed"
    BASELINE_RESTORED = "baseline_restored"
    AGENDA_FULFILLED = "agenda_fulfilled"
    AGENDA_FAILED = "agenda_failed"
    AGENDA_DEGRADED = "agenda_degraded"
    CONTROL_DEGRADED = "control_degraded"


@dataclass
class AgendaPhase:
    """A capability phase within an agenda.

    Each phase specifies what capabilities are needed and optionally
    which endpoints should provide them.

    Attributes:
        name: Phase name (e.g., "REASONING_WORKLOAD", "BASELINE_RESTORATION")
        required_capabilities: List of capability names needed
        target_endpoints: Optional specific endpoints (empty = any healthy)
        projected_duration_ms: OR-Tools projected duration for this phase
        actual_duration_ms: Actual duration once completed
    """

    name: str
    required_capabilities: list[str] = field(default_factory=list)
    target_endpoints: list[str] = field(default_factory=list)
    projected_duration_ms: int = 0
    actual_duration_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "required_capabilities": self.required_capabilities,
            "target_endpoints": self.target_endpoints,
            "projected_duration_ms": self.projected_duration_ms,
            "actual_duration_ms": self.actual_duration_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgendaPhase":
        """Create from dictionary."""
        return cls(
            name=data["name"],
            required_capabilities=data.get("required_capabilities", []),
            target_endpoints=data.get("target_endpoints", []),
            projected_duration_ms=data.get("projected_duration_ms", 0),
            actual_duration_ms=data.get("actual_duration_ms"),
        )


@dataclass
class EndpointTransition:
    """Record of an endpoint state transition during an agenda.

    Used for diagnostic drill-down to understand what happened
    at the endpoint level.

    Attributes:
        endpoint: Endpoint name (e.g., "reasoning", "coding")
        from_state: Previous state
        to_state: New state
        timestamp: When transition occurred
        control_mode: How transition occurred
        phase_index: Which phase this occurred in
    """

    endpoint: str
    from_state: str
    to_state: str
    timestamp: datetime = field(default_factory=datetime.now)
    control_mode: ControlMode = ControlMode.POSITIVE
    phase_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "endpoint": self.endpoint,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "timestamp": self.timestamp.isoformat(),
            "control_mode": self.control_mode.value,
            "phase_index": self.phase_index,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EndpointTransition":
        """Create from dictionary."""
        return cls(
            endpoint=data["endpoint"],
            from_state=data["from_state"],
            to_state=data["to_state"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            control_mode=ControlMode(data["control_mode"]),
            phase_index=data.get("phase_index", 0),
        )


@dataclass
class AgendaPhaseEvent:
    """An event in the agenda phase lifecycle.

    Used for event-sourced tracking of what happened during
    each phase of the agenda.

    Attributes:
        event_id: Unique event identifier
        phase_index: Which phase this event belongs to
        phase_name: Name of the phase
        event_type: Type of event
        control_mode: Control mode at time of event
        endpoint: Optional endpoint involved
        endpoint_from_state: Optional previous endpoint state
        endpoint_to_state: Optional new endpoint state
        projected_duration_ms: Expected duration (for timing events)
        actual_duration_ms: Actual duration (for completed events)
        payload: Additional event-specific data
        created_at: When event occurred
    """

    event_id: UUID = field(default_factory=uuid4)
    phase_index: int = 0
    phase_name: str = ""
    event_type: PhaseEventType = PhaseEventType.PHASE_STARTED
    control_mode: ControlMode = ControlMode.POSITIVE
    endpoint: str | None = None
    endpoint_from_state: str | None = None
    endpoint_to_state: str | None = None
    projected_duration_ms: int | None = None
    actual_duration_ms: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "event_id": str(self.event_id),
            "phase_index": self.phase_index,
            "phase_name": self.phase_name,
            "event_type": self.event_type.value,
            "control_mode": self.control_mode.value,
            "endpoint": self.endpoint,
            "endpoint_from_state": self.endpoint_from_state,
            "endpoint_to_state": self.endpoint_to_state,
            "projected_duration_ms": self.projected_duration_ms,
            "actual_duration_ms": self.actual_duration_ms,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class AgendaIncident:
    """Tracks whether an Agenda is proceeding according to makespan projections.

    The Agenda is the unit of health tracking. An incident is created when
    a workload begins and tracks:
    - Progress through capability phases
    - Makespan variance (actual vs projected)
    - Control mode (positive vs failure/restart recovery)

    Resolution requires ALL of:
    1. All phases completed successfully
    2. Return to baseline configuration
    3. Return under positive control (not via failure/restart)

    Attributes:
        incident_id: Unique identifier
        agenda_id: WorkloadRequest.workload_id
        agenda_type: Type of agenda
        phases: Ordered list of capability phases
        current_phase_index: Current phase (0-indexed)
        scheduler_plan_id: OR-Tools plan ID
        makespan_projection_ms: What OR-Tools projected
        actual_duration_ms: What actually happened
        status: Current lifecycle status
        control_mode: Overall control mode (degrades on any non-positive transition)
        severity_score: Computed severity for RPN
        endpoint_transitions: Diagnostic endpoint transition log
        healing_event_ids: Links to healing_events for drill-down
    """

    incident_id: UUID = field(default_factory=uuid4)
    agenda_id: str = ""
    agenda_type: AgendaType = AgendaType.INFERENCE
    phases: list[AgendaPhase] = field(default_factory=list)
    current_phase_index: int = 0
    scheduler_plan_id: str | None = None
    makespan_projection_ms: int | None = None
    actual_duration_ms: int = 0
    status: AgendaStatus = AgendaStatus.SCHEDULING
    control_mode: ControlMode = ControlMode.POSITIVE
    severity_score: int = 0
    endpoint_transitions: list[EndpointTransition] = field(default_factory=list)
    healing_event_ids: list[UUID] = field(default_factory=list)
    events: list[AgendaPhaseEvent] = field(default_factory=list)

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    baseline_departed_at: datetime | None = None
    baseline_restored_at: datetime | None = None
    resolved_at: datetime | None = None

    # Database ID (set after persistence)
    db_id: int | None = None

    @property
    def makespan_variance_pct(self) -> float:
        """Calculate variance from projected makespan.

        Returns:
            Percentage variance: (actual - projected) / projected
            Returns 0.0 if no projection available
        """
        if not self.makespan_projection_ms or self.makespan_projection_ms == 0:
            return 0.0
        return (self.actual_duration_ms - self.makespan_projection_ms) / self.makespan_projection_ms

    @property
    def current_phase(self) -> AgendaPhase | None:
        """Get the current phase."""
        if 0 <= self.current_phase_index < len(self.phases):
            return self.phases[self.current_phase_index]
        return None

    @property
    def is_active(self) -> bool:
        """Check if this incident is still active (not resolved)."""
        return self.status not in (
            AgendaStatus.FULFILLED,
            AgendaStatus.FAILED,
            AgendaStatus.DEGRADED,
        )

    @property
    def is_resolved(self) -> bool:
        """Check if this incident is resolved."""
        return not self.is_active

    @property
    def elapsed_ms(self) -> int:
        """Elapsed time since incident started in milliseconds."""
        if self.resolved_at:
            delta = self.resolved_at - self.created_at
        else:
            delta = datetime.now() - self.created_at
        return int(delta.total_seconds() * 1000)

    def advance_phase(self) -> bool:
        """Advance to the next phase.

        Returns:
            True if advanced, False if already at last phase
        """
        if self.current_phase_index < len(self.phases) - 1:
            # Record duration on current phase
            if self.current_phase:
                self.current_phase.actual_duration_ms = self.elapsed_ms
            self.current_phase_index += 1
            return True
        return False

    def record_transition(
        self,
        endpoint: str,
        from_state: str,
        to_state: str,
        control: ControlMode,
    ) -> None:
        """Record an endpoint transition.

        Automatically degrades control_mode if transition is non-positive.

        Args:
            endpoint: Endpoint name
            from_state: Previous state
            to_state: New state
            control: How transition occurred
        """
        transition = EndpointTransition(
            endpoint=endpoint,
            from_state=from_state,
            to_state=to_state,
            control_mode=control,
            phase_index=self.current_phase_index,
        )
        self.endpoint_transitions.append(transition)

        # Degrade overall control mode if any transition is non-positive
        if control != ControlMode.POSITIVE:
            self._degrade_control_mode(control)

    def _degrade_control_mode(self, new_mode: ControlMode) -> None:
        """Degrade control mode to the worse of current and new.

        Control mode degradation order: POSITIVE < FAILURE_RECOVERY < RESTART_RECOVERY
        """
        mode_severity = {
            ControlMode.POSITIVE: 0,
            ControlMode.FAILURE_RECOVERY: 1,
            ControlMode.RESTART_RECOVERY: 2,
        }
        if mode_severity[new_mode] > mode_severity[self.control_mode]:
            old_mode = self.control_mode
            self.control_mode = new_mode
            # Record control degradation event
            self.events.append(
                AgendaPhaseEvent(
                    phase_index=self.current_phase_index,
                    phase_name=self.current_phase.name if self.current_phase else "",
                    event_type=PhaseEventType.CONTROL_DEGRADED,
                    control_mode=new_mode,
                    payload={"from_mode": old_mode.value, "to_mode": new_mode.value},
                )
            )

    def mark_scheduling_complete(
        self,
        scheduler_plan_id: str,
        makespan_projection_ms: int,
    ) -> None:
        """Mark scheduling as complete with OR-Tools plan.

        Args:
            scheduler_plan_id: ID from OR-Tools scheduler
            makespan_projection_ms: Projected total duration
        """
        self.scheduler_plan_id = scheduler_plan_id
        self.makespan_projection_ms = makespan_projection_ms
        self.status = AgendaStatus.ON_TRACK
        self.events.append(
            AgendaPhaseEvent(
                phase_index=0,
                phase_name=self.phases[0].name if self.phases else "",
                event_type=PhaseEventType.SCHEDULING_COMPLETE,
                payload={
                    "scheduler_plan_id": scheduler_plan_id,
                    "makespan_projection_ms": makespan_projection_ms,
                },
            )
        )

    def mark_baseline_departed(self) -> None:
        """Mark departure from baseline configuration."""
        self.baseline_departed_at = datetime.now()
        self.events.append(
            AgendaPhaseEvent(
                phase_index=self.current_phase_index,
                phase_name=self.current_phase.name if self.current_phase else "",
                event_type=PhaseEventType.BASELINE_DEPARTED,
            )
        )

    def mark_baseline_restored(self, control: ControlMode) -> None:
        """Mark return to baseline configuration.

        Args:
            control: Control mode of the restoration
        """
        self.baseline_restored_at = datetime.now()
        self.actual_duration_ms = self.elapsed_ms

        # Update control mode if degraded
        if control != ControlMode.POSITIVE:
            self._degrade_control_mode(control)

        self.events.append(
            AgendaPhaseEvent(
                phase_index=self.current_phase_index,
                phase_name=self.current_phase.name if self.current_phase else "",
                event_type=PhaseEventType.BASELINE_RESTORED,
                control_mode=control,
                actual_duration_ms=self.actual_duration_ms,
            )
        )

    def mark_fulfilled(self) -> None:
        """Mark agenda as fulfilled under positive control."""
        if self.control_mode != ControlMode.POSITIVE:
            # Can't be FULFILLED with non-positive control
            self.mark_degraded()
            return

        self.status = AgendaStatus.FULFILLED
        self.resolved_at = datetime.now()
        self.actual_duration_ms = self.elapsed_ms
        self.severity_score = calculate_agenda_severity(self)
        self.events.append(
            AgendaPhaseEvent(
                phase_index=self.current_phase_index,
                phase_name=self.current_phase.name if self.current_phase else "",
                event_type=PhaseEventType.AGENDA_FULFILLED,
                payload={
                    "total_duration_ms": self.actual_duration_ms,
                    "makespan_variance_pct": self.makespan_variance_pct,
                },
            )
        )

    def mark_failed(self, reason: str, error: str | None = None) -> None:
        """Mark agenda as failed.

        Args:
            reason: Why the agenda failed
            error: Optional error message
        """
        self.status = AgendaStatus.FAILED
        self.resolved_at = datetime.now()
        self.actual_duration_ms = self.elapsed_ms
        self.severity_score = calculate_agenda_severity(self)
        self.events.append(
            AgendaPhaseEvent(
                phase_index=self.current_phase_index,
                phase_name=self.current_phase.name if self.current_phase else "",
                event_type=PhaseEventType.AGENDA_FAILED,
                payload={
                    "reason": reason,
                    "failed_at_phase": self.current_phase_index,
                    "last_error": error,
                },
            )
        )

    def mark_degraded(self) -> None:
        """Mark agenda as completed but via degraded (non-positive) path."""
        self.status = AgendaStatus.DEGRADED
        self.resolved_at = datetime.now()
        self.actual_duration_ms = self.elapsed_ms
        self.severity_score = calculate_agenda_severity(self)
        self.events.append(
            AgendaPhaseEvent(
                phase_index=self.current_phase_index,
                phase_name=self.current_phase.name if self.current_phase else "",
                event_type=PhaseEventType.AGENDA_DEGRADED,
                control_mode=self.control_mode,
                payload={
                    "control_mode": self.control_mode.value,
                    "recovery_events": len(
                        [t for t in self.endpoint_transitions if t.control_mode != ControlMode.POSITIVE]
                    ),
                },
            )
        )

    def mark_blocked(self, reason: str) -> None:
        """Mark agenda as blocked and requiring intervention.

        Args:
            reason: Why the agenda is blocked
        """
        self.status = AgendaStatus.BLOCKED
        self.severity_score = calculate_agenda_severity(self)

    def mark_delayed(self) -> None:
        """Mark agenda as delayed but still recoverable."""
        if self.status == AgendaStatus.ON_TRACK:
            self.status = AgendaStatus.DELAYED
            self.severity_score = calculate_agenda_severity(self)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "incident_id": str(self.incident_id),
            "agenda_id": self.agenda_id,
            "agenda_type": self.agenda_type.value,
            "phases": [p.to_dict() for p in self.phases],
            "current_phase_index": self.current_phase_index,
            "scheduler_plan_id": self.scheduler_plan_id,
            "makespan_projection_ms": self.makespan_projection_ms,
            "actual_duration_ms": self.actual_duration_ms,
            "makespan_variance_pct": self.makespan_variance_pct,
            "status": self.status.value,
            "control_mode": self.control_mode.value,
            "severity_score": self.severity_score,
            "endpoint_transitions": [t.to_dict() for t in self.endpoint_transitions],
            "healing_event_ids": [str(h) for h in self.healing_event_ids],
            "created_at": self.created_at.isoformat(),
            "baseline_departed_at": self.baseline_departed_at.isoformat() if self.baseline_departed_at else None,
            "baseline_restored_at": self.baseline_restored_at.isoformat() if self.baseline_restored_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "db_id": self.db_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgendaIncident":
        """Create from dictionary."""
        incident = cls(
            incident_id=UUID(data["incident_id"]) if isinstance(data["incident_id"], str) else data["incident_id"],
            agenda_id=data["agenda_id"],
            agenda_type=AgendaType(data["agenda_type"]),
            phases=[AgendaPhase.from_dict(p) for p in data.get("phases", [])],
            current_phase_index=data.get("current_phase_index", 0),
            scheduler_plan_id=data.get("scheduler_plan_id"),
            makespan_projection_ms=data.get("makespan_projection_ms"),
            actual_duration_ms=data.get("actual_duration_ms", 0),
            status=AgendaStatus(data["status"]),
            control_mode=ControlMode(data.get("control_mode", "positive")),
            severity_score=data.get("severity_score", 0),
            endpoint_transitions=[EndpointTransition.from_dict(t) for t in data.get("endpoint_transitions", [])],
            healing_event_ids=[UUID(h) for h in data.get("healing_event_ids", [])],
            db_id=data.get("db_id"),
        )
        incident.created_at = datetime.fromisoformat(data["created_at"])
        if data.get("baseline_departed_at"):
            incident.baseline_departed_at = datetime.fromisoformat(data["baseline_departed_at"])
        if data.get("baseline_restored_at"):
            incident.baseline_restored_at = datetime.fromisoformat(data["baseline_restored_at"])
        if data.get("resolved_at"):
            incident.resolved_at = datetime.fromisoformat(data["resolved_at"])
        return incident


def detect_control_mode(
    endpoint: str,
    from_state: str,
    to_state: str,
    planned_transitions: list[tuple[str, str, str]] | None = None,
) -> ControlMode:
    """Determine if a transition was positive control or recovery.

    Args:
        endpoint: Endpoint name
        from_state: Previous state
        to_state: New state
        planned_transitions: Optional list of (endpoint, from, to) tuples from agenda plan

    Returns:
        ControlMode indicating how the transition occurred
    """
    # Check if transition was planned
    if planned_transitions:
        for ep, f, t in planned_transitions:
            if ep == endpoint and f == from_state and t == to_state:
                return ControlMode.POSITIVE

    # Failure recovery: Endpoint was UNHEALTHY, now HEALTHY
    if from_state.upper() == "UNHEALTHY" and to_state.upper() == "HEALTHY":
        return ControlMode.FAILURE_RECOVERY

    # Restart recovery: Endpoint was ABSENT (engine restart), now HEALTHY
    if from_state.upper() == "ABSENT" and to_state.upper() == "HEALTHY":
        return ControlMode.RESTART_RECOVERY

    # Restart recovery: Endpoint was STOPPED unexpectedly, now HEALTHY
    if from_state.upper() == "STOPPED" and to_state.upper() == "HEALTHY":
        # Check if this was a planned stop (would be in planned_transitions)
        # If not planned, it's a restart recovery
        if not planned_transitions:
            return ControlMode.RESTART_RECOVERY

    # Default: assume positive control
    return ControlMode.POSITIVE


def calculate_agenda_severity(incident: AgendaIncident) -> int:
    """Compute severity from makespan variance and control mode.

    Severity is used for RPN calculation and escalation decisions.
    Base severity is 5, modified by:
    - Makespan variance: >20% variance increases severity
    - Control mode: Non-positive control increases severity
    - Status: BLOCKED is highest severity

    Returns:
        Severity score (typically 25-500 range for RPN calculation)
    """
    base_severity = 5

    # Makespan factor: >20% variance increases severity
    variance = abs(incident.makespan_variance_pct)
    if variance > 0.2:
        makespan_factor = min(2.0, 1.0 + variance)
    else:
        makespan_factor = 1.0

    # Control mode factor: Non-positive control increases severity
    control_factors = {
        ControlMode.POSITIVE: 1.0,
        ControlMode.FAILURE_RECOVERY: 1.5,
        ControlMode.RESTART_RECOVERY: 2.0,
    }
    control_factor = control_factors.get(incident.control_mode, 1.0)

    # Status factor: Blocked is highest severity
    status_factors = {
        AgendaStatus.SCHEDULING: 0.5,
        AgendaStatus.ON_TRACK: 0.8,
        AgendaStatus.DELAYED: 1.3,
        AgendaStatus.BLOCKED: 2.0,
        AgendaStatus.FULFILLED: 0.5,
        AgendaStatus.FAILED: 1.5,
        AgendaStatus.DEGRADED: 1.2,
    }
    status_factor = status_factors.get(incident.status, 1.0)

    # RPN style: S * O * D where O and D are fixed at 5 each
    # This gives us a range of roughly 25-500
    return int(base_severity * makespan_factor * control_factor * status_factor * 5 * 5)
