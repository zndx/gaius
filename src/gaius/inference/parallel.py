"""Parallel inference client for evolution workloads.

Distributes LLM calls across multiple vLLM endpoints for maximum throughput.
Used by the evolution daemon for overnight optimization runs.

Engine-First, no bypass: ParallelInferenceClient completes exclusively through
Engine/Complete (the engine owns GPU-aware routing across the evolution
endpoints it starts); this class keeps only the endpoint lifecycle bookkeeping.

Usage:
    client = ParallelInferenceClient()
    await client.start(["evo0", "evo1", "evo2", "evo3", "evo4", "evo5"])

    # Run evaluations in parallel
    results = await client.parallel_complete(messages_list)

    await client.stop()
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

# Engine-First, no bypass: completions go through Engine/Complete (see
# complete()); this client keeps only the endpoint lifecycle bookkeeping.

logger = logging.getLogger(__name__)


@dataclass
class ParallelResult:
    """Result from a parallel completion."""
    content: str
    endpoint: str
    success: bool
    error: str | None = None


class ParallelInferenceClient:
    """Distributes inference calls across multiple vLLM endpoints.

    Features:
    - Round-robin load balancing across endpoints
    - Automatic failover on endpoint errors
    - Concurrent request execution with asyncio.gather
    """

    def __init__(self):
        self._endpoints: dict[str, str] = {}  # name -> url
        self._lock = asyncio.Lock()
        self._model = "mistralai/Mistral-7B-Instruct-v0.3"

    async def start(self, endpoint_names: list[str] | None = None) -> dict[str, bool]:
        """Start parallel inference with specified endpoints.

        Args:
            endpoint_names: List of endpoint names (e.g., ["evo0", "evo1", ...])
                           If None, discovers available evo* endpoints

        Returns:
            Dict of endpoint -> success status
        """
        from ..core.config import get_config
        from .orchestrator import get_orchestrator

        config = get_config()
        orchestrator = get_orchestrator()

        # Get endpoint configs
        if config._raw is None:
            raise RuntimeError("Config not loaded - cannot determine endpoints")
        inference = config._raw.get("gaius", {}).get("inference", {})
        endpoints_raw = inference.get("endpoints", {})

        # Determine which endpoints to use
        if endpoint_names is None:
            # Auto-discover evo* endpoints
            endpoint_names = [name for name in endpoints_raw.keys() if name.startswith("evo")]

        if not endpoint_names:
            logger.warning("No evolution endpoints configured")
            return {}

        results = {}

        # Start each endpoint
        for name in endpoint_names:
            if name not in endpoints_raw:
                logger.warning(f"Endpoint {name} not found in config")
                results[name] = False
                continue

            ep_config = endpoints_raw[name]
            url = ep_config.get("url", "")

            try:
                # Start the endpoint via orchestrator (the engine serves it;
                # completions go through Engine/Complete, never this URL).
                success = await orchestrator.start_endpoint(name)
                if success:
                    self._endpoints[name] = url
                    logger.info(f"Started evolution endpoint: {name} at {url}")
                results[name] = success

            except Exception as e:
                logger.error(f"Failed to start endpoint {name}: {e}")
                results[name] = False

        logger.info(f"Parallel inference ready with {len(self._endpoints)} endpoints")
        return results

    async def stop(self) -> None:
        """Stop all evolution endpoints."""
        from .orchestrator import get_orchestrator

        orchestrator = get_orchestrator()

        for name in list(self._endpoints.keys()):
            try:
                await orchestrator.stop_endpoint(name)
                logger.info(f"Stopped endpoint: {name}")
            except Exception as e:
                logger.warning(f"Error stopping {name}: {e}")

        self._endpoints.clear()

    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> ParallelResult:
        """Complete a single request using next available endpoint."""
        # Engine-First, no bypass: the completion goes through Engine/Complete;
        # the engine routes/load-balances across the evolution endpoints it
        # started (round-robin client pools are its job, not ours).
        from .engine_client import get_engine_client

        system_prompt = None
        user_parts: list[str] = []
        for m in messages:
            if m.get("role") == "system" and system_prompt is None:
                system_prompt = m.get("content") or ""
            else:
                user_parts.append(str(m.get("content") or ""))

        try:
            engine = await get_engine_client()
            res = await engine.complete_simple(
                prompt="\n\n".join(p for p in user_parts if p),
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return ParallelResult(
                content=res.content or "", endpoint=res.backend or "engine", success=True
            )
        except Exception as e:
            logger.warning(f"Engine completion failed: {e}")
            return ParallelResult(
                content="",
                endpoint="engine",
                success=False,
                error=str(e),
            )

    async def parallel_complete(
        self,
        messages_list: list[list[dict[str, str]]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> list[ParallelResult]:
        """Complete multiple requests in parallel across all endpoints.

        Args:
            messages_list: List of message arrays to complete
            temperature: Temperature for all completions
            max_tokens: Max tokens for all completions

        Returns:
            List of results in same order as input
        """
        if not self._endpoints:
            return [
                ParallelResult(content="", endpoint="none", success=False, error="No endpoints")
                for _ in messages_list
            ]

        # Create tasks for all requests
        tasks = []
        for messages in messages_list:
            tasks.append(self.complete(messages, temperature, max_tokens))

        # Run all in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to ParallelResult
        final_results = []
        for r in results:
            if isinstance(r, Exception):
                final_results.append(ParallelResult(
                    content="",
                    endpoint="unknown",
                    success=False,
                    error=str(r),
                ))
            else:
                final_results.append(r)

        return final_results

    @property
    def num_endpoints(self) -> int:
        """Number of active endpoints."""
        return len(self._endpoints)

    @property
    def endpoint_urls(self) -> list[str]:
        """List of active endpoint URLs."""
        return list(self._endpoints.values())


# Module-level singleton
_parallel_client: ParallelInferenceClient | None = None


def get_parallel_client() -> ParallelInferenceClient:
    """Get or create the parallel inference client."""
    global _parallel_client
    if _parallel_client is None:
        _parallel_client = ParallelInferenceClient()
    return _parallel_client
