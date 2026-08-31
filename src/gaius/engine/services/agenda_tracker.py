"""Agenda-centric tracking service with operations/incidents separation.

Tracks Agenda progress against OR-Tools makespan projections and
detects control mode (positive vs failure vs restart recovery).

This service is the bridge between:
- OrchestratorService (workload begin/complete lifecycle)
- ReconciliationService (endpoint state transitions)
- HealthObserverService (incident escalation)

Key concepts:
- Agenda: Scheduled capability phases with makespan projections
- Positive Control: Intentional orchestrated transitions
- Resolution: Return to baseline under positive control only

Table Separation:
- agenda_operations: All workload executions (routine tracking for metrics)
- agenda_incidents: Only problems requiring attention (BLOCKED, FAILED, DEGRADED)

Operations become incidents when:
- Control mode degrades from POSITIVE to FAILURE_RECOVERY or RESTART_RECOVERY
- Makespan variance exceeds tolerance
- Workload fails

Usage:
    tracker = AgendaTracker(orchestrator, reconciliation, db_pool)
    await tracker.start()

    # OrchestratorService calls:
    operation = await tracker.on_workload_begin(request, schedule_result)
    await tracker.on_workload_complete(workload_id, result)

    # ReconciliationService calls:
    await tracker.on_endpoint_transition(endpoint, from_state, to_state, control)
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional
from uuid import UUID, uuid4

from ..incidents import (
    AgendaIncident,
    AgendaPhase,
    AgendaPhaseEvent,
    AgendaStatus,
    AgendaType,
    ControlMode,
    PhaseEventType,
    calculate_agenda_severity,
    detect_control_mode,
)
from ..incidents.agenda_incident import EndpointTransition
from ..resources.reconciliation import EndpointState


@dataclass
class AgendaOperation:
    """Routine workload operation for metrics tracking.

    This represents a normal workload execution (not an incident).
    Only escalates to AgendaIncident if problems occur.
    """

    workload_id: str
    workload_type: AgendaType
    operation_id: UUID = field(default_factory=uuid4)

    # Phase tracking
    phases: list[AgendaPhase] = field(default_factory=list)
    current_phase_index: int = 0

    # Makespan tracking
    scheduler_plan_id: Optional[str] = None
    makespan_projection_ms: Optional[int] = None
    actual_duration_ms: int = 0
    makespan_variance_pct: float = 0.0

    # Status tracking
    status: AgendaStatus = AgendaStatus.SCHEDULING
    control_mode: ControlMode = ControlMode.POSITIVE

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Endpoint transitions (for state recovery)
    endpoint_transitions: list[EndpointTransition] = field(default_factory=list)

    # Link to incident if escalated
    escalated_to_incident_id: Optional[int] = None

    # Database ID
    db_id: Optional[int] = None

    @property
    def elapsed_ms(self) -> int:
        """Time elapsed since operation started."""
        if self.started_at:
            elapsed = datetime.now(timezone.utc) - self.started_at
            return int(elapsed.total_seconds() * 1000)
        return 0

    @property
    def current_phase(self) -> Optional[AgendaPhase]:
        """Get the current phase."""
        if 0 <= self.current_phase_index < len(self.phases):
            return self.phases[self.current_phase_index]
        return None

    def mark_started(self) -> None:
        """Mark operation as started."""
        self.started_at = datetime.now(timezone.utc)
        self.status = AgendaStatus.ON_TRACK

    def mark_fulfilled(self) -> None:
        """Mark operation as successfully completed."""
        self.completed_at = datetime.now(timezone.utc)
        self.status = AgendaStatus.FULFILLED
        self._update_makespan_variance()

    def mark_degraded(self) -> None:
        """Mark operation as completed but degraded."""
        self.completed_at = datetime.now(timezone.utc)
        self.status = AgendaStatus.DEGRADED
        self._update_makespan_variance()

    def mark_failed(self) -> None:
        """Mark operation as failed."""
        self.completed_at = datetime.now(timezone.utc)
        self.status = AgendaStatus.FAILED
        self._update_makespan_variance()

    def _update_makespan_variance(self) -> None:
        """Update makespan variance percentage."""
        if self.makespan_projection_ms and self.makespan_projection_ms > 0:
            self.actual_duration_ms = self.elapsed_ms
            variance = (self.actual_duration_ms - self.makespan_projection_ms) / self.makespan_projection_ms
            self.makespan_variance_pct = variance

    def record_transition(
        self,
        endpoint: str,
        from_state: str,
        to_state: str,
        control: ControlMode,
    ) -> None:
        """Record an endpoint transition."""
        transition = EndpointTransition(
            endpoint=endpoint,
            from_state=from_state,
            to_state=to_state,
            control_mode=control,
            timestamp=datetime.now(timezone.utc),
        )
        self.endpoint_transitions.append(transition)

        # Degrade control mode if needed
        if control != ControlMode.POSITIVE and self.control_mode == ControlMode.POSITIVE:
            self.control_mode = control

if TYPE_CHECKING:
    from asyncpg import Pool

    from ..scheduling import SchedulingResult, TransitionPlan
    from ..workloads import WorkloadRequest, WorkloadResult

logger = logging.getLogger(__name__)

# Callback types
OperationCallback = Callable[[AgendaOperation], Coroutine[Any, Any, None]]
IncidentCallback = Callable[[AgendaIncident], Coroutine[Any, Any, None]]


class AgendaTracker:
    """Tracks workload operations for metrics and state recovery.

    This service tracks all workload executions in agenda_operations.
    Escalation to agenda_incidents is handled by HealthObserverService
    through the ACP-mediated health framework.

    Responsibilities:
    - Create AgendaOperation when workload begins
    - Track phase transitions and control mode
    - Persist to agenda_operations for metrics
    - Notify HealthObserver of control mode changes for potential escalation

    Table separation:
    - agenda_operations: All workloads (managed here)
    - agenda_incidents: Problems only (managed by HealthObserverService)

    Attributes:
        _active_operations: Currently active operations by workload_id
    """

    def __init__(
        self,
        db_pool: Optional["Pool"] = None,
        baseline_endpoints: Optional[list[str]] = None,
    ):
        """Initialize the agenda tracker.

        Args:
            db_pool: Database pool for persistence
            baseline_endpoints: List of endpoints that constitute baseline
        """
        self._db_pool = db_pool
        self._baseline_endpoints = baseline_endpoints or ["orchestrator", "thinking"]

        # Active operations (routine tracking)
        self._active_operations: dict[str, AgendaOperation] = {}

        # Callbacks for operation lifecycle
        self._on_operation_start: list[OperationCallback] = []
        self._on_operation_complete: list[OperationCallback] = []
        self._on_control_degraded: list[OperationCallback] = []  # For HealthObserver escalation

        # Planned transitions for the current operation
        # List of (endpoint, from_state, to_state) tuples
        self._planned_transitions: dict[str, list[tuple[str, str, str]]] = {}

        # Statistics
        self._operations_created = 0
        self._operations_fulfilled = 0
        self._operations_degraded = 0
        self._operations_failed = 0

        self._running = False
        self._persistence_task: Optional[asyncio.Task] = None

        logger.info("AgendaTracker initialized (writes to agenda_operations only)")

    async def start(self) -> None:
        """Start the agenda tracker."""
        if self._running:
            return

        self._running = True

        # Restore active operations from database
        await self._restore_operations_from_db()

        # Start periodic persistence
        self._persistence_task = asyncio.create_task(self._persistence_loop())

        logger.info(
            f"AgendaTracker started with {len(self._active_operations)} active operations"
        )

    async def stop(self) -> None:
        """Stop the agenda tracker."""
        if not self._running:
            return

        self._running = False

        # Stop persistence loop
        if self._persistence_task:
            self._persistence_task.cancel()
            try:
                await self._persistence_task
            except asyncio.CancelledError:
                pass

        # Persist final state
        await self._persist_all()

        logger.info("AgendaTracker stopped")

    # ─────────────────────────────────────────────────────────────────────────
    # Workload Lifecycle Hooks (from OrchestratorService)
    # ─────────────────────────────────────────────────────────────────────────

    async def on_workload_begin(
        self,
        request: "WorkloadRequest",
        schedule_result: Optional["SchedulingResult"] = None,
    ) -> AgendaOperation:
        """Called when OrchestratorService.begin_workload() starts.

        Creates a new AgendaOperation for routine tracking.
        Escalation to incidents is handled by HealthObserverService.

        Args:
            request: The workload request
            schedule_result: Optional OR-Tools scheduling result

        Returns:
            The created AgendaOperation
        """
        from ..workloads import WorkloadType

        # Map WorkloadType to AgendaType
        type_map = {
            WorkloadType.INIT: AgendaType.INFERENCE,
            WorkloadType.SWARM: AgendaType.SWARM,
            WorkloadType.INFERENCE: AgendaType.INFERENCE,
            WorkloadType.EMBEDDING: AgendaType.INFERENCE,
            WorkloadType.EVOLUTION: AgendaType.EVOLUTION,
            WorkloadType.FLOW: AgendaType.FLOW,
        }

        agenda_type = type_map.get(request.workload_type, AgendaType.INFERENCE)

        # Build phases from required capabilities
        phases = []

        # Extract plan if available (narrow type once for multiple uses)
        plan = schedule_result.plan if schedule_result else None

        # Phase 0: Baseline eviction (if needed)
        if plan and plan.evicted_endpoints:
            phases.append(
                AgendaPhase(
                    name="BASELINE_EVICTION",
                    required_capabilities=[],
                    target_endpoints=plan.evicted_endpoints,
                )
            )

        # Phase 1+: Capability phases
        for cap in request.required_capabilities:
            phases.append(
                AgendaPhase(
                    name=f"{cap.value}_WORKLOAD",
                    required_capabilities=[cap.value],
                    target_endpoints=[f"cap_{cap.value}"],
                )
            )

        # Final phase: Baseline restoration
        if plan and plan.restore_plan:
            phases.append(
                AgendaPhase(
                    name="BASELINE_RESTORATION",
                    required_capabilities=[],
                    target_endpoints=plan.restore_plan,
                )
            )

        # Create operation (not incident)
        operation = AgendaOperation(
            workload_id=request.workload_id,
            workload_type=agenda_type,
            phases=phases,
        )

        # Add scheduling info if available
        if schedule_result and schedule_result.success and schedule_result.plan is not None:
            plan = schedule_result.plan
            operation.scheduler_plan_id = (
                str(plan.plan_id)
                if hasattr(plan, "plan_id")
                else "unknown"
            )
            operation.makespan_projection_ms = plan.total_makespan_ms

            # Track planned transitions for control mode detection
            self._planned_transitions[request.workload_id] = self._extract_planned_transitions(
                plan
            )

        # Mark operation as started
        operation.mark_started()

        # Track and persist
        self._active_operations[request.workload_id] = operation
        self._operations_created += 1

        await self._persist_operation(operation)

        # Notify callbacks
        for callback in self._on_operation_start:
            try:
                await callback(operation)
            except Exception as e:
                logger.warning(f"Operation start callback error: {e}")

        logger.info(
            f"Created operation {operation.operation_id} for workload {request.workload_id} "
            f"({agenda_type.value}, {len(phases)} phases)"
        )

        return operation

    async def on_workload_complete(
        self,
        workload_id: str,
        result: "WorkloadResult",
    ) -> Optional[AgendaOperation]:
        """Called when workload finishes - complete the operation.

        Args:
            workload_id: ID of the completed workload
            result: The workload result

        Returns:
            The completed AgendaOperation, or None if not found
        """
        operation = self._active_operations.get(workload_id)
        if not operation:
            logger.warning(f"No operation found for workload {workload_id}")
            return None

        # Determine final status based on control mode and result
        if result.success:
            if operation.control_mode == ControlMode.POSITIVE:
                operation.mark_fulfilled()
                self._operations_fulfilled += 1
            else:
                operation.mark_degraded()
                self._operations_degraded += 1
        else:
            operation.mark_failed()
            self._operations_failed += 1

        # Clean up planned transitions
        self._planned_transitions.pop(workload_id, None)

        # Persist final state
        await self._persist_operation(operation)

        # Move to completed
        del self._active_operations[workload_id]

        # Notify callbacks
        for callback in self._on_operation_complete:
            try:
                await callback(operation)
            except Exception as e:
                logger.warning(f"Operation complete callback error: {e}")

        logger.info(
            f"Completed operation {operation.operation_id}: "
            f"status={operation.status.value}, control_mode={operation.control_mode.value}, "
            f"makespan_variance={operation.makespan_variance_pct:.1%}"
        )

        return operation

    def _extract_planned_transitions(
        self,
        plan: "TransitionPlan",
    ) -> list[tuple[str, str, str]]:
        """Extract planned transitions from an OR-Tools plan.

        Args:
            plan: TransitionPlan from scheduler

        Returns:
            List of (endpoint, from_state, to_state) tuples
        """
        from ..scheduling import TransitionType

        transitions = []

        for step in plan.steps:
            if step.transition_type == TransitionType.STOP_ENDPOINT:
                transitions.append((step.endpoint_name, "HEALTHY", "STOPPED"))
            elif step.transition_type == TransitionType.START_ENDPOINT:
                transitions.append((step.endpoint_name, "STOPPED", "HEALTHY"))

        return transitions

    # ─────────────────────────────────────────────────────────────────────────
    # Endpoint Transition Hooks (from ReconciliationService)
    # ─────────────────────────────────────────────────────────────────────────

    async def on_endpoint_transition(
        self,
        endpoint: str,
        from_state: EndpointState,
        to_state: EndpointState,
        observed_control: Optional[ControlMode] = None,
    ) -> None:
        """Called when ReconciliationService observes state change.

        Updates all active operations that involve this endpoint.
        If control mode degrades, notifies HealthObserver for potential escalation.

        Args:
            endpoint: Endpoint name
            from_state: Previous state
            to_state: New state
            observed_control: Override control mode if already detected
        """
        from_str = from_state.value.upper()
        to_str = to_state.value.upper()

        # Find operations that involve this endpoint
        affected_workloads = []
        for workload_id, operation in self._active_operations.items():
            # Check if any phase targets this endpoint
            for phase in operation.phases:
                if endpoint in phase.target_endpoints:
                    affected_workloads.append(workload_id)
                    break

        if not affected_workloads:
            return

        # Detect control mode and update operations
        for workload_id in affected_workloads:
            operation = self._active_operations[workload_id]
            planned = self._planned_transitions.get(workload_id, [])

            if observed_control:
                control = observed_control
            else:
                control = detect_control_mode(
                    endpoint=endpoint,
                    from_state=from_str,
                    to_state=to_str,
                    planned_transitions=planned,
                )

            # Check if control mode is degrading
            was_positive = operation.control_mode == ControlMode.POSITIVE

            # Record the transition
            operation.record_transition(
                endpoint=endpoint,
                from_state=from_str,
                to_state=to_str,
                control=control,
            )

            # Update actual duration
            operation.actual_duration_ms = operation.elapsed_ms

            # Notify HealthObserver if control mode degraded (for potential escalation)
            if was_positive and operation.control_mode != ControlMode.POSITIVE:
                logger.warning(
                    f"Operation {workload_id} control degraded to {operation.control_mode.value}"
                )
                for callback in self._on_control_degraded:
                    try:
                        await callback(operation)
                    except Exception as e:
                        logger.warning(f"Control degraded callback error: {e}")

            # Persist updated state
            await self._persist_operation(operation)

            logger.debug(
                f"Recorded transition for {workload_id}: "
                f"{endpoint} {from_str}->{to_str} (control={control.value})"
            )

    async def on_engine_restart(self) -> None:
        """Called when engine restart is detected.

        Degrades all active operations to RESTART_RECOVERY control mode.
        This notifies HealthObserver for potential escalation to incidents.
        """
        for workload_id, operation in self._active_operations.items():
            if operation.control_mode == ControlMode.POSITIVE:
                operation.control_mode = ControlMode.RESTART_RECOVERY
                logger.warning(
                    f"Operation {workload_id} degraded to RESTART_RECOVERY due to engine restart"
                )

                # Notify HealthObserver for potential escalation
                for callback in self._on_control_degraded:
                    try:
                        await callback(operation)
                    except Exception as e:
                        logger.warning(f"Control degraded callback error: {e}")

                await self._persist_operation(operation)

    # ─────────────────────────────────────────────────────────────────────────
    # Callback Registration
    # ─────────────────────────────────────────────────────────────────────────

    def on_operation_started(self, callback: OperationCallback) -> None:
        """Register callback for new operation creation.

        Args:
            callback: Async function receiving AgendaOperation
        """
        self._on_operation_start.append(callback)

    def on_operation_completed(self, callback: OperationCallback) -> None:
        """Register callback for operation completion.

        Args:
            callback: Async function receiving completed AgendaOperation
        """
        self._on_operation_complete.append(callback)

    def on_control_degraded(self, callback: OperationCallback) -> None:
        """Register callback for control mode degradation.

        HealthObserver uses this to decide whether to escalate to incident.

        Args:
            callback: Async function receiving degraded AgendaOperation
        """
        self._on_control_degraded.append(callback)

    # ─────────────────────────────────────────────────────────────────────────
    # Query Interface
    # ─────────────────────────────────────────────────────────────────────────

    def get_active_operations(self) -> list[AgendaOperation]:
        """Get all active operations.

        Returns:
            List of active AgendaOperation objects
        """
        return list(self._active_operations.values())

    def get_operation(self, workload_id: str) -> Optional[AgendaOperation]:
        """Get a specific operation.

        Args:
            workload_id: The workload ID

        Returns:
            AgendaOperation or None
        """
        return self._active_operations.get(workload_id)

    def is_endpoint_in_scheduled_transition(self, endpoint: str) -> bool:
        """Check if an endpoint is part of a scheduled operation.

        Used by HealthObserver to distinguish between:
        - Intentionally stopped/starting (part of makespan schedule) → not an incident
        - Unexpectedly failed (not part of any operation) → create incident

        Args:
            endpoint: Endpoint name to check

        Returns:
            True if endpoint is in an active operation with POSITIVE control
        """
        for operation in self._active_operations.values():
            # Only consider operations under positive control
            if operation.control_mode != ControlMode.POSITIVE:
                continue

            # Check if endpoint is a target of any phase
            for phase in operation.phases:
                if endpoint in phase.target_endpoints:
                    return True

            # Also check planned transitions
            workload_id = str(operation.workload_id) if operation.workload_id else ""
            planned = self._planned_transitions.get(workload_id, [])
            for ep, _, _ in planned:
                if ep == endpoint:
                    return True

        return False

    def get_scheduled_endpoint_state(self, endpoint: str) -> str | None:
        """Get the expected state for an endpoint in a scheduled operation.

        Args:
            endpoint: Endpoint name

        Returns:
            Expected state ("HEALTHY", "STOPPED") or None if not scheduled
        """
        for workload_id, operation in self._active_operations.items():
            if operation.control_mode != ControlMode.POSITIVE:
                continue

            planned = self._planned_transitions.get(workload_id, [])
            for ep, _, to_state in planned:
                if ep == endpoint:
                    return to_state

        return None

    def get_status(self) -> dict[str, Any]:
        """Get tracker status for API.

        Returns:
            Status dict with statistics and active operations
        """
        return {
            "running": self._running,
            "active_operations": len(self._active_operations),
            "operations_created": self._operations_created,
            "operations_fulfilled": self._operations_fulfilled,
            "operations_degraded": self._operations_degraded,
            "operations_failed": self._operations_failed,
            "baseline_endpoints": self._baseline_endpoints,
            "operations": {
                workload_id: {
                    "operation_id": str(operation.operation_id),
                    "type": operation.workload_type.value,
                    "status": operation.status.value,
                    "control_mode": operation.control_mode.value,
                    "current_phase": operation.current_phase.name if operation.current_phase else None,
                    "makespan_variance_pct": operation.makespan_variance_pct,
                    "elapsed_ms": operation.elapsed_ms,
                }
                for workload_id, operation in self._active_operations.items()
            },
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────────────────────────────────

    async def _persistence_loop(self) -> None:
        """Periodically persist active operations."""
        while self._running:
            try:
                await asyncio.sleep(30)  # Every 30 seconds
                await self._persist_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Persistence loop error: {e}")

    async def _persist_all(self) -> None:
        """Persist all active operations to database."""
        # Snapshot: each awaited persist yields the loop, and workload
        # lifecycle handlers add/remove operations concurrently —
        # iterating the live dict raised "dictionary changed size during
        # iteration" (observed 2026-08-31).
        for operation in list(self._active_operations.values()):
            try:
                await self._persist_operation(operation)
            except Exception as e:
                logger.error(f"Failed to persist operation {operation.workload_id}: {e}")

    async def _persist_operation(self, operation: AgendaOperation) -> None:
        """Persist a single operation to agenda_operations table.

        Args:
            operation: The operation to persist
        """
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                if operation.db_id:
                    # Update existing
                    await conn.execute(
                        """
                        UPDATE agenda_operations SET
                            phases = $1,
                            current_phase_index = $2,
                            scheduler_plan_id = $3,
                            makespan_projection_ms = $4,
                            actual_duration_ms = $5,
                            makespan_variance_pct = $6,
                            status = $7::agenda_status,
                            control_mode = $8::control_mode,
                            started_at = $9,
                            completed_at = $10,
                            endpoint_transitions = $11,
                            escalated_to_incident_id = $12
                        WHERE id = $13
                        """,
                        json.dumps([p.to_dict() for p in operation.phases]),
                        operation.current_phase_index,
                        operation.scheduler_plan_id,
                        operation.makespan_projection_ms,
                        operation.actual_duration_ms,
                        operation.makespan_variance_pct,
                        operation.status.value,
                        operation.control_mode.value,
                        operation.started_at,
                        operation.completed_at,
                        json.dumps([t.to_dict() for t in operation.endpoint_transitions]),
                        operation.escalated_to_incident_id,
                        operation.db_id,
                    )
                else:
                    # Insert new
                    row = await conn.fetchrow(
                        """
                        INSERT INTO agenda_operations (
                            operation_id, workload_id, workload_type, phases,
                            current_phase_index, scheduler_plan_id,
                            makespan_projection_ms, actual_duration_ms,
                            makespan_variance_pct, status, control_mode,
                            created_at, started_at, completed_at,
                            endpoint_transitions, escalated_to_incident_id
                        ) VALUES (
                            $1, $2, $3::agenda_type, $4,
                            $5, $6, $7, $8, $9,
                            $10::agenda_status, $11::control_mode,
                            $12, $13, $14, $15, $16
                        )
                        RETURNING id
                        """,
                        operation.operation_id,
                        operation.workload_id,
                        operation.workload_type.value,
                        json.dumps([p.to_dict() for p in operation.phases]),
                        operation.current_phase_index,
                        operation.scheduler_plan_id,
                        operation.makespan_projection_ms,
                        operation.actual_duration_ms,
                        operation.makespan_variance_pct,
                        operation.status.value,
                        operation.control_mode.value,
                        operation.created_at,
                        operation.started_at,
                        operation.completed_at,
                        json.dumps([t.to_dict() for t in operation.endpoint_transitions]),
                        operation.escalated_to_incident_id,
                    )
                    operation.db_id = row["id"]

        except Exception as e:
            logger.error(f"Operation persistence error: {e}")

    async def _restore_operations_from_db(self) -> None:
        """Restore active operations from database on startup."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT *
                    FROM agenda_operations
                    WHERE status NOT IN ('fulfilled', 'failed', 'degraded')
                    ORDER BY created_at DESC
                    """
                )

                for row in rows:
                    try:
                        operation = AgendaOperation(
                            operation_id=row["operation_id"],
                            workload_id=row["workload_id"],
                            workload_type=AgendaType(row["workload_type"]),
                            phases=[
                                AgendaPhase.from_dict(p)
                                for p in json.loads(row["phases"])
                            ],
                            current_phase_index=row["current_phase_index"],
                            scheduler_plan_id=row["scheduler_plan_id"],
                            makespan_projection_ms=row["makespan_projection_ms"],
                            actual_duration_ms=row["actual_duration_ms"],
                            status=AgendaStatus(row["status"]),
                            control_mode=ControlMode(row["control_mode"]),
                            db_id=row["id"],
                        )
                        operation.created_at = row["created_at"]
                        operation.started_at = row["started_at"]
                        operation.completed_at = row["completed_at"]
                        operation.escalated_to_incident_id = row["escalated_to_incident_id"]

                        # Restore endpoint transitions
                        if row["endpoint_transitions"]:
                            operation.endpoint_transitions = [
                                EndpointTransition.from_dict(t)
                                for t in json.loads(row["endpoint_transitions"])
                            ]

                        # Engine restart detected - degrade control mode
                        if operation.control_mode == ControlMode.POSITIVE:
                            operation.control_mode = ControlMode.RESTART_RECOVERY
                            logger.warning(
                                f"Restored operation {operation.workload_id} with RESTART_RECOVERY "
                                "due to engine restart"
                            )

                        self._active_operations[operation.workload_id] = operation

                    except Exception as e:
                        logger.error(f"Failed to restore operation {row['workload_id']}: {e}")

                logger.info(
                    f"Restored {len(self._active_operations)} active operations from database"
                )

        except Exception as e:
            logger.error(f"Database restoration error: {e}")


# Module-level singleton
_tracker_instance: AgendaTracker | None = None


def get_agenda_tracker() -> AgendaTracker | None:
    """Get the singleton AgendaTracker instance.

    Returns:
        AgendaTracker instance or None if not initialized
    """
    return _tracker_instance


def set_agenda_tracker(tracker: AgendaTracker) -> None:
    """Set the singleton AgendaTracker instance.

    Called by engine startup to register the active tracker.

    Args:
        tracker: The AgendaTracker instance to use
    """
    global _tracker_instance
    _tracker_instance = tracker
