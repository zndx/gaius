"""Routing analytics for capability-based inference decisions.

Tracks routing decisions to detect when agents are "starved" of optimal
model selections due to GPU constraints forcing fallback models.

Usage:
    from gaius.inference.routing_analytics import (
        RoutingDecision,
        RoutingOutcome,
        get_routing_collector,
    )

    # After making a routing decision
    decision = RoutingDecision(
        agent_alias="leader",
        requested_capabilities=["reasoning"],
        preferred_model="Qwen/QwQ-32B",
        actual_endpoint="coding",
        actual_model="Qwen/Qwen2.5-Coder-32B-Instruct",
        outcome=RoutingOutcome.CAPABILITY_FALLBACK,
        mismatched_capabilities=["reasoning"],
        success=True,
        latency_ms=150,
    )

    collector = get_routing_collector()
    await collector.record(decision)
"""

import asyncio
import logging
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# Lazy import to avoid hard dependency
_asyncpg = None


def _get_asyncpg():
    """Lazy import asyncpg."""
    global _asyncpg
    if _asyncpg is None:
        import asyncpg

        _asyncpg = asyncpg
    return _asyncpg


def get_database_url() -> str:
    """Get database URL from environment."""
    return os.getenv(
        "DATABASE_URL", "postgresql://gaius:gaius@localhost:5432/gaius"
    )


class RoutingOutcome(Enum):
    """Outcome of a routing decision."""

    OPTIMAL = "optimal"  # Got the preferred model
    CAPABILITY_MATCH = "capability_match"  # Got a model matching capabilities
    CAPABILITY_FALLBACK = "capability_fallback"  # Fell back due to capability mismatch
    DEFAULT_FALLBACK = "default_fallback"  # Fell back to default endpoint


@dataclass
class RoutingDecision:
    """A single routing decision record.

    Attributes:
        agent_alias: Agent identifier (e.g., "leader", "critic")
        requested_capabilities: Capabilities the agent requested
        preferred_model: Model the agent preferred (if any)
        actual_endpoint: Endpoint that was actually used
        actual_model: Model that was actually used
        outcome: Type of routing outcome
        mismatched_capabilities: Capabilities that couldn't be satisfied
        success: Whether the inference succeeded
        latency_ms: Response latency in milliseconds
        agent_role: Optional role category (e.g., "AgentRole.LEADER")
        workflow_phase: Optional workflow phase (e.g., "synthesis")
        fallback_reason: Optional explanation for fallback
    """

    agent_alias: str
    requested_capabilities: list[str]
    preferred_model: str | None
    actual_endpoint: str
    actual_model: str
    outcome: RoutingOutcome
    mismatched_capabilities: list[str]
    success: bool
    latency_ms: int
    agent_role: str | None = None
    workflow_phase: str | None = None
    fallback_reason: str | None = None
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def capability_mismatch(self) -> bool:
        """Whether there was a capability mismatch."""
        return self.outcome in (
            RoutingOutcome.CAPABILITY_FALLBACK,
            RoutingOutcome.DEFAULT_FALLBACK,
        )

    @property
    def fallback_used(self) -> bool:
        """Whether a fallback was used."""
        return self.outcome != RoutingOutcome.OPTIMAL

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "agent_alias": self.agent_alias,
            "agent_role": self.agent_role,
            "workflow_phase": self.workflow_phase,
            "requested_capabilities": self.requested_capabilities,
            "preferred_model": self.preferred_model,
            "actual_endpoint": self.actual_endpoint,
            "actual_model": self.actual_model,
            "outcome": self.outcome.value,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "capability_mismatch": self.capability_mismatch,
            "mismatched_capabilities": self.mismatched_capabilities,
            "success": self.success,
            "latency_ms": self.latency_ms,
            "created_at": self.created_at.isoformat(),
        }


