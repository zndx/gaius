"""
Phase Change Pattern for Resilient Dynamic Workload Coordination.

A Phase Change occurs when the system transitions between operational modes,
such as loading ColNomic for vector search or restoring instruct after search.

This module implements:
1. PhaseChangeType/Status enums - Define transition semantics
2. PhaseChangeEvent - Track individual transitions
3. PhaseChangeProfile - Accumulate timing statistics for decision support
4. PhaseChangeObserver - Watch OTel events and confirm HEALTHY status

Design Philosophy:
    "Premature performance optimization is the root of all evil."

The solution prioritizes resilience over speed by:
- Awaiting positive confirmation of HEALTHY status before proceeding
- Accumulating timing statistics for future decision support
- Deferring threshold-based interventions until statistical power is achieved
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional

from opentelemetry import trace

if TYPE_CHECKING:
    from gaius.engine.services.orchestrator_service import OrchestratorService

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class PhaseChangeType(Enum):
    """Types of phase transitions in the system.

    Each phase change represents a model loading/unloading transition:
    - COLNOMIC_LOAD: Load ColNomic for vector search (evicts instruct)
    - INSTRUCT_RESTORE: Restore instruct after vector search
    - REASONING_LOAD: Load reasoning model (evicts baseline)
    - BASELINE_RESTORE: Restore baseline after reasoning
    """

    COLNOMIC_LOAD = "colnomic_load"
    INSTRUCT_RESTORE = "instruct_restore"
    REASONING_LOAD = "reasoning_load"
    BASELINE_RESTORE = "baseline_restore"


class PhaseChangeStatus(Enum):
    """Status of a phase change transition."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    CONVERGED = "converged"
    FAILED = "failed"


@dataclass
class PhaseChangeEvent:
    """Represents a single phase change transition.

    Tracks the lifecycle of a model loading/unloading operation from
    initiation through convergence (HEALTHY confirmation).
    """

    change_type: PhaseChangeType
    status: PhaseChangeStatus
    started_at: datetime
    converged_at: Optional[datetime] = None
    target_endpoint: str = ""
    otel_trace_id: str = ""
    progress_pct: int = 0
    error_message: Optional[str] = None

    @property
    def duration_ms(self) -> Optional[int]:
        """Duration in milliseconds from start to convergence."""
        if self.converged_at:
            delta = self.converged_at - self.started_at
            return int(delta.total_seconds() * 1000)
        return None

    def to_dict(self) -> dict:
        """Convert to dictionary for gRPC response."""
        return {
            "change_type": self.change_type.value,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "converged_at": self.converged_at.isoformat() if self.converged_at else None,
            "target_endpoint": self.target_endpoint,
            "otel_trace_id": self.otel_trace_id,
            "progress_pct": self.progress_pct,
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
        }


@dataclass
class PhaseChangeProfile:
    """Accumulated statistics for a phase change type.

    Used for decision support once sufficient data is collected.
    Statistical power requires ~70 samples (~1 week at 10 changes/day).
    """

    change_type: PhaseChangeType
    sample_count: int = 0
    total_duration_ms: int = 0
    min_duration_ms: Optional[int] = None
    max_duration_ms: Optional[int] = None
    failures: int = 0

    # Threshold for statistical significance
    STATISTICAL_POWER_THRESHOLD: int = 70

    @property
    def avg_duration_ms(self) -> Optional[float]:
        """Average duration in milliseconds."""
        if self.sample_count > 0:
            return self.total_duration_ms / self.sample_count
        return None

    @property
    def has_statistical_power(self) -> bool:
        """Whether sufficient data exists for decision support.

        Requires ~1 week of data (70 samples at 10/day) before
        enabling threshold-based interventions.
        """
        return self.sample_count >= self.STATISTICAL_POWER_THRESHOLD

    @property
    def failure_rate(self) -> float:
        """Failure rate as a fraction (0.0 - 1.0)."""
        if self.sample_count + self.failures > 0:
            return self.failures / (self.sample_count + self.failures)
        return 0.0

    def update(self, event: PhaseChangeEvent) -> None:
        """Update profile with a completed phase change event."""
        if event.status == PhaseChangeStatus.CONVERGED and event.duration_ms:
            self.sample_count += 1
            self.total_duration_ms += event.duration_ms

            if self.min_duration_ms is None or event.duration_ms < self.min_duration_ms:
                self.min_duration_ms = event.duration_ms
            if self.max_duration_ms is None or event.duration_ms > self.max_duration_ms:
                self.max_duration_ms = event.duration_ms

        if event.status == PhaseChangeStatus.FAILED:
            self.failures += 1

    def to_dict(self) -> dict:
        """Convert to dictionary for persistence/display."""
        return {
            "change_type": self.change_type.value,
            "sample_count": self.sample_count,
            "total_duration_ms": self.total_duration_ms,
            "min_duration_ms": self.min_duration_ms,
            "max_duration_ms": self.max_duration_ms,
            "avg_duration_ms": self.avg_duration_ms,
            "failures": self.failures,
            "failure_rate": self.failure_rate,
            "has_statistical_power": self.has_statistical_power,
        }


