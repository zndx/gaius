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

    # Healing sequence events
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

    # Recovery timer events (for incident lifecycle persistence)
    RECOVERY_TIMER_STARTED = "recovery_timer_started"
    RECOVERY_TIMER_CLEARED = "recovery_timer_cleared"

    # Preflight check events (gate for ambient cycles)
    PREFLIGHT_STARTED = "preflight_started"
    PREFLIGHT_COMPLETED = "preflight_completed"
    PREFLIGHT_BLOCKER = "preflight_blocker"  # Hard failure blocking ambient

    # Ambient compute cycle events
    AMBIENT_CYCLE_STARTED = "ambient_cycle_started"
    AMBIENT_PHASE_COMPLETED = "ambient_phase_completed"
    AMBIENT_CYCLE_COMPLETED = "ambient_cycle_completed"
    AMBIENT_CYCLE_FAILED = "ambient_cycle_failed"

    # RCA (Root Cause Analysis) events
    RCA_STARTED = "rca_started"
    RCA_COMPLETED = "rca_completed"
    RCA_CLASSIFICATION = "rca_classification"  # operational vs architectural
    RCA_CONSTRAINT_VIOLATION = "rca_constraint_violation"  # CP-SAT constraint mapped
    RCA_GITHUB_ISSUE_CREATED = "rca_github_issue_created"
    RCA_FAILED = "rca_failed"

    # ACP (Agent Client Protocol) escalation events
    ACP_ESCALATION_STARTED = "acp_escalation_started"
    ACP_ESCALATION_COMPLETED = "acp_escalation_completed"
    ACP_ESCALATION_FAILED = "acp_escalation_failed"


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

        # sequence_num derives ATOMICALLY from the DB. The old in-memory
        # counter reset to 1 on every engine restart and collided with rows
        # already recorded for the same sequence (duplicate-key errors under
        # restart-heavy operations, observed 2026-08-31) — silently dropping
        # healing telemetry.
        event = HealingEvent(
            event_type=event_type,
            endpoint=endpoint,
            tier=tier,
            sequence_id=sequence_id,
            sequence_num=0,  # assigned by the INSERT below
            payload=payload,
            aiops_event_id=aiops_event_id,
            failure_mode_id=failure_mode_id,
        )

        try:
            from asyncpg.exceptions import UniqueViolationError

            sequence_num = None
            for _attempt in range(3):
                try:
                    async with pool.acquire() as conn:
                        sequence_num = await conn.fetchval(
                            """
                            INSERT INTO healing_events (
                                event_id, sequence_id, sequence_num, event_type,
                                endpoint, tier, payload, aiops_event_id, failure_mode_id
                            )
                            SELECT $1, $2, COALESCE(MAX(sequence_num), 0) + 1,
                                   $3, $4, $5, $6, $7, $8
                            FROM healing_events WHERE sequence_id = $2
                            RETURNING sequence_num
                            """,
                            event.event_id,
                            sequence_id,
                            event_type.value,
                            endpoint,
                            tier,
                            json.dumps(payload),
                            aiops_event_id,
                            failure_mode_id,
                        )
                    break
                except UniqueViolationError:
                    continue  # concurrent writer took the number; recompute
            if sequence_num is None:
                raise RuntimeError(
                    f"could not allocate sequence_num for {sequence_id} after 3 attempts"
                )
            event.sequence_num = sequence_num
            self._sequence_counters[sequence_id] = sequence_num + 1

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

    # Recovery timer events (for incident lifecycle persistence)

    async def record_recovery_timer_started(
        self,
        sequence_id: UUID,
        endpoint: str,
        fingerprint: str,
        started_at: datetime,
    ) -> HealingEvent | None:
        """Record that a recovery timer has started.

        This event allows recovery timers to be persisted and restored
        after engine restart.

        Args:
            sequence_id: The healing sequence
            endpoint: Affected endpoint
            fingerprint: Incident fingerprint
            started_at: When the timer was started
        """
        return await self._record_event(
            event_type=HealingEventType.RECOVERY_TIMER_STARTED,
            endpoint=endpoint,
            tier=0,
            sequence_id=sequence_id,
            payload={
                "fingerprint": fingerprint,
                "started_at": started_at.isoformat(),
            },
        )

    async def record_recovery_timer_cleared(
        self,
        sequence_id: UUID,
        endpoint: str,
        fingerprint: str,
        reason: str = "recovery_failed",
    ) -> HealingEvent | None:
        """Record that a recovery timer has been cleared.

        Called when an incident regresses from recovering back to active,
        or when the incident is fully resolved.

        Args:
            sequence_id: The healing sequence
            endpoint: Affected endpoint
            fingerprint: Incident fingerprint
            reason: Why timer was cleared (recovery_failed, resolved)
        """
        return await self._record_event(
            event_type=HealingEventType.RECOVERY_TIMER_CLEARED,
            endpoint=endpoint,
            tier=0,
            sequence_id=sequence_id,
            payload={
                "fingerprint": fingerprint,
                "reason": reason,
            },
        )

    # RCA (Root Cause Analysis) event recording

    async def record_rca_started(
        self,
        sequence_id: UUID,
        endpoint: str,
        incident_fingerprint: str,
        failure_mode_id: str | None = None,
    ) -> HealingEvent | None:
        """Record start of RCA analysis phase.

        Args:
            sequence_id: The healing sequence
            endpoint: Affected endpoint
            incident_fingerprint: Unique incident identifier
            failure_mode_id: FMEA failure mode if mapped
        """
        return await self._record_event(
            event_type=HealingEventType.RCA_STARTED,
            endpoint=endpoint,
            tier=0,
            sequence_id=sequence_id,
            payload={
                "incident_fingerprint": incident_fingerprint,
            },
            failure_mode_id=failure_mode_id,
        )

    async def record_rca_completed(
        self,
        sequence_id: UUID,
        endpoint: str,
        classification: str,  # "operational" or "architectural"
        highest_order: int,  # 0-4 (symptom to design_principle)
        observations_count: int,
        constraint_violations_count: int,
        github_issue_needed: bool,
        duration_ms: int,
    ) -> HealingEvent | None:
        """Record completion of RCA analysis.

        Args:
            sequence_id: The healing sequence
            endpoint: Affected endpoint
            classification: operational or architectural
            highest_order: Highest abstraction level reached (0-4)
            observations_count: Number of observations recorded
            constraint_violations_count: Number of constraint violations found
            github_issue_needed: Whether code fix is required
            duration_ms: Time taken for RCA analysis
        """
        return await self._record_event(
            event_type=HealingEventType.RCA_COMPLETED,
            endpoint=endpoint,
            tier=0,
            sequence_id=sequence_id,
            payload={
                "classification": classification,
                "highest_order": highest_order,
                "observations_count": observations_count,
                "constraint_violations_count": constraint_violations_count,
                "github_issue_needed": github_issue_needed,
                "duration_ms": duration_ms,
            },
        )

    async def record_rca_classification(
        self,
        sequence_id: UUID,
        endpoint: str,
        classification: str,
        reasoning: str | None = None,
    ) -> HealingEvent | None:
        """Record RCA classification determination.

        Args:
            sequence_id: The healing sequence
            endpoint: Affected endpoint
            classification: operational or architectural
            reasoning: Why this classification was chosen
        """
        payload = {"classification": classification}
        if reasoning:
            payload["reasoning"] = reasoning

        return await self._record_event(
            event_type=HealingEventType.RCA_CLASSIFICATION,
            endpoint=endpoint,
            tier=0,
            sequence_id=sequence_id,
            payload=payload,
        )

    async def record_rca_constraint_violation(
        self,
        sequence_id: UUID,
        endpoint: str,
        constraint_id: str,
        constraint_name: str,
        location: str | None = None,
        evidence: str | None = None,
        failure_mode_id: str | None = None,
    ) -> HealingEvent | None:
        """Record a CP-SAT constraint violation found during RCA.

        Args:
            sequence_id: The healing sequence
            endpoint: Affected endpoint
            constraint_id: Constraint identifier (e.g., GPU_MUTUAL_EXCLUSION)
            constraint_name: Human-readable constraint name
            location: Code location where constraint is defined
            evidence: Evidence of the violation
            failure_mode_id: FMEA failure mode if mapped
        """
        payload = {
            "constraint_id": constraint_id,
            "constraint_name": constraint_name,
        }
        if location:
            payload["location"] = location
        if evidence:
            payload["evidence"] = evidence

        return await self._record_event(
            event_type=HealingEventType.RCA_CONSTRAINT_VIOLATION,
            endpoint=endpoint,
            tier=0,
            sequence_id=sequence_id,
            payload=payload,
            failure_mode_id=failure_mode_id,
        )

    async def record_rca_github_issue_created(
        self,
        sequence_id: UUID,
        endpoint: str,
        issue_number: int,
        issue_url: str,
        classification: str,
        fix_location: str | None = None,
    ) -> HealingEvent | None:
        """Record GitHub issue created for RCA findings.

        Args:
            sequence_id: The healing sequence
            endpoint: Affected endpoint
            issue_number: GitHub issue number
            issue_url: Full URL to the issue
            classification: RCA classification (should be architectural)
            fix_location: Proposed code location for fix
        """
        payload = {
            "issue_number": issue_number,
            "issue_url": issue_url,
            "classification": classification,
        }
        if fix_location:
            payload["fix_location"] = fix_location

        return await self._record_event(
            event_type=HealingEventType.RCA_GITHUB_ISSUE_CREATED,
            endpoint=endpoint,
            tier=0,
            sequence_id=sequence_id,
            payload=payload,
        )

    async def record_rca_failed(
        self,
        sequence_id: UUID,
        endpoint: str,
        error: str,
        stage: str = "analysis",  # analysis, parsing, github
    ) -> HealingEvent | None:
        """Record RCA analysis failure.

        Args:
            sequence_id: The healing sequence
            endpoint: Affected endpoint
            error: Error message
            stage: Which stage failed (analysis, parsing, github)
        """
        return await self._record_event(
            event_type=HealingEventType.RCA_FAILED,
            endpoint=endpoint,
            tier=0,
            sequence_id=sequence_id,
            payload={
                "error": error,
                "stage": stage,
            },
        )

    # ACP escalation event recording

    async def record_acp_escalation_started(
        self,
        sequence_id: UUID,
        endpoint: str,
        incident_fingerprint: str,
        rpn_score: int,
        failure_mode_id: str | None = None,
        prior_attempts: int = 0,
        prior_tiers: list[int] | None = None,
        escalation_reason: str | None = None,
        incident_age_seconds: int | None = None,
        prompt_sent: str | None = None,
        context_summary: str | None = None,
    ) -> HealingEvent | None:
        """Record start of ACP escalation.

        Args:
            sequence_id: The healing sequence
            endpoint: Affected endpoint
            incident_fingerprint: Unique incident identifier
            rpn_score: FMEA RPN score triggering escalation
            failure_mode_id: FMEA failure mode if mapped
            prior_attempts: Number of healing attempts before escalation
            prior_tiers: List of tiers attempted before escalation
            escalation_reason: Why escalation was triggered
            incident_age_seconds: How long the incident has been active
            prompt_sent: The prompt sent to the ACP agent (truncated)
            context_summary: Summary of health context sent
        """
        payload = {
            "incident_fingerprint": incident_fingerprint,
            "rpn_score": rpn_score,
            "prior_attempts": prior_attempts,
            "narrative": f"Escalating via ACP after {prior_attempts} failed attempts",
        }
        if prior_tiers:
            payload["prior_tiers"] = prior_tiers
        if escalation_reason:
            payload["escalation_reason"] = escalation_reason
        if incident_age_seconds is not None:
            payload["incident_age_seconds"] = incident_age_seconds
            payload["incident_age_human"] = self._format_duration(incident_age_seconds)
        if prompt_sent:
            payload["prompt_sent"] = prompt_sent[:2000]  # Truncate for DB
        if context_summary:
            payload["context_summary"] = context_summary[:1000]

        return await self._record_event(
            event_type=HealingEventType.ACP_ESCALATION_STARTED,
            endpoint=endpoint,
            tier=2,  # ACP is tier 2
            sequence_id=sequence_id,
            payload=payload,
            failure_mode_id=failure_mode_id,
        )

    def _format_duration(self, seconds: int) -> str:
        """Format duration in human-readable form."""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            return f"{seconds // 60}m {seconds % 60}s"
        else:
            hours = seconds // 3600
            mins = (seconds % 3600) // 60
            return f"{hours}h {mins}m"

    async def record_acp_escalation_completed(
        self,
        sequence_id: UUID,
        endpoint: str,
        session_id: str,
        result_summary: str | None = None,
        duration_ms: int | None = None,
        success: bool = True,
        actions_taken: list[str] | None = None,
        tools_used: list[str] | None = None,
        full_response: str | None = None,
        diagnosis: str | None = None,
        remediation_applied: str | None = None,
    ) -> HealingEvent | None:
        """Record successful ACP escalation completion.

        Args:
            sequence_id: The healing sequence
            endpoint: Affected endpoint
            session_id: ACP session identifier
            result_summary: Brief summary of the ACP agent's response
            duration_ms: Time taken for ACP interaction
            success: Whether the ACP agent determined remediation succeeded
            actions_taken: List of actions the ACP agent performed
            tools_used: List of MCP tools the ACP agent used
            full_response: Full response text (truncated)
            diagnosis: The ACP agent's diagnosis of the issue
            remediation_applied: What remediation was applied
        """
        # Build narrative
        duration_str = self._format_duration(duration_ms // 1000) if duration_ms else "unknown"
        narrative = f"ACP agent completed analysis in {duration_str}"
        if success:
            narrative += " - remediation successful"
        else:
            narrative += " - remediation failed or incomplete"

        payload = {
            "session_id": session_id,
            "success": success,
            "narrative": narrative,
        }
        if result_summary:
            payload["result_summary"] = result_summary[:500]
        if duration_ms:
            payload["duration_ms"] = duration_ms
            payload["duration_human"] = self._format_duration(duration_ms // 1000)
        if actions_taken:
            payload["actions_taken"] = actions_taken[:10]  # Limit to 10 actions
        if tools_used:
            payload["tools_used"] = tools_used[:20]  # Limit to 20 tools
        if full_response:
            payload["full_response"] = full_response[:5000]  # Store more context
        if diagnosis:
            payload["diagnosis"] = diagnosis[:1000]
        if remediation_applied:
            payload["remediation_applied"] = remediation_applied[:500]

        return await self._record_event(
            event_type=HealingEventType.ACP_ESCALATION_COMPLETED,
            endpoint=endpoint,
            tier=2,  # ACP is tier 2
            sequence_id=sequence_id,
            payload=payload,
        )

    async def record_acp_escalation_failed(
        self,
        sequence_id: UUID,
        endpoint: str,
        error: str,
        error_code: str | None = None,
        duration_ms: int | None = None,
        failure_stage: str | None = None,
        partial_response: str | None = None,
        connection_state: str | None = None,
        retry_recommended: bool = False,
        escalation_path: str | None = None,
    ) -> HealingEvent | None:
        """Record ACP escalation failure.

        Args:
            sequence_id: The healing sequence
            endpoint: Affected endpoint
            error: Error message
            error_code: Guru meditation code if applicable
            duration_ms: How long before failure occurred
            failure_stage: At what stage failure occurred (connection, prompt, timeout)
            partial_response: Any partial response received
            connection_state: State of ACP connection at failure
            retry_recommended: Whether retry is recommended
            escalation_path: Next escalation path (manual intervention, etc.)
        """
        # Build narrative
        narrative = f"ACP escalation failed: {error[:100]}"
        if failure_stage:
            narrative = f"ACP escalation failed at {failure_stage} stage: {error[:80]}"

        payload = {
            "error": error,
            "narrative": narrative,
        }
        if error_code:
            payload["error_code"] = error_code
        if duration_ms:
            payload["duration_ms"] = duration_ms
            payload["duration_human"] = self._format_duration(duration_ms // 1000)
        if failure_stage:
            payload["failure_stage"] = failure_stage
        if partial_response:
            payload["partial_response"] = partial_response[:1000]
        if connection_state:
            payload["connection_state"] = connection_state
        payload["retry_recommended"] = retry_recommended
        if escalation_path:
            payload["escalation_path"] = escalation_path
        else:
            payload["escalation_path"] = "Manual intervention required"

        return await self._record_event(
            event_type=HealingEventType.ACP_ESCALATION_FAILED,
            endpoint=endpoint,
            tier=2,  # ACP is tier 2
            sequence_id=sequence_id,
            payload=payload,
        )

    # Simple event recording (for preflight/ambient events)

    async def record_event(
        self,
        event_type: HealingEventType,
        payload: dict[str, Any],
        endpoint: str = "system",
    ) -> HealingEvent | None:
        """Record a simple event without full sequence tracking.

        Used for preflight and ambient cycle events that don't follow
        the healing sequence pattern.

        Args:
            event_type: Type of event
            payload: Event-specific data (should include sequence_id for linking)
            endpoint: Optional endpoint name (default: "system")

        Returns:
            HealingEvent if recorded, None if recording failed
        """
        pool = await self._get_pool()
        if not pool:
            logger.warning(f"Cannot record {event_type.value} event: no database pool")
            return None

        # Use sequence_id from payload if provided, otherwise generate one
        sequence_id_str = payload.get("sequence_id")
        if sequence_id_str:
            try:
                sequence_id = UUID(sequence_id_str) if isinstance(sequence_id_str, str) else sequence_id_str
            except (ValueError, TypeError):
                sequence_id = uuid4()
        else:
            sequence_id = uuid4()

        sequence_num = self._next_sequence_num(sequence_id)
        event = HealingEvent(
            event_type=event_type,
            endpoint=endpoint,
            tier=0,  # Not used for preflight/ambient
            sequence_id=sequence_id,
            sequence_num=sequence_num,
            payload=payload,
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
                    0,
                    json.dumps(payload),
                    None,
                    None,
                )

            logger.debug(f"Recorded event: {event_type.value} (sequence {sequence_id})")
            return event

        except Exception as e:
            logger.error(f"Failed to record event: {e}")
            return None

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
