"""Event-sourced healing event recorder.

Records healing attempts as immutable events to the healing_events table.
Enables state reconstruction from event history for CLI persistence.

Usage:
    recorder = HealingEventRecorder(pool)

    # Start a new healing sequence
    sequence_id = await recorder.start_sequence(endpoint, issue, rpn_score)

    # Record events during healing
    await recorder.record_tier_entered(sequence_id, endpoint, from_tier=None, to_tier=0)
    await recorder.record_attempt_started(sequence_id, endpoint, tier=0, attempt_num=1, action="SOFT_RESET")
    await recorder.record_attempt_failed(sequence_id, endpoint, tier=0, attempt_num=1, action="SOFT_RESET", duration_ms=5000, reason="still unhealthy")
    await recorder.record_cooldown_started(sequence_id, endpoint, tier=0, cooldown_until=..., cooldown_seconds=60)

    # Complete the sequence
    await recorder.complete_sequence(sequence_id, outcome="success", total_attempts=2, final_tier=0)
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4
import json
import logging

if TYPE_CHECKING:
    from asyncpg import Pool

logger = logging.getLogger(__name__)


class HealingEventType(str, Enum):
    """Event types for healing audit trail."""

    SEQUENCE_STARTED = "sequence_started"
    SEQUENCE_COMPLETED = "sequence_completed"
    TIER_ENTERED = "tier_entered"
    TIER_EXHAUSTED = "tier_exhausted"
    ATTEMPT_STARTED = "attempt_started"
    ATTEMPT_SUCCEEDED = "attempt_succeeded"
    ATTEMPT_FAILED = "attempt_failed"
    COOLDOWN_STARTED = "cooldown_started"
    COOLDOWN_CLEARED = "cooldown_cleared"
    CIRCUIT_BREAKER_TRIPPED = "circuit_breaker_tripped"
    CIRCUIT_BREAKER_RESET = "circuit_breaker_reset"


@dataclass
class HealingEvent:
    """Represents a single healing event."""

    event_type: HealingEventType
    endpoint: str
    tier: int
    sequence_id: UUID
    sequence_num: int
    payload: dict[str, Any] = field(default_factory=dict)
    aiops_event_id: int | None = None
    failure_mode_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    event_id: UUID = field(default_factory=uuid4)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "endpoint": self.endpoint,
            "tier": self.tier,
            "sequence_id": str(self.sequence_id),
            "sequence_num": self.sequence_num,
            "payload": self.payload,
            "aiops_event_id": self.aiops_event_id,
            "failure_mode_id": self.failure_mode_id,
            "created_at": self.created_at.isoformat(),
        }


class HealingEventRecorder:
    """Records healing events to database for audit trail.

    Thread-safe event recording with automatic sequence number management.
    """

    def __init__(self, pool: "Pool | None" = None):
        """Initialize the event recorder.

        Args:
            pool: Database connection pool. If None, will attempt to get from storage.
        """
        self._pool = pool
        self._sequence_counters: dict[UUID, int] = {}  # sequence_id -> next_num

    async def _get_pool(self) -> "Pool | None":
        """Get database pool, creating if needed."""
        if self._pool:
            return self._pool

        try:
            from ..storage.database import get_pool
            self._pool = await get_pool()
            return self._pool
        except Exception as e:
            logger.warning(f"Cannot get database pool: {e}")
            return None

    def _next_sequence_num(self, sequence_id: UUID) -> int:
        """Get next sequence number for a sequence."""
        num = self._sequence_counters.get(sequence_id, 1)
        self._sequence_counters[sequence_id] = num + 1
        return num

    async def _record_event(
        self,
        event_type: HealingEventType,
        endpoint: str,
        tier: int,
        sequence_id: UUID,
        payload: dict[str, Any],
        aiops_event_id: int | None = None,
        failure_mode_id: str | None = None,
    ) -> HealingEvent | None:
        """Record a healing event to the database.

        Args:
            event_type: Type of event
            endpoint: Affected endpoint
            tier: Current healing tier (0, 1, or 2)
            sequence_id: UUID grouping events for one healing sequence
            payload: Event-specific data
            aiops_event_id: Link to aiops_events table
            failure_mode_id: Link to fmea_catalog

        Returns:
            HealingEvent if recorded, None if recording failed
        """
        pool = await self._get_pool()
        if not pool:
            logger.warning(f"Cannot record {event_type.value} event: no database pool")
            return None

        sequence_num = self._next_sequence_num(sequence_id)
        event = HealingEvent(
            event_type=event_type,
            endpoint=endpoint,
            tier=tier,
            sequence_id=sequence_id,
            sequence_num=sequence_num,
            payload=payload,
            aiops_event_id=aiops_event_id,
            failure_mode_id=failure_mode_id,
        )

        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO healing_events (
                        event_id, sequence_id, sequence_num, event_type,
                        endpoint, tier, payload, aiops_event_id, failure_mode_id
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    event.event_id,
                    sequence_id,
                    sequence_num,
                    event_type.value,
                    endpoint,
                    tier,
                    json.dumps(payload),
                    aiops_event_id,
                    failure_mode_id,
                )

            logger.debug(
                f"Recorded healing event: {event_type.value} for {endpoint} "
                f"(sequence {sequence_id}, num {sequence_num})"
            )
            return event

        except Exception as e:
            logger.error(f"Failed to record healing event: {e}")
            return None

    # Convenience methods for specific event types

    async def start_sequence(
        self,
        endpoint: str,
        issue_type: str,
        check_name: str | None = None,
        severity: str = "warning",
        rpn_score: int | None = None,
        context: dict[str, Any] | None = None,
        aiops_event_id: int | None = None,
        failure_mode_id: str | None = None,
    ) -> UUID:
        """Start a new healing sequence.

        Args:
            endpoint: Affected endpoint
            issue_type: Type of issue (e.g., "unhealthy", "stuck_starting")
            check_name: Name of health check that detected issue
            severity: Issue severity (critical, warning, info)
            rpn_score: FMEA RPN score if available
            context: Additional context about the issue
            aiops_event_id: Link to aiops_events table
            failure_mode_id: Link to fmea_catalog

        Returns:
            UUID for the new sequence
        """
        sequence_id = uuid4()
        self._sequence_counters[sequence_id] = 1

        payload = {
            "issue_type": issue_type,
            "check_name": check_name,
            "severity": severity,
        }
        if rpn_score is not None:
            payload["rpn_score"] = rpn_score
        if context:
            payload["initial_context"] = context

        await self._record_event(
            event_type=HealingEventType.SEQUENCE_STARTED,
            endpoint=endpoint,
            tier=0,  # Always start at tier 0
            sequence_id=sequence_id,
            payload=payload,
            aiops_event_id=aiops_event_id,
            failure_mode_id=failure_mode_id,
        )

        logger.info(f"Started healing sequence {sequence_id} for {endpoint}: {issue_type}")
        return sequence_id

    async def complete_sequence(
        self,
        sequence_id: UUID,
        endpoint: str,
        outcome: str,
        total_attempts: int,
        final_tier: int,
        total_duration_ms: int | None = None,
    ) -> HealingEvent | None:
        """Complete a healing sequence.

        Args:
            sequence_id: The sequence to complete
            endpoint: Affected endpoint
            outcome: "success", "exhausted", or "manual_required"
            total_attempts: Total healing attempts made
            final_tier: Tier at completion
            total_duration_ms: Total time from start to completion

        Returns:
            HealingEvent if recorded
        """
        payload = {
            "outcome": outcome,
            "total_attempts": total_attempts,
            "final_tier": final_tier,
        }
        if total_duration_ms is not None:
            payload["total_duration_ms"] = total_duration_ms

        event = await self._record_event(
            event_type=HealingEventType.SEQUENCE_COMPLETED,
            endpoint=endpoint,
            tier=final_tier,
            sequence_id=sequence_id,
            payload=payload,
        )

        # Clean up sequence counter
        self._sequence_counters.pop(sequence_id, None)

        logger.info(
            f"Completed healing sequence {sequence_id} for {endpoint}: "
            f"{outcome} after {total_attempts} attempts at tier {final_tier}"
        )
        return event

    async def record_tier_entered(
        self,
        sequence_id: UUID,
        endpoint: str,
        to_tier: int,
        from_tier: int | None = None,
        reason: str = "initial",
    ) -> HealingEvent | None:
        """Record entering a tier.

        Args:
            sequence_id: The sequence
            endpoint: Affected endpoint
            to_tier: Tier being entered
            from_tier: Previous tier (None if initial)
            reason: Why entering this tier (initial, escalation, fmea_directed)
        """
        return await self._record_event(
            event_type=HealingEventType.TIER_ENTERED,
            endpoint=endpoint,
            tier=to_tier,
            sequence_id=sequence_id,
            payload={
                "from_tier": from_tier,
                "to_tier": to_tier,
                "reason": reason,
            },
        )

    async def record_tier_exhausted(
        self,
        sequence_id: UUID,
        endpoint: str,
        tier: int,
        attempts_made: int,
        max_attempts: int,
        reason: str | None = None,
    ) -> HealingEvent | None:
        """Record that a tier has been exhausted."""
        return await self._record_event(
            event_type=HealingEventType.TIER_EXHAUSTED,
            endpoint=endpoint,
            tier=tier,
            sequence_id=sequence_id,
            payload={
                "attempts_made": attempts_made,
                "max_attempts": max_attempts,
                "reason": reason or f"Max attempts ({max_attempts}) reached at tier {tier}",
            },
        )

    async def record_attempt_started(
        self,
        sequence_id: UUID,
        endpoint: str,
        tier: int,
        attempt_num: int,
        action: str,
    ) -> HealingEvent | None:
        """Record starting a healing attempt."""
        return await self._record_event(
            event_type=HealingEventType.ATTEMPT_STARTED,
            endpoint=endpoint,
            tier=tier,
            sequence_id=sequence_id,
            payload={
                "attempt_num": attempt_num,
                "action": action,
            },
        )

    async def record_attempt_succeeded(
        self,
        sequence_id: UUID,
        endpoint: str,
        tier: int,
        attempt_num: int,
        action: str,
        duration_ms: int,
        reason: str | None = None,
    ) -> HealingEvent | None:
        """Record a successful healing attempt."""
        payload = {
            "attempt_num": attempt_num,
            "action": action,
            "duration_ms": duration_ms,
        }
        if reason:
            payload["reason"] = reason

        return await self._record_event(
            event_type=HealingEventType.ATTEMPT_SUCCEEDED,
            endpoint=endpoint,
            tier=tier,
            sequence_id=sequence_id,
            payload=payload,
        )

    async def record_attempt_failed(
        self,
        sequence_id: UUID,
        endpoint: str,
        tier: int,
        attempt_num: int,
        action: str,
        duration_ms: int,
        reason: str | None = None,
        agent_reasoning: str | None = None,
        remote_assessment: str | None = None,
    ) -> HealingEvent | None:
        """Record a failed healing attempt."""
        payload = {
            "attempt_num": attempt_num,
            "action": action,
            "duration_ms": duration_ms,
        }
        if reason:
            payload["reason"] = reason
        if agent_reasoning:
            payload["agent_reasoning"] = agent_reasoning
        if remote_assessment:
            payload["remote_assessment"] = remote_assessment

        return await self._record_event(
            event_type=HealingEventType.ATTEMPT_FAILED,
            endpoint=endpoint,
            tier=tier,
            sequence_id=sequence_id,
            payload=payload,
        )

    async def record_cooldown_started(
        self,
        sequence_id: UUID,
        endpoint: str,
        tier: int,
        cooldown_until: datetime,
        cooldown_seconds: int,
        reason: str | None = None,
    ) -> HealingEvent | None:
        """Record entering a cooldown period."""
        payload = {
            "cooldown_until": cooldown_until.isoformat(),
            "cooldown_seconds": cooldown_seconds,
        }
        if reason:
            payload["reason"] = reason

        return await self._record_event(
            event_type=HealingEventType.COOLDOWN_STARTED,
            endpoint=endpoint,
            tier=tier,
            sequence_id=sequence_id,
            payload=payload,
        )

    async def record_cooldown_cleared(
        self,
        sequence_id: UUID,
        endpoint: str,
        tier: int,
    ) -> HealingEvent | None:
        """Record cooldown expiration."""
        return await self._record_event(
            event_type=HealingEventType.COOLDOWN_CLEARED,
            endpoint=endpoint,
            tier=tier,
            sequence_id=sequence_id,
            payload={},
        )

    async def record_circuit_breaker_tripped(
        self,
        sequence_id: UUID,
        endpoint: str,
        failure_count: int,
        threshold: int,
        cooldown_until: datetime,
    ) -> HealingEvent | None:
        """Record global circuit breaker activation."""
        return await self._record_event(
            event_type=HealingEventType.CIRCUIT_BREAKER_TRIPPED,
            endpoint=endpoint,
            tier=-1,  # Circuit breaker is global, not tier-specific
            sequence_id=sequence_id,
            payload={
                "failure_count": failure_count,
                "threshold": threshold,
                "cooldown_until": cooldown_until.isoformat(),
            },
        )

    async def record_circuit_breaker_reset(
        self,
        sequence_id: UUID,
        endpoint: str,
    ) -> HealingEvent | None:
        """Record circuit breaker reset."""
        return await self._record_event(
            event_type=HealingEventType.CIRCUIT_BREAKER_RESET,
            endpoint=endpoint,
            tier=-1,
            sequence_id=sequence_id,
            payload={},
        )

    # Query methods

    async def get_sequence_events(self, sequence_id: UUID) -> list[dict[str, Any]]:
        """Get all events for a sequence in order.

        Args:
            sequence_id: The sequence to query

        Returns:
            List of event dicts ordered by sequence_num
        """
        pool = await self._get_pool()
        if not pool:
            return []

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT event_id, event_type, endpoint, tier, sequence_num,
                           payload, created_at, aiops_event_id, failure_mode_id
                    FROM healing_events
                    WHERE sequence_id = $1
                    ORDER BY sequence_num
                    """,
                    sequence_id,
                )

                return [
                    {
                        "event_id": str(row["event_id"]),
                        "event_type": row["event_type"],
                        "endpoint": row["endpoint"],
                        "tier": row["tier"],
                        "sequence_num": row["sequence_num"],
                        "payload": row["payload"],
                        "created_at": row["created_at"].isoformat(),
                        "aiops_event_id": row["aiops_event_id"],
                        "failure_mode_id": row["failure_mode_id"],
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Failed to get sequence events: {e}")
            return []

    async def get_recent_events(
        self,
        endpoint: str | None = None,
        limit: int = 50,
        hours: int = 24,
    ) -> list[dict[str, Any]]:
        """Get recent healing events.

        Args:
            endpoint: Filter by endpoint (None for all)
            limit: Maximum events to return
            hours: How far back to look

        Returns:
            List of event dicts ordered by created_at DESC
        """
        pool = await self._get_pool()
        if not pool:
            return []

        try:
            async with pool.acquire() as conn:
                if endpoint:
                    rows = await conn.fetch(
                        """
                        SELECT event_id, event_type, endpoint, tier, sequence_id,
                               sequence_num, payload, created_at
                        FROM healing_events
                        WHERE endpoint = $1
                        AND created_at > NOW() - INTERVAL '1 hour' * $2
                        ORDER BY created_at DESC
                        LIMIT $3
                        """,
                        endpoint,
                        hours,
                        limit,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT event_id, event_type, endpoint, tier, sequence_id,
                               sequence_num, payload, created_at
                        FROM healing_events
                        WHERE created_at > NOW() - INTERVAL '1 hour' * $1
                        ORDER BY created_at DESC
                        LIMIT $2
                        """,
                        hours,
                        limit,
                    )

                return [
                    {
                        "event_id": str(row["event_id"]),
                        "event_type": row["event_type"],
                        "endpoint": row["endpoint"],
                        "tier": row["tier"],
                        "sequence_id": str(row["sequence_id"]),
                        "sequence_num": row["sequence_num"],
                        "payload": row["payload"],
                        "created_at": row["created_at"].isoformat(),
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Failed to get recent events: {e}")
            return []

    async def get_active_sequences(self) -> list[dict[str, Any]]:
        """Get sequences that started but haven't completed.

        Returns:
            List of active sequence info dicts
        """
        pool = await self._get_pool()
        if not pool:
            return []

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    WITH started AS (
                        SELECT sequence_id, endpoint, created_at, payload
                        FROM healing_events
                        WHERE event_type = 'sequence_started'
                        AND created_at > NOW() - INTERVAL '24 hours'
                    ),
                    completed AS (
                        SELECT sequence_id
                        FROM healing_events
                        WHERE event_type = 'sequence_completed'
                    )
                    SELECT s.sequence_id, s.endpoint, s.created_at, s.payload
                    FROM started s
                    LEFT JOIN completed c ON s.sequence_id = c.sequence_id
                    WHERE c.sequence_id IS NULL
                    ORDER BY s.created_at DESC
                    """,
                )

                return [
                    {
                        "sequence_id": str(row["sequence_id"]),
                        "endpoint": row["endpoint"],
                        "created_at": row["created_at"].isoformat(),
                        "payload": row["payload"],
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Failed to get active sequences: {e}")
            return []