class RoutingAnalyticsCollector:
    """Buffered collector for routing decisions.

    Batches writes to PostgreSQL for efficiency.
    Flushes every 30 seconds or when buffer reaches 100 records.
    """

    BUFFER_SIZE = 100
    FLUSH_INTERVAL = 30.0  # seconds

    def __init__(self):
        self._buffer: deque[RoutingDecision] = deque(maxlen=self.BUFFER_SIZE)
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
        self._running = False
        self._last_flush = datetime.now()

    async def start(self) -> None:
        """Start the background flush task."""
        if self._running:
            return

        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("RoutingAnalyticsCollector started")

    async def stop(self) -> None:
        """Stop the collector and flush remaining records."""
        if not self._running:
            return

        self._running = False

        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Final flush
        await self._flush()
        logger.info("RoutingAnalyticsCollector stopped")

    async def record(self, decision: RoutingDecision) -> None:
        """Record a routing decision.

        Args:
            decision: The routing decision to record
        """
        async with self._lock:
            self._buffer.append(decision)

            # Flush if buffer is full
            if len(self._buffer) >= self.BUFFER_SIZE:
                await self._flush()

    async def _flush_loop(self) -> None:
        """Background loop to flush buffer periodically."""
        while self._running:
            await asyncio.sleep(self.FLUSH_INTERVAL)
            if self._buffer:
                await self._flush()

    async def _flush(self) -> None:
        """Flush buffered records to PostgreSQL."""
        if not self._buffer:
            return

        async with self._lock:
            records = list(self._buffer)
            self._buffer.clear()

        if not records:
            return

        try:
            asyncpg = _get_asyncpg()
            url = get_database_url()
            conn = await asyncpg.connect(url)

            try:
                # Batch insert
                await conn.executemany(
                    """
                    INSERT INTO routing_decisions (
                        created_at,
                        agent_role,
                        agent_alias,
                        workflow_phase,
                        requested_capabilities,
                        preferred_model,
                        actual_endpoint,
                        actual_model,
                        fallback_used,
                        fallback_reason,
                        capability_mismatch,
                        mismatched_capabilities,
                        success,
                        latency_ms
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14
                    )
                    """,
                    [
                        (
                            r.created_at,
                            r.agent_role,
                            r.agent_alias,
                            r.workflow_phase,
                            r.requested_capabilities,
                            r.preferred_model,
                            r.actual_endpoint,
                            r.actual_model,
                            r.fallback_used,
                            r.fallback_reason,
                            r.capability_mismatch,
                            r.mismatched_capabilities,
                            r.success,
                            r.latency_ms,
                        )
                        for r in records
                    ],
                )
                logger.debug(f"Flushed {len(records)} routing decisions to DB")
                self._last_flush = datetime.now()

            finally:
                await conn.close()

        except Exception as e:
            logger.error(f"Failed to flush routing decisions: {e}")
            # Re-add records to buffer on failure (best effort)
            async with self._lock:
                for r in records:
                    if len(self._buffer) < self.BUFFER_SIZE:
                        self._buffer.appendleft(r)

    def get_stats(self) -> dict[str, Any]:
        """Get collector statistics."""
        return {
            "running": self._running,
            "buffer_size": len(self._buffer),
            "buffer_capacity": self.BUFFER_SIZE,
            "flush_interval_s": self.FLUSH_INTERVAL,
            "last_flush": self._last_flush.isoformat(),
        }


# Module-level singleton
_collector: RoutingAnalyticsCollector | None = None


def get_routing_collector() -> RoutingAnalyticsCollector:
    """Get or create the routing analytics collector singleton."""
    global _collector
    if _collector is None:
        _collector = RoutingAnalyticsCollector()
    return _collector


async def record_routing_decision(
    agent_alias: str,
    requested_capabilities: list[str],
    preferred_model: str | None,
    actual_endpoint: str,
    actual_model: str,
    outcome: RoutingOutcome,
    mismatched_capabilities: list[str] | None = None,
    success: bool = True,
    latency_ms: int = 0,
    agent_role: str | None = None,
    workflow_phase: str | None = None,
    fallback_reason: str | None = None,
) -> None:
    """Convenience function to record a routing decision.

    Args:
        agent_alias: Agent identifier
        requested_capabilities: Capabilities requested
        preferred_model: Model preferred by agent
        actual_endpoint: Endpoint actually used
        actual_model: Model actually used
        outcome: Routing outcome type
        mismatched_capabilities: Capabilities that couldn't be satisfied
        success: Whether inference succeeded
        latency_ms: Response latency
        agent_role: Optional role category
        workflow_phase: Optional workflow phase
        fallback_reason: Optional explanation for fallback
    """
    decision = RoutingDecision(
        agent_alias=agent_alias,
        requested_capabilities=requested_capabilities,
        preferred_model=preferred_model,
        actual_endpoint=actual_endpoint,
        actual_model=actual_model,
        outcome=outcome,
        mismatched_capabilities=mismatched_capabilities or [],
        success=success,
        latency_ms=latency_ms,
        agent_role=agent_role,
        workflow_phase=workflow_phase,
        fallback_reason=fallback_reason,
    )

    collector = get_routing_collector()
    await collector.record(decision)
