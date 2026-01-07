"""Agent runner for evolution using engine infrastructure.

Routes agent inference through the engine's scheduler/router to ensure
proper GPU management and coordination. Validates outputs before returning.

This fixes the core issue where optimization.py bypassed the engine,
creating direct client calls that fail silently with empty outputs.

Usage:
    from gaius.agents.evolution.runner import AgentRunner, get_runner

    runner = await get_runner()
    result = await runner.invoke(agent_config, prompt)
    if result.success:
        print(f"Output: {result.content}")
    else:
        print(f"Failed: {result.error}")
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

from ...models.versioning import AgentConfig

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Result from agent invocation.

    Unlike previous implementations that defaulted to success with empty
    content, this explicitly tracks success/failure and validation.
    """

    content: str
    tokens_used: int
    model: str
    latency_ms: int
    success: bool
    error: Optional[str] = None

    # Validation details
    output_validated: bool = False
    validation_error: Optional[str] = None

    def __post_init__(self):
        """Validate that successful results have content."""
        if self.success and not self.content.strip():
            self.success = False
            self.error = "Empty output content"
            self.validation_error = "Output was empty or whitespace-only"


class AgentRunner:
    """Runs agent inference through the engine's infrastructure.

    Key differences from direct client calls:
    1. Uses SchedulerProxy for proper GPU management
    2. Validates outputs are non-empty before returning success
    3. Tracks detailed error information for debugging
    4. Provides consistent result format for evolution scoring

    The runner ensures evolution never scores empty outputs as 0.5
    (the previous default) - empty outputs are explicit failures.
    """

    def __init__(self):
        """Initialize runner."""
        self._scheduler = None
        self._connected = False

    async def _ensure_connected(self) -> bool:
        """Ensure scheduler proxy is connected.

        Returns:
            True if connected, False if engine unavailable
        """
        if self._connected and self._scheduler is not None:
            return True

        try:
            from ...client.engine_proxy import get_scheduler_proxy, use_engine_proxy

            if not use_engine_proxy():
                logger.warning("Engine not available for AgentRunner")
                return False

            self._scheduler = await get_scheduler_proxy()
            self._connected = True
            return True

        except Exception as e:
            logger.error(f"Failed to connect to engine: {e}")
            return False

    async def invoke(
        self,
        config: AgentConfig,
        prompt: str,
        max_tokens: Optional[int] = None,
    ) -> AgentResult:
        """Invoke an agent with the given config and prompt.

        Routes through engine scheduler for proper resource management.
        Validates output is non-empty before marking as success.

        Args:
            config: Agent configuration (system prompt, temperature, etc.)
            prompt: User prompt to process
            max_tokens: Override max tokens (default: from config)

        Returns:
            AgentResult with output or error details
        """
        start_time = time.perf_counter()

        # Ensure engine connection
        if not await self._ensure_connected():
            return AgentResult(
                content="",
                tokens_used=0,
                model=config.model,
                latency_ms=0,
                success=False,
                error="Engine not available",
            )

        # Type narrowing: _ensure_connected guarantees scheduler is set
        scheduler = self._scheduler
        if scheduler is None:
            return AgentResult(
                content="",
                tokens_used=0,
                model=config.model,
                latency_ms=0,
                success=False,
                error="Scheduler unexpectedly None after connection",
            )

        try:
            # Route through scheduler proxy
            result = await scheduler.complete(
                prompt=prompt,
                agent="fast",  # Default agent, config provides the specifics
                system_prompt=config.system_prompt,
                temperature=config.temperature,
                max_tokens=max_tokens or config.max_tokens,
                technique=config.optillm_technique,
            )

            latency_ms = int((time.perf_counter() - start_time) * 1000)

            # Validate output
            content = result.content or ""
            tokens = result.output_tokens or 0

            # Check for empty output
            if not content.strip():
                return AgentResult(
                    content=content,
                    tokens_used=tokens,
                    model=result.model or config.model,
                    latency_ms=latency_ms,
                    success=False,
                    error="Empty output from model",
                    output_validated=True,
                    validation_error="Model returned empty or whitespace-only content",
                )

            # Check for minimal output (likely truncated or failed)
            if tokens > 0 and len(content.strip()) < 10:
                return AgentResult(
                    content=content,
                    tokens_used=tokens,
                    model=result.model or config.model,
                    latency_ms=latency_ms,
                    success=False,
                    error="Output too short",
                    output_validated=True,
                    validation_error=f"Output only {len(content.strip())} chars, likely truncated",
                )

            # Success
            return AgentResult(
                content=content,
                tokens_used=tokens,
                model=result.model or config.model,
                latency_ms=latency_ms,
                success=True,
                output_validated=True,
            )

        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(f"Agent invocation failed: {e}")
            return AgentResult(
                content="",
                tokens_used=0,
                model=config.model,
                latency_ms=latency_ms,
                success=False,
                error=str(e),
            )

    async def invoke_batch(
        self,
        config: AgentConfig,
        prompts: list[str],
        max_tokens: Optional[int] = None,
    ) -> list[AgentResult]:
        """Invoke agent on multiple prompts.

        Currently sequential, but structured for future parallel execution.

        Args:
            config: Agent configuration
            prompts: List of prompts to process
            max_tokens: Override max tokens

        Returns:
            List of AgentResult for each prompt
        """
        results = []
        for prompt in prompts:
            result = await self.invoke(config, prompt, max_tokens)
            results.append(result)
        return results

    async def health_check(self) -> bool:
        """Check if runner can reach the engine.

        Returns:
            True if engine is reachable and inference endpoints available
        """
        if not await self._ensure_connected():
            return False

        try:
            # Check orchestrator status instead of scheduler
            # Scheduler status may return empty dict which is still valid
            from ...client.engine_proxy import get_orchestrator_proxy

            orch = await get_orchestrator_proxy()
            status = await orch._get_status_async()

            # Check for any healthy endpoints
            endpoints = status.get("endpoints", [])
            healthy = sum(
                1 for ep in endpoints
                if isinstance(ep, dict) and ep.get("status") == "healthy"
            )
            return healthy > 0
        except Exception as e:
            logger.debug(f"Health check failed: {e}")
            return False


# Module-level singleton
_runner: Optional[AgentRunner] = None


async def get_runner() -> AgentRunner:
    """Get or create the AgentRunner singleton.

    Returns:
        AgentRunner instance
    """
    global _runner
    if _runner is None:
        _runner = AgentRunner()
    return _runner


def reset_runner() -> None:
    """Reset the runner singleton (for testing)."""
    global _runner
    _runner = None
