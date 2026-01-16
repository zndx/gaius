"""Endpoint Recovery Manager.

Provides 4-level escalating recovery for failed endpoints:
1. SOFT_RESET - Reduce load, brief cooldown
2. WARM_RESTART - Restart process, same model
3. COLD_RESTART - Full restart with cleanup
4. FAILOVER - Disable endpoint, redistribute jobs

Usage:
    from gaius.inference.recovery import RecoveryManager, RecoveryLevel
    from gaius.client.engine_proxy import get_orchestrator_proxy

    proxy = await get_orchestrator_proxy()
    manager = RecoveryManager(proxy)
    level = manager.determine_recovery_level(failures=3, error=None)
    success = await manager.execute_recovery(endpoint, level)
"""

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Protocol
import asyncio
import logging
import re

if TYPE_CHECKING:
    from ..client.engine_proxy import OrchestratorProxy


class OrchestratorProtocol(Protocol):
    """Protocol for orchestrator interface used by RecoveryManager.

    Defines the minimal interface needed for endpoint recovery.
    Works with both OrchestratorProxy (client-side) and OrchestratorService (engine-side).
    """

    async def health_check(self, endpoint: str) -> bool:
        """Check if endpoint is healthy."""
        ...

    async def stop_endpoint(self, endpoint: str, timeout: float = 30.0) -> bool:
        """Stop an endpoint."""
        ...

    async def start_endpoint(self, endpoint: str) -> Any:
        """Start an endpoint. Returns bool (proxy) or EndpointStatus (service)."""
        ...

    async def get_endpoint_status(self, endpoint: str) -> Any:
        """Get endpoint status."""
        ...


logger = logging.getLogger(__name__)


class RecoveryLevel(IntEnum):
    """Recovery escalation levels."""
    SOFT_RESET = 1      # Reduce load, brief cooldown (5s)
    WARM_RESTART = 2    # Restart vLLM process, keep model
    COLD_RESTART = 3    # Full restart with cleanup
    FAILOVER = 4        # Disable endpoint, redistribute


@dataclass
class RecoveryAttempt:
    """Record of a recovery attempt."""
    endpoint: str
    level: RecoveryLevel
    timestamp: datetime
    success: bool
    error: str | None = None
    duration_ms: int = 0


# Error patterns that suggest specific recovery levels
RECOVERABLE_ERRORS = {
    # OOM - need cold restart to clear GPU memory
    r"CUDA out of memory": RecoveryLevel.COLD_RESTART,
    r"OutOfMemoryError": RecoveryLevel.COLD_RESTART,
    r"CUDA error: out of memory": RecoveryLevel.COLD_RESTART,

    # CUDA driver issues - cold restart
    r"CUDA driver error": RecoveryLevel.COLD_RESTART,
    r"cudaErrorIllegalAddress": RecoveryLevel.COLD_RESTART,
    r"device-side assert": RecoveryLevel.COLD_RESTART,

    # Process issues - warm restart
    r"Connection refused": RecoveryLevel.WARM_RESTART,
    r"Connection reset": RecoveryLevel.WARM_RESTART,
    r"broken pipe": RecoveryLevel.WARM_RESTART,
    r"EOF occurred": RecoveryLevel.WARM_RESTART,

    # Timeout - soft reset first
    r"timed out": RecoveryLevel.SOFT_RESET,
    r"Timeout": RecoveryLevel.SOFT_RESET,
    r"deadline exceeded": RecoveryLevel.SOFT_RESET,
}

# Fatal errors that require manual intervention
FATAL_ERRORS = {
    r"GPU has fallen off the bus",
    r"ECC uncorrectable error",
    r"Xid.*\b(?:31|32|38|43|45|48|63|64|65|68|69|74|79)\b",  # NVIDIA Xid errors
    r"hardware error",
}


