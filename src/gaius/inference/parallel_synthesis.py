"""Parallel dual-LLM synthesis with relative timeout.

Runs local instruct model and Grok in parallel for search/research commands.
Grok gets a configurable timeout *after* local model completes to ensure
snappy responses while capturing frontier model perspectives when available.

Usage:
    synthesizer = ParallelSynthesizer()
    result = await synthesizer.synthesize(
        query="distributed consensus",
        context="## KB Results\n...",
        system_prompt="You are a research assistant...",
    )

    if result.has_grok:
        print(result.grok_content)
    if result.has_local:
        print(result.local_content)
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from .config import get_grok_timeout, is_grok_enabled

logger = logging.getLogger(__name__)


@dataclass
class ParallelResult:
    """Result from parallel local + Grok synthesis."""

    local_content: Optional[str] = None
    local_model: Optional[str] = None
    local_error: Optional[str] = None
    local_latency_ms: int = 0

    grok_content: Optional[str] = None
    grok_model: Optional[str] = None
    grok_error: Optional[str] = None
    grok_latency_ms: int = 0

    query: str = ""

    @property
    def has_local(self) -> bool:
        """Check if local synthesis succeeded."""
        return bool(self.local_content)

    @property
    def has_grok(self) -> bool:
        """Check if Grok synthesis succeeded."""
        return bool(self.grok_content)

    @property
    def errors(self) -> list[str]:
        """Collect all error messages (excluding skipped modes)."""
        errs = []
        if self.local_error and "Skipped" not in self.local_error:
            errs.append(f"Local: {self.local_error}")
        if self.grok_error and "Skipped" not in self.grok_error:
            errs.append(f"Grok: {self.grok_error}")
        return errs

    @property
    def fallback_action(self) -> str:
        """Action link for fallback to local-only mode."""
        return f"[action:/search --local {self.query}]"


class ParallelSynthesizer:
    """Orchestrates parallel local + Grok inference.

    The key insight is that we want both perspectives:
    - Local (fast, always available): Uses local vLLM with cot_reflection
    - Grok (frontier quality): Uses XAI API for outsider perspective

    The timeout is applied *after* local completes, giving Grok a grace
    period. This ensures we never block on Grok while still capturing
    its output when available.
    """

    async def synthesize(
        self,
        query: str,
        context: str,
        system_prompt: str,
        skip_grok: bool = False,
    ) -> ParallelResult:
        """Run parallel synthesis with relative timeout.

        Args:
            query: The user's query
            context: Context built from search results
            system_prompt: System prompt for synthesis
            skip_grok: If True, skip Grok and use local only

        Returns:
            ParallelResult with content from both backends
        """
        result = ParallelResult(query=query)
        grok_timeout = get_grok_timeout()
        grok_enabled = is_grok_enabled()

        # Skip Grok if disabled globally or via flag
        if skip_grok or not grok_enabled:
            content, model, error, latency = await self._run_local(
                context, system_prompt
            )
            result.local_content = content
            result.local_model = model
            result.local_error = error
            result.local_latency_ms = latency
            result.grok_error = "Skipped (--local mode)" if skip_grok else "Skipped (disabled)"
            return result

        # Start both tasks in parallel
        local_task = asyncio.create_task(
            self._run_local(context, system_prompt),
            name="local_synthesis",
        )
        grok_task = asyncio.create_task(
            self._run_grok(query, context, system_prompt),
            name="grok_synthesis",
        )

        # Phase 1: Wait for local to complete (anchor point)
        try:
            content, model, error, latency = await local_task
            result.local_content = content
            result.local_model = model
            result.local_error = error
            result.local_latency_ms = latency
            logger.debug(f"Local synthesis completed in {latency}ms")
        except Exception as e:
            result.local_error = str(e)
            logger.warning(f"Local synthesis failed: {e}")

        # Phase 2: Apply relative timeout to Grok
        if grok_task.done():
            # Grok finished before or with local
            try:
                content, model, error, latency = grok_task.result()
                result.grok_content = content
                result.grok_model = model
                result.grok_error = error
                result.grok_latency_ms = latency
                logger.debug(f"Grok synthesis completed in {latency}ms (finished with local)")
            except Exception as e:
                result.grok_error = str(e)
                logger.warning(f"Grok synthesis failed: {e}")
        else:
            # Grok still running - apply relative timeout
            try:
                content, model, error, latency = await asyncio.wait_for(
                    grok_task, timeout=grok_timeout
                )
                result.grok_content = content
                result.grok_model = model
                result.grok_error = error
                result.grok_latency_ms = latency
                logger.debug(
                    f"Grok synthesis completed in {latency}ms "
                    f"(within {grok_timeout}s grace period)"
                )
            except asyncio.TimeoutError:
                # Cancel the orphaned task
                grok_task.cancel()
                try:
                    await grok_task
                except asyncio.CancelledError:
                    pass
                result.grok_error = (
                    f"Timeout ({grok_timeout:.0f}s after local completed)"
                )
                logger.info(
                    f"Grok timed out after {grok_timeout}s relative to local "
                    f"(local took {result.local_latency_ms}ms)"
                )
            except Exception as e:
                result.grok_error = str(e)
                logger.warning(f"Grok synthesis failed: {e}")

        return result

    async def _run_local(
        self, context: str, system_prompt: str
    ) -> tuple[Optional[str], Optional[str], Optional[str], int]:
        """Run local instruct synthesis via gRPC.

        Uses the engine's Scheduler.complete with agent="instruct" and
        technique="cot_reflection" for chain-of-thought reasoning.

        Returns:
            Tuple of (content, model, error, latency_ms)
        """
        start = time.time()
        try:
            from gaius.client import get_grpc_client

            client = await get_grpc_client()
            result = await client.call(
                service="Scheduler",
                action="complete",
                params={
                    "prompt": context,
                    "system_prompt": system_prompt,
                    "agent": "instruct",
                    "technique": "cot_reflection",
                    "max_tokens": 4096,
                },
            )

            content = result.get("text", result.get("content", ""))
            model = result.get("model", "local-instruct")
            latency = int((time.time() - start) * 1000)
            return content, model, None, latency
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            return None, None, str(e), latency

    async def _run_grok(
        self, query: str, context: str, system_prompt: str
    ) -> tuple[Optional[str], Optional[str], Optional[str], int]:
        """Run Grok synthesis via XAI backend.

        Uses the external inference router to call XAI's Grok model.
        This provides an "outsider" perspective from a frontier model.

        Returns:
            Tuple of (content, model, error, latency_ms)
        """
        start = time.time()
        try:
            from gaius.engine.backends.external.router import get_external_router

            router = get_external_router()

            if "xai" not in router.available_backends:
                return None, None, "XAI not available (XAI_API_KEY not set)", 0

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Query: {query}\n\n{context}"},
            ]

            response = await router.complete(
                messages=messages,
                provider="xai",
                max_tokens=4096,
                temperature=0.7,
                source_context={
                    "agent_alias": "parallel_synthesizer",
                    "task_type": "frontier_synthesis",
                },
            )

            latency = int((time.time() - start) * 1000)

            if response.error:
                return None, None, response.error, latency

            return response.content, response.model, None, latency
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            return None, None, str(e), latency


# Module-level singleton
_parallel_synthesizer: ParallelSynthesizer | None = None


def get_parallel_synthesizer() -> ParallelSynthesizer:
    """Get or create the parallel synthesizer singleton."""
    global _parallel_synthesizer
    if _parallel_synthesizer is None:
        _parallel_synthesizer = ParallelSynthesizer()
    return _parallel_synthesizer
