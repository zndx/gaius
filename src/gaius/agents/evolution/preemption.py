"""Preemption support for evolution daemon.

Allows background evolution work to be preempted when
high-priority interactive requests arrive.

The PreemptionManager hooks into the scheduler's job events
and raises PreemptedError when evolution should yield.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class PreemptedError(Exception):
    """Raised when evolution is preempted by interactive request.

    This is a control flow exception, not an error condition.
    The daemon should catch this and gracefully abort the current cycle.
    """

    def __init__(self, reason: str = "Preempted by high-priority job"):
        self.reason = reason
        super().__init__(reason)


class JobPriority(Enum):
    """Job priority levels (matching scheduler)."""

    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


@dataclass
class PreemptionEvent:
    """Event data for preemption."""

    timestamp: datetime
    job_id: str
    priority: JobPriority
    reason: str


class PreemptionManager:
    """Manages preemption of low-priority background work.

    Monitors for high-priority job submissions and signals
    preemption to running evolution cycles.

    Usage:
        manager = PreemptionManager()

        # In evolution daemon:
        try:
            result = await manager.run_with_preemption(
                long_running_optimization()
            )
        except PreemptedError:
            # Gracefully abort and yield to interactive request
            pass
    """

    # Priority threshold - jobs at or below this priority trigger preemption
    PREEMPTION_THRESHOLD = JobPriority.HIGH

    def __init__(self):
        """Initialize preemption manager."""
        self._preempt_event = asyncio.Event()
        self._last_preemption: PreemptionEvent | None = None
        self._callbacks: list[Callable[[PreemptionEvent], Awaitable[None]]] = []
        self._active = False

    def activate(self) -> None:
        """Activate preemption monitoring."""
        self._active = True
        self._preempt_event.clear()
        logger.debug("Preemption manager activated")

    def deactivate(self) -> None:
        """Deactivate preemption monitoring."""
        self._active = False
        logger.debug("Preemption manager deactivated")

    def signal_preemption(
        self,
        job_id: str,
        priority: JobPriority,
        reason: str = "",
    ) -> None:
        """Signal that preemption is needed.

        Called by scheduler when high-priority job arrives.

        Args:
            job_id: ID of preempting job
            priority: Priority of preempting job
            reason: Human-readable reason
        """
        if not self._active:
            return

        if priority.value > self.PREEMPTION_THRESHOLD.value:
            # Not high enough priority to preempt
            return

        event = PreemptionEvent(
            timestamp=datetime.now(),
            job_id=job_id,
            priority=priority,
            reason=reason or f"Job {job_id} with priority {priority.name}",
        )

        self._last_preemption = event
        self._preempt_event.set()

        logger.info(f"Preemption signaled: {event.reason}")

        # Notify callbacks
        for callback in self._callbacks:
            asyncio.ensure_future(callback(event))

    def on_preemption(
        self,
        callback: Callable[[PreemptionEvent], Awaitable[None]],
    ) -> None:
        """Register callback for preemption events.

        Args:
            callback: Async function called when preemption occurs
        """
        self._callbacks.append(callback)

    def clear(self) -> None:
        """Clear preemption signal (after handling)."""
        self._preempt_event.clear()
        self._last_preemption = None

    @property
    def is_preempted(self) -> bool:
        """Check if preemption has been signaled."""
        return self._preempt_event.is_set()

    @property
    def last_preemption(self) -> PreemptionEvent | None:
        """Get details of last preemption event."""
        return self._last_preemption

    async def run_with_preemption(
        self,
        coro: Awaitable[T],
        timeout: float | None = None,
    ) -> T:
        """Run coroutine with preemption support.

        If a high-priority job arrives during execution,
        raises PreemptedError.

        Args:
            coro: Coroutine to run
            timeout: Optional timeout in seconds

        Returns:
            Result of coroutine if completed

        Raises:
            PreemptedError: If preempted by high-priority job
            asyncio.TimeoutError: If timeout exceeded
        """
        self.activate()
        self.clear()

        try:
            task = asyncio.ensure_future(coro)
            preempt_task = asyncio.create_task(self._preempt_event.wait())

            # Build task set
            tasks = {task, preempt_task}

            # Wait for first to complete
            done, pending = await asyncio.wait(
                tasks,
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel pending tasks
            for p in pending:
                p.cancel()
                try:
                    await p
                except asyncio.CancelledError:
                    pass

            # Check what completed
            if preempt_task in done:
                # Preemption occurred
                reason = self._last_preemption.reason if self._last_preemption else "Unknown"
                raise PreemptedError(reason)

            if task in done:
                # Task completed normally
                return task.result()

            # Timeout occurred
            raise asyncio.TimeoutError("Operation timed out")

        finally:
            self.deactivate()

    async def check_preemption(self) -> None:
        """Check if preemption occurred and raise if so.

        Call this periodically in long-running operations
        to check for preemption.

        Raises:
            PreemptedError: If preemption has been signaled
        """
        if self.is_preempted:
            reason = self._last_preemption.reason if self._last_preemption else "Unknown"
            raise PreemptedError(reason)

        # Yield to allow preemption signal to propagate
        await asyncio.sleep(0)


# Module-level singleton
_preemption_manager: PreemptionManager | None = None


def get_preemption_manager() -> PreemptionManager:
    """Get or create preemption manager singleton."""
    global _preemption_manager
    if _preemption_manager is None:
        _preemption_manager = PreemptionManager()
    return _preemption_manager