class RecoveryManager:
    """Manages endpoint recovery with escalating strategies.

    Works with any orchestrator that implements OrchestratorProtocol:
    - OrchestratorProxy (client-side, via gRPC)
    - OrchestratorService (engine-side, direct)
    """

    def __init__(
        self,
        orchestrator: OrchestratorProtocol,
        max_attempts_per_level: int = 2,
        cooldown_seconds: float = 5.0,
    ):
        self._orchestrator = orchestrator
        self._max_attempts = max_attempts_per_level
        self._cooldown = cooldown_seconds
        self._history: list[RecoveryAttempt] = []
        self._attempt_counts: dict[str, dict[RecoveryLevel, int]] = {}

    def determine_recovery_level(
        self,
        consecutive_failures: int,
        error: Exception | str | None = None,
    ) -> RecoveryLevel:
        """Determine appropriate recovery level based on failures and error type.

        Args:
            consecutive_failures: Number of consecutive failures
            error: The error that triggered recovery (if any)

        Returns:
            Recommended RecoveryLevel
        """
        # Check error patterns first
        if error:
            error_str = str(error)

            # Check for fatal errors
            for pattern in FATAL_ERRORS:
                if re.search(pattern, error_str, re.IGNORECASE):
                    logger.error(f"Fatal error detected: {error_str[:100]}")
                    return RecoveryLevel.FAILOVER

            # Check for recoverable error patterns
            for pattern, level in RECOVERABLE_ERRORS.items():
                if re.search(pattern, error_str, re.IGNORECASE):
                    return level

        # Escalate based on failure count
        if consecutive_failures <= 1:
            return RecoveryLevel.SOFT_RESET
        elif consecutive_failures <= 3:
            return RecoveryLevel.WARM_RESTART
        elif consecutive_failures <= 5:
            return RecoveryLevel.COLD_RESTART
        else:
            return RecoveryLevel.FAILOVER

    async def execute_recovery(
        self,
        endpoint: str,
        level: RecoveryLevel,
    ) -> bool:
        """Execute recovery at the specified level.

        Args:
            endpoint: Endpoint name
            level: Recovery level to execute

        Returns:
            True if recovery succeeded
        """
        start_time = datetime.now()
        success = False
        error_msg = None

        # Track attempts
        if endpoint not in self._attempt_counts:
            self._attempt_counts[endpoint] = {}
        if level not in self._attempt_counts[endpoint]:
            self._attempt_counts[endpoint][level] = 0

        self._attempt_counts[endpoint][level] += 1
        attempt_num = self._attempt_counts[endpoint][level]

        logger.info(
            f"Executing {level.name} recovery for {endpoint} "
            f"(attempt {attempt_num}/{self._max_attempts})"
        )

        try:
            if level == RecoveryLevel.SOFT_RESET:
                success = await self._soft_reset(endpoint)
            elif level == RecoveryLevel.WARM_RESTART:
                success = await self._warm_restart(endpoint)
            elif level == RecoveryLevel.COLD_RESTART:
                success = await self._cold_restart(endpoint)
            elif level == RecoveryLevel.FAILOVER:
                await self._failover(endpoint)
                success = True  # Failover always "succeeds" (endpoint disabled)
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Recovery failed for {endpoint}: {e}")
            success = False

        # Record attempt
        duration = int((datetime.now() - start_time).total_seconds() * 1000)
        self._history.append(RecoveryAttempt(
            endpoint=endpoint,
            level=level,
            timestamp=start_time,
            success=success,
            error=error_msg,
            duration_ms=duration,
        ))

        # If failed and haven't exceeded attempts, try next level
        if not success and attempt_num >= self._max_attempts:
            next_level = RecoveryLevel(min(level + 1, RecoveryLevel.FAILOVER))
            if next_level != level:
                logger.warning(
                    f"Escalating recovery for {endpoint} from {level.name} "
                    f"to {next_level.name}"
                )
                return await self.execute_recovery(endpoint, next_level)

        return success

    async def _soft_reset(self, endpoint: str) -> bool:
        """Level 1: Soft reset - reduce load and brief cooldown.

        Actions:
        - Wait for in-flight requests to drain (brief)
        - Brief cooldown period
        """
        logger.info(f"Soft reset for {endpoint}: cooldown {self._cooldown}s")

        # Brief cooldown
        await asyncio.sleep(self._cooldown)

        # Check if endpoint recovered
        return await self._orchestrator.health_check(endpoint)

    async def _warm_restart(self, endpoint: str) -> bool:
        """Level 2: Warm restart - restart process keeping model.

        Actions:
        - Stop vLLM process gracefully
        - Brief wait
        - Restart with same model
        """
        logger.info(f"Warm restart for {endpoint}")

        # Stop the endpoint
        await self._orchestrator.stop_endpoint(endpoint)

        # Brief cooldown
        await asyncio.sleep(2)

        # Restart
        return await self._orchestrator.start_endpoint(endpoint)

    async def _cold_restart(self, endpoint: str) -> bool:
        """Level 3: Cold restart - full restart with cleanup.

        Actions:
        - Force stop process
        - Wait for GPU memory release
        - Clear any cached state
        - Full restart
        """
        logger.info(f"Cold restart for {endpoint}")

        # Force stop
        await self._orchestrator.stop_endpoint(endpoint, timeout=10)

        # Extended wait for GPU memory release
        logger.info(f"Waiting for GPU memory release on {endpoint}")
        await asyncio.sleep(10)

        # TODO: Could add CUDA context reset here if needed
        # subprocess.run(["nvidia-smi", "--gpu-reset", "-i", str(gpu_id)])

        # Restart
        return await self._orchestrator.start_endpoint(endpoint)

    async def _failover(self, endpoint: str) -> None:
        """Level 4: Failover - disable endpoint and alert.

        Actions:
        - Stop process if running
        - Log critical alert
        - Engine marks status as FAILED on repeated stop

        Note: Status mutation happens in orchestrator service,
        not client-side. Stopping repeatedly marks as failed.
        """
        logger.critical(
            f"FAILOVER: Endpoint {endpoint} has been disabled due to "
            f"repeated failures. Manual intervention required."
        )

        # Stop the endpoint - orchestrator tracks this as failure
        await self._orchestrator.stop_endpoint(endpoint, timeout=10)

        # Log final status for observability
        status = await self._orchestrator.get_endpoint_status(endpoint)
        if status:
            logger.info(f"Endpoint {endpoint} final status: {status}")

        # TODO: Could emit alert to external system
        # await self._emit_alert(endpoint)

        # TODO: Could redistribute pending jobs
        # await self._redistribute_jobs(endpoint)

    def reset_attempt_count(self, endpoint: str) -> None:
        """Reset attempt counts for an endpoint after successful recovery."""
        if endpoint in self._attempt_counts:
            self._attempt_counts[endpoint] = {}

    def get_history(self, endpoint: str | None = None, limit: int = 20) -> list[RecoveryAttempt]:
        """Get recovery history.

        Args:
            endpoint: Filter by endpoint (None for all)
            limit: Max records to return

        Returns:
            List of recovery attempts
        """
        history = self._history
        if endpoint:
            history = [h for h in history if h.endpoint == endpoint]
        return history[-limit:]

    def get_stats(self) -> dict:
        """Get recovery statistics."""
        total = len(self._history)
        successful = sum(1 for h in self._history if h.success)

        by_level = {}
        for level in RecoveryLevel:
            level_attempts = [h for h in self._history if h.level == level]
            level_success = sum(1 for h in level_attempts if h.success)
            by_level[level.name] = {
                "total": len(level_attempts),
                "successful": level_success,
                "rate": level_success / len(level_attempts) if level_attempts else 0,
            }

        return {
            "total_attempts": total,
            "successful": successful,
            "success_rate": successful / total if total > 0 else 0,
            "by_level": by_level,
            "current_attempt_counts": {
                ep: {l.name: c for l, c in counts.items()}
                for ep, counts in self._attempt_counts.items()
            },
        }
