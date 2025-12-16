"""State reconstruction from healing events.

Rebuilds HealingState objects from event history on startup.
Enables CLI healing to properly resume tier escalation.

Usage:
    from gaius.health.healing_state_store import HealingStateStore

    store = HealingStateStore(pool)
    states = await store.reconstruct_states()
    circuit_breaker = await store.load_circuit_breaker()
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID
import json
import logging

if TYPE_CHECKING:
    from asyncpg import Pool, Record

logger = logging.getLogger(__name__)


@dataclass
class ReconstructedHealingState:
    """Reconstructed healing state from event history.

    Mirrors the structure of HealingState in self_healing.py but
    is reconstructed from persisted events.
    """

    endpoint: str
    current_tier: int = 0
    attempts_at_tier: int = 0
    last_attempt: datetime | None = None
    cooldown_until: datetime | None = None
    sequence_id: UUID | None = None

    # Additional metadata from reconstruction
    total_attempts: int = 0
    started_at: datetime | None = None
    max_sequence_num: int = 0  # Track max sequence_num for event recorder sync


@dataclass
class CircuitBreakerState:
    """Global circuit breaker state."""

    global_failures: int = 0
    global_cooldown_until: datetime | None = None


class HealingStateStore:
    """Persists and reconstructs healing state from database."""

    def __init__(self, pool: "Pool | None" = None):
        """Initialize the state store.

        Args:
            pool: Database connection pool
        """
        self._pool = pool

    async def _get_pool(self) -> "Pool | None":
        """Get database pool."""
        if self._pool:
            return self._pool

        try:
            from ..storage.database import get_pool
            self._pool = await get_pool()
            return self._pool
        except Exception as e:
            logger.warning(f"Cannot get database pool: {e}")
            return None

    async def reconstruct_states(self) -> dict[str, ReconstructedHealingState]:
        """Reconstruct healing states for all active (incomplete) sequences.

        Finds sequences that started but never completed and replays
        their events to rebuild the current healing state.

        Returns:
            Dict mapping endpoint to reconstructed HealingState
        """
        pool = await self._get_pool()
        if not pool:
            logger.warning("Cannot reconstruct states: no database pool")
            return {}

        try:
            async with pool.acquire() as conn:
                # Find active sequences (started but not completed in last 24h)
                active_sequences = await conn.fetch(
                    """
                    WITH started AS (
                        SELECT sequence_id, endpoint, created_at
                        FROM healing_events
                        WHERE event_type = 'sequence_started'
                        AND created_at > NOW() - INTERVAL '24 hours'
                    ),
                    completed AS (
                        SELECT sequence_id
                        FROM healing_events
                        WHERE event_type = 'sequence_completed'
                    )
                    SELECT s.sequence_id, s.endpoint, s.created_at
                    FROM started s
                    LEFT JOIN completed c ON s.sequence_id = c.sequence_id
                    WHERE c.sequence_id IS NULL
                    """
                )

                if not active_sequences:
                    logger.debug("No active healing sequences to reconstruct")
                    return {}

                states: dict[str, ReconstructedHealingState] = {}

                for row in active_sequences:
                    endpoint = row["endpoint"]
                    sequence_id = row["sequence_id"]
                    started_at = row["created_at"]

                    # Get all events for this sequence in order
                    events = await conn.fetch(
                        """
                        SELECT event_type, tier, payload, created_at, sequence_num
                        FROM healing_events
                        WHERE sequence_id = $1
                        ORDER BY sequence_num
                        """,
                        sequence_id,
                    )

                    # Replay events to reconstruct state
                    state = ReconstructedHealingState(
                        endpoint=endpoint,
                        sequence_id=sequence_id,
                        started_at=started_at,
                    )

                    max_seq_num = 0
                    for event in events:
                        self._apply_event(state, event)
                        seq_num = event.get("sequence_num", 0)
                        if seq_num > max_seq_num:
                            max_seq_num = seq_num

                    state.max_sequence_num = max_seq_num

                    # Clear expired cooldowns
                    if state.cooldown_until and state.cooldown_until < datetime.now():
                        state.cooldown_until = None

                    states[endpoint] = state

                    logger.info(
                        f"Reconstructed healing state for {endpoint}: "
                        f"tier={state.current_tier}, attempts={state.attempts_at_tier}, "
                        f"cooldown={'yes' if state.cooldown_until else 'no'}"
                    )

                return states

        except Exception as e:
            logger.error(f"Failed to reconstruct healing states: {e}")
            return {}

    def _apply_event(self, state: ReconstructedHealingState, event: "Record") -> None:
        """Apply a single event to reconstruct state.

        Args:
            state: State being reconstructed
            event: Database row with event_type, tier, payload, created_at
        """
        event_type = event["event_type"]
        tier = event["tier"]
        payload = event["payload"] or {}
        timestamp = event["created_at"]

        # Handle JSON string from asyncpg (may not auto-decode JSONB)
        if isinstance(payload, str):
            import json
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}

        if event_type == "tier_entered":
            state.current_tier = tier
            state.attempts_at_tier = 0

        elif event_type == "attempt_started":
            # Track that an attempt is in progress
            pass

        elif event_type == "attempt_succeeded":
            state.attempts_at_tier = payload.get("attempt_num", state.attempts_at_tier)
            state.last_attempt = timestamp
            state.total_attempts += 1

        elif event_type == "attempt_failed":
            state.attempts_at_tier = payload.get("attempt_num", state.attempts_at_tier)
            state.last_attempt = timestamp
            state.total_attempts += 1

        elif event_type == "cooldown_started":
            cooldown_str = payload.get("cooldown_until")
            if cooldown_str:
                try:
                    # Handle ISO format with or without timezone
                    if cooldown_str.endswith("Z"):
                        cooldown_str = cooldown_str[:-1] + "+00:00"
                    state.cooldown_until = datetime.fromisoformat(cooldown_str)
                except ValueError:
                    logger.warning(f"Invalid cooldown_until format: {cooldown_str}")

        elif event_type == "cooldown_cleared":
            state.cooldown_until = None

        elif event_type == "tier_exhausted":
            # State will be updated by subsequent tier_entered event
            pass

    async def load_circuit_breaker(self) -> CircuitBreakerState:
        """Load global circuit breaker state from health_loop_state.

        Returns:
            CircuitBreakerState with global_failures and cooldown
        """
        pool = await self._get_pool()
        if not pool:
            return CircuitBreakerState()

        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT circuit_breaker
                    FROM health_loop_state
                    WHERE id = 1
                    """
                )

                if not row or not row["circuit_breaker"]:
                    return CircuitBreakerState()

                cb = row["circuit_breaker"]

                # Handle both dict and JSON string (asyncpg may return string)
                if isinstance(cb, str):
                    cb = json.loads(cb)

                # Parse cooldown datetime
                cooldown_until = None
                cooldown_str = cb.get("global_cooldown_until")
                if cooldown_str:
                    try:
                        if cooldown_str.endswith("Z"):
                            cooldown_str = cooldown_str[:-1] + "+00:00"
                        cooldown_until = datetime.fromisoformat(cooldown_str)

                        # Clear if expired
                        if cooldown_until < datetime.now():
                            cooldown_until = None
                    except ValueError:
                        pass

                return CircuitBreakerState(
                    global_failures=cb.get("global_failures", 0),
                    global_cooldown_until=cooldown_until,
                )

        except Exception as e:
            logger.error(f"Failed to load circuit breaker: {e}")
            return CircuitBreakerState()

    async def save_circuit_breaker(self, state: CircuitBreakerState) -> bool:
        """Save global circuit breaker state to health_loop_state.

        Args:
            state: Circuit breaker state to save

        Returns:
            True if saved successfully
        """
        pool = await self._get_pool()
        if not pool:
            return False

        try:
            cb_data = {
                "global_failures": state.global_failures,
                "global_cooldown_until": (
                    state.global_cooldown_until.isoformat()
                    if state.global_cooldown_until
                    else None
                ),
            }

            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE health_loop_state
                    SET circuit_breaker = $1::jsonb,
                        updated_at = NOW()
                    WHERE id = 1
                    """,
                    json.dumps(cb_data),
                )

            logger.debug(
                f"Saved circuit breaker: failures={state.global_failures}, "
                f"cooldown={'yes' if state.global_cooldown_until else 'no'}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to save circuit breaker: {e}")
            return False

    async def clear_endpoint_state(self, endpoint: str) -> bool:
        """Mark endpoint sequences as completed after successful healing.

        Note: This doesn't delete events (they're immutable for audit).
        Instead, we just log that future reconstructions should ignore
        completed sequences.

        Args:
            endpoint: Endpoint that was successfully healed

        Returns:
            True if any cleanup was done
        """
        # Events are immutable, so we don't delete them.
        # The complete_sequence() call in HealingEventRecorder handles marking
        # sequences as completed, which reconstruct_states() filters out.
        logger.debug(f"State cleared for {endpoint} (no event deletion needed)")
        return True

    async def get_healing_stats(self, hours: int = 24) -> dict[str, Any]:
        """Get healing statistics for monitoring.

        Args:
            hours: How far back to look

        Returns:
            Statistics dict with counts and success rates
        """
        pool = await self._get_pool()
        if not pool:
            return {"error": "no database pool"}

        try:
            async with pool.acquire() as conn:
                # Get attempt counts by tier
                tier_stats = await conn.fetch(
                    """
                    SELECT
                        tier,
                        COUNT(*) FILTER (WHERE event_type = 'attempt_succeeded') as successes,
                        COUNT(*) FILTER (WHERE event_type = 'attempt_failed') as failures
                    FROM healing_events
                    WHERE event_type IN ('attempt_succeeded', 'attempt_failed')
                    AND created_at > NOW() - INTERVAL '1 hour' * $1
                    GROUP BY tier
                    ORDER BY tier
                    """,
                    hours,
                )

                # Get sequence outcomes
                outcomes = await conn.fetch(
                    """
                    SELECT
                        payload->>'outcome' as outcome,
                        COUNT(*) as count
                    FROM healing_events
                    WHERE event_type = 'sequence_completed'
                    AND created_at > NOW() - INTERVAL '1 hour' * $1
                    GROUP BY payload->>'outcome'
                    """,
                    hours,
                )

                # Get active sequences count
                active = await conn.fetchval(
                    """
                    WITH started AS (
                        SELECT sequence_id
                        FROM healing_events
                        WHERE event_type = 'sequence_started'
                        AND created_at > NOW() - INTERVAL '24 hours'
                    ),
                    completed AS (
                        SELECT sequence_id
                        FROM healing_events
                        WHERE event_type = 'sequence_completed'
                    )
                    SELECT COUNT(*)
                    FROM started s
                    LEFT JOIN completed c ON s.sequence_id = c.sequence_id
                    WHERE c.sequence_id IS NULL
                    """
                )

                return {
                    "period_hours": hours,
                    "tier_stats": [
                        {
                            "tier": row["tier"],
                            "successes": row["successes"],
                            "failures": row["failures"],
                            "success_rate": (
                                round(row["successes"] / (row["successes"] + row["failures"]) * 100, 1)
                                if (row["successes"] + row["failures"]) > 0
                                else None
                            ),
                        }
                        for row in tier_stats
                    ],
                    "outcomes": {
                        row["outcome"]: row["count"]
                        for row in outcomes
                    },
                    "active_sequences": active or 0,
                }

        except Exception as e:
            logger.error(f"Failed to get healing stats: {e}")
            return {"error": str(e)}