class PhaseChangeObserver:
    """Watches OTel events for phase change progress and confirms HEALTHY status.

    This is the core reliability mechanism:
    1. Initiate the phase change via orchestrator
    2. Watch for progress (via status polling)
    3. Confirm HEALTHY status before returning

    The observer accumulates timing statistics for decision support,
    but defers threshold-based interventions until statistical power
    is achieved (~1 week of baseline data per profile).
    """

    def __init__(self, orchestrator: OrchestratorService) -> None:
        """Initialize observer with orchestrator reference.

        Args:
            orchestrator: OrchestratorService for endpoint operations
        """
        self._orchestrator = orchestrator
        self._active_changes: dict[str, PhaseChangeEvent] = {}
        self._profiles: dict[PhaseChangeType, PhaseChangeProfile] = {
            t: PhaseChangeProfile(change_type=t) for t in PhaseChangeType
        }
        self._db = None  # Set by orchestrator if persistence enabled

    async def await_phase_change(
        self,
        change_type: PhaseChangeType,
        target_endpoint: str,
        timeout_s: float = 120.0,
    ) -> PhaseChangeEvent:
        """Wait for a phase change to converge (HEALTHY status confirmed).

        This method blocks until:
        1. The target endpoint reaches HEALTHY status, OR
        2. The endpoint reaches FAILED/STOPPED status, OR
        3. The timeout is exceeded

        Args:
            change_type: Type of phase change (for statistics)
            target_endpoint: Endpoint name to ensure healthy
            timeout_s: Maximum seconds to wait for convergence

        Returns:
            PhaseChangeEvent with final status and duration
        """
        with tracer.start_as_current_span(
            "phase_change.await",
            attributes={
                "change_type": change_type.value,
                "target_endpoint": target_endpoint,
                "timeout_s": timeout_s,
            },
        ) as span:
            event = PhaseChangeEvent(
                change_type=change_type,
                status=PhaseChangeStatus.PENDING,
                started_at=datetime.now(timezone.utc),
                target_endpoint=target_endpoint,
                otel_trace_id=format(span.get_span_context().trace_id, "032x"),
            )

            change_id = f"{change_type.value}:{target_endpoint}:{event.started_at.isoformat()}"
            self._active_changes[change_id] = event

            try:
                # Initiate the phase change
                event.status = PhaseChangeStatus.IN_PROGRESS
                span.set_attribute("status", "in_progress")

                logger.info(
                    "Phase change initiated: %s -> %s",
                    change_type.value,
                    target_endpoint,
                )

                # Request endpoint via orchestrator
                try:
                    await asyncio.wait_for(
                        self._orchestrator.ensure_endpoint(target_endpoint),
                        timeout=timeout_s,
                    )
                except asyncio.TimeoutError:
                    event.status = PhaseChangeStatus.FAILED
                    event.error_message = f"ensure_endpoint timed out after {timeout_s}s"
                    span.set_attribute("error", event.error_message)
                    logger.warning("Phase change ensure_endpoint timeout: %s", target_endpoint)
                    self._update_profile(event)
                    return event

                # Wait for HEALTHY confirmation
                remaining_timeout = timeout_s - (
                    datetime.now(timezone.utc) - event.started_at
                ).total_seconds()

                if remaining_timeout <= 0:
                    event.status = PhaseChangeStatus.FAILED
                    event.error_message = "No time remaining for health confirmation"
                    span.set_attribute("error", event.error_message)
                    self._update_profile(event)
                    return event

                healthy = await self._await_healthy_confirmation(
                    target_endpoint,
                    timeout_s=remaining_timeout,
                )

                if healthy:
                    event.status = PhaseChangeStatus.CONVERGED
                    event.converged_at = datetime.now(timezone.utc)
                    span.set_attribute("status", "converged")
                    span.set_attribute("duration_ms", event.duration_ms)
                    logger.info(
                        "Phase change converged: %s -> %s in %dms",
                        change_type.value,
                        target_endpoint,
                        event.duration_ms,
                    )
                else:
                    event.status = PhaseChangeStatus.FAILED
                    event.error_message = "Endpoint did not reach HEALTHY status"
                    span.set_attribute("error", event.error_message)
                    logger.warning(
                        "Phase change failed: %s -> %s (not healthy)",
                        change_type.value,
                        target_endpoint,
                    )

                # Update profile statistics
                self._update_profile(event)

                # Persist if database available
                if self._db:
                    await self._persist_profile(self._profiles[change_type])

                return event

            finally:
                del self._active_changes[change_id]

    async def _await_healthy_confirmation(
        self,
        endpoint: str,
        timeout_s: float,
        poll_interval_s: float = 1.0,
    ) -> bool:
        """Poll until endpoint reaches HEALTHY status.

        Args:
            endpoint: Endpoint name to check
            timeout_s: Maximum seconds to wait
            poll_interval_s: Interval between polls

        Returns:
            True if endpoint is HEALTHY, False otherwise
        """
        deadline = time.time() + timeout_s

        while time.time() < deadline:
            status = await self._orchestrator.get_endpoint_status_async(endpoint)

            if status == "PROCESS_STATUS_HEALTHY":
                return True
            if status in ("PROCESS_STATUS_FAILED", "PROCESS_STATUS_STOPPED"):
                return False

            # Update active change progress
            for change in self._active_changes.values():
                if change.target_endpoint == endpoint:
                    # Estimate progress based on elapsed time
                    elapsed = (datetime.now(timezone.utc) - change.started_at).total_seconds()
                    profile = self._profiles.get(change.change_type)
                    if profile and profile.avg_duration_ms:
                        expected_s = profile.avg_duration_ms / 1000
                        change.progress_pct = min(95, int(100 * elapsed / expected_s))
                    else:
                        # No historical data, estimate 30s typical
                        change.progress_pct = min(95, int(100 * elapsed / 30))

            await asyncio.sleep(poll_interval_s)

        return False

    def _update_profile(self, event: PhaseChangeEvent) -> None:
        """Accumulate phase change timing for decision support.

        Args:
            event: Completed phase change event
        """
        profile = self._profiles[event.change_type]
        profile.update(event)

    async def _persist_profile(self, profile: PhaseChangeProfile) -> None:
        """Save phase change statistics to PostgreSQL.

        Args:
            profile: Profile to persist
        """
        if not self._db:
            return

        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO meta.phase_change_profiles
                        (change_type, sample_count, total_duration_ms,
                         min_duration_ms, max_duration_ms, failures, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, NOW())
                    ON CONFLICT (change_type) DO UPDATE SET
                        sample_count = EXCLUDED.sample_count,
                        total_duration_ms = EXCLUDED.total_duration_ms,
                        min_duration_ms = EXCLUDED.min_duration_ms,
                        max_duration_ms = EXCLUDED.max_duration_ms,
                        failures = EXCLUDED.failures,
                        updated_at = NOW()
                    """,
                    profile.change_type.value,
                    profile.sample_count,
                    profile.total_duration_ms,
                    profile.min_duration_ms,
                    profile.max_duration_ms,
                    profile.failures,
                )
        except Exception as e:
            logger.warning("Failed to persist phase change profile: %s", e)

    def get_profiles(self) -> dict[str, dict]:
        """Get all phase change profiles as dictionaries.

        Returns:
            Dict mapping change_type to profile dict
        """
        return {t.value: p.to_dict() for t, p in self._profiles.items()}

    def get_active_changes(self) -> list[dict]:
        """Get currently active phase changes.

        Returns:
            List of active change event dictionaries
        """
        return [e.to_dict() for e in self._active_changes.values()]
