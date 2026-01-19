"""LLM Exchange Context - Tracked capture for remote LLM API calls.

Provides utilities for tracked LLM exchanges with provenance:

1. `get_source_context()` - Build source_context for router.complete()
2. `link_kb_artifact()` - Link a KB artifact to its source exchange
3. `ExchangeResult` - Dataclass for exchange metadata

The ExternalInferenceRouter now handles capture and lineage emission
automatically. This module provides helpers for:
- Building consistent source_context dicts
- Linking downstream KB artifacts to exchanges
- Converting router responses to ExchangeResult

Usage with router:
    from gaius.engine.backends.external import get_external_router
    from gaius.engine.services.llm_exchange_context import get_source_context

    router = get_external_router()
    response = await router.complete(
        messages=[...],
        source_context=get_source_context(
            agent_alias="metaagent",
            task_type="audit",
        ),
    )

    # response.exchange_id and response.request_hash are populated
    # for linking to derived KB artifacts

Usage for direct API calls (bypassing router):
    async with tracked_llm_exchange("cerebras", "audit") as tracker:
        response = await cerebras_client.chat(messages=[...], model="glm-4.7")
        tracker.record_response(
            messages=[...],
            response_content=response.content,
            model="glm-4.7",
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
        )

    # tracker.result contains ExchangeResult with exchange_id
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncIterator

if TYPE_CHECKING:
    from gaius.hx import ExchangeRecord
    from gaius.engine.backends.external.base import ExternalResponse

logger = logging.getLogger(__name__)


@dataclass
class ExchangeResult:
    """Result of an LLM exchange with capture metadata.

    Attributes:
        content: The LLM response text
        model: Model identifier used
        provider: LLM provider (cerebras, xai, etc.)
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        exchange_id: UUID of the exchange record in raw.exchange
        request_hash: SHA-256 hash for deduplication/lineage linkage
        latency_ms: Request latency in milliseconds
    """

    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    exchange_id: str
    request_hash: str
    latency_ms: int

    @classmethod
    def from_external_response(cls, response: "ExternalResponse") -> "ExchangeResult":
        """Create ExchangeResult from router ExternalResponse.

        Args:
            response: ExternalResponse from router.complete()

        Returns:
            ExchangeResult with exchange metadata

        Raises:
            ValueError: If response doesn't have exchange_id (capture disabled or failed)
        """
        if not response.exchange_id:
            raise ValueError(
                "ExternalResponse has no exchange_id. "
                "Exchange capture may be disabled or failed.\n"
                "  Guru Meditation: #HX.00000003.NOEXCHANGEID"
            )
        return cls(
            content=response.content,
            model=response.model,
            provider=response.provider,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            exchange_id=response.exchange_id,
            request_hash=response.request_hash or "",
            latency_ms=response.latency_ms,
        )


def get_source_context(
    agent_alias: str = "external_inference",
    task_type: str = "completion",
    parent_run_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build source_context dict for router.complete().

    This creates a consistent source_context that:
    - Identifies the calling agent and task type
    - Links to parent lineage runs for nested chains
    - Includes any additional context the caller wants to track

    Args:
        agent_alias: Agent making the call (metaagent, swarm, researcher, etc.)
        task_type: Type of task (audit, synthesis, quality_check, etc.)
        parent_run_id: Optional parent run ID for nested lineage chains
        **extra: Additional context to include

    Returns:
        Dict suitable for router.complete(source_context=...)

    Example:
        response = await router.complete(
            messages=[...],
            source_context=get_source_context(
                agent_alias="metaagent",
                task_type="audit",
                audit_scope="full",  # extra context
            ),
        )
    """
    context: dict[str, Any] = {
        "agent_alias": agent_alias,
        "task_type": task_type,
    }
    if parent_run_id:
        context["parent_run_id"] = parent_run_id
    context.update(extra)
    return context


async def link_kb_artifact(
    kb_path: str,
    exchange_id: str,
    exchange_hash: str | None = None,
) -> None:
    """Emit lineage linking a KB artifact to its source exchange.

    Call this after creating a KB artifact from an LLM response to
    establish the provenance chain: Exchange → KB Artifact.

    Args:
        kb_path: KB path of the created artifact (e.g., "scratch/2026-01-19/report.md")
        exchange_id: UUID of the source exchange
        exchange_hash: Optional request hash for additional linkage

    Example:
        # After creating KB artifact from LLM response
        await link_kb_artifact(
            kb_path="scratch/2026-01-19/audit_report.md",
            exchange_id=response.exchange_id,
            exchange_hash=response.request_hash,
        )
    """
    try:
        from gaius.hx.lineage import Dataset, Job, Run, RunEvent, get_emitter

        # Create datasets
        exchange_dataset = Dataset.from_exchange(
            provider="",  # Provider already captured in exchange record
            exchange_id=exchange_id,
            request_hash=exchange_hash,
        )
        kb_dataset = Dataset.from_kb(kb_path)

        # Emit transformation event
        emitter = get_emitter()
        event = RunEvent.complete(
            run=Run(),
            job=Job.agent("kb_artifact_creation"),
            inputs=[exchange_dataset],
            outputs=[kb_dataset],
        )
        await emitter.emit(event)

        logger.debug(
            f"Linked KB artifact to exchange: {kb_path} <- {exchange_id[:8]}..."
        )

    except Exception as e:
        logger.warning(
            f"Failed to link KB artifact to exchange: {e}\n"
            f"  Guru Meditation: #HX.00000004.LINKFAIL"
        )


# === Direct API call tracking (for code that bypasses the router) ===


class LLMExchangeTracker:
    """Tracks LLM exchange for capture and lineage emission.

    Use this for direct API calls that bypass ExternalInferenceRouter.
    For router-based calls, use get_source_context() instead.
    """

    def __init__(
        self,
        provider: str,
        task_type: str,
        agent_alias: str,
        parent_run_id: str | None,
    ) -> None:
        """Initialize exchange tracker.

        Args:
            provider: LLM provider (cerebras, xai, etc.)
            task_type: Type of task (audit, quality_check, etc.)
            agent_alias: Agent making the call (metaagent, swarm, etc.)
            parent_run_id: Optional parent run ID for nested lineage
        """
        self.provider = provider
        self.task_type = task_type
        self.agent_alias = agent_alias
        self.parent_run_id = parent_run_id
        self._start_time = time.monotonic()
        self._record: ExchangeRecord | None = None
        self.result: ExchangeResult | None = None

    def record_response(
        self,
        messages: list[dict],
        response_content: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        params: dict | None = None,
    ) -> None:
        """Record the exchange details for capture.

        This must be called before the context manager exits.

        Args:
            messages: Chat messages in OpenAI format
            response_content: Full response text from LLM
            model: Model identifier
            input_tokens: Input token count
            output_tokens: Output token count
            params: Request parameters (temperature, max_tokens, etc.)
        """
        from gaius.hx import ExchangeRecord

        latency_ms = int((time.monotonic() - self._start_time) * 1000)

        self._record = ExchangeRecord(
            provider=self.provider,
            request_messages=messages,
            request_model=model,
            request_params=params or {},
            response_content=response_content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            source_context={
                "agent_alias": self.agent_alias,
                "task_type": self.task_type,
                "parent_run_id": self.parent_run_id,
            },
        )

    async def finalize(self) -> None:
        """Capture to HX and emit lineage.

        Called automatically by the context manager on exit.
        """
        if not self._record:
            logger.warning(
                "LLMExchangeTracker.finalize called but no response was recorded. "
                "Call record_response() before exiting the context manager."
            )
            return

        # 1. Capture to Iceberg
        try:
            from gaius.hx import get_exchange_capture

            capture = get_exchange_capture()
            result = await capture.capture(self._record)

            if not result.success:
                logger.error(
                    f"Exchange capture failed: {result.errors}\n"
                    f"  Guru Meditation: #HX.00000001.CAPTUREFAIL"
                )
        except Exception as e:
            logger.error(
                f"Exchange capture error: {e}\n"
                f"  Guru Meditation: #HX.00000001.CAPTUREFAIL"
            )

        # 2. Emit OpenLineage event
        try:
            from gaius.hx.lineage import Dataset, Job, Run, RunEvent, get_emitter

            emitter = get_emitter()
            event = RunEvent.complete(
                run=Run(),
                job=Job.agent(f"{self.agent_alias}_{self.task_type}"),
                inputs=[],
                outputs=[
                    Dataset.from_exchange(
                        provider=self.provider,
                        request_hash=self._record.request_hash,
                        exchange_id=self._record.id,
                    )
                ],
            )
            await emitter.emit(event)
        except Exception as e:
            logger.error(
                f"Lineage emission error: {e}\n"
                f"  Guru Meditation: #HX.00000002.LINEAGEFAIL"
            )

        # 3. Set result for caller
        self.result = ExchangeResult(
            content=self._record.response_content,
            model=self._record.request_model,
            provider=self.provider,
            input_tokens=self._record.input_tokens,
            output_tokens=self._record.output_tokens,
            exchange_id=self._record.id,
            request_hash=self._record.request_hash,
            latency_ms=self._record.latency_ms,
        )

        logger.info(
            f"LLM exchange captured: provider={self.provider} model={self._record.request_model} "
            f"tokens={self._record.input_tokens}+{self._record.output_tokens} "
            f"latency={self._record.latency_ms}ms exchange_id={self._record.id[:8]}..."
        )


@asynccontextmanager
async def tracked_llm_exchange(
    provider: str,
    task_type: str,
    agent_alias: str = "metaagent",
    parent_run_id: str | None = None,
) -> AsyncIterator[LLMExchangeTracker]:
    """Context manager for tracked LLM exchanges (direct API calls).

    Use this when making direct LLM API calls that bypass the router.
    For router-based calls, use get_source_context() instead.

    Args:
        provider: LLM provider (cerebras, xai, bytez, etc.)
        task_type: Type of task (audit, quality_check, etc.)
        agent_alias: Agent making the call (metaagent, swarm, etc.)
        parent_run_id: Optional parent run ID for nested lineage chains

    Yields:
        LLMExchangeTracker to record the response

    Example:
        async with tracked_llm_exchange("cerebras", "audit") as tracker:
            response = await cerebras_client.chat(messages=[...], model="glm-4.7")
            tracker.record_response(
                messages=[...],
                response_content=response.content,
                model="glm-4.7",
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
            )

        # After context exits, tracker.result contains ExchangeResult
        print(f"Exchange ID: {tracker.result.exchange_id}")
    """
    tracker = LLMExchangeTracker(provider, task_type, agent_alias, parent_run_id)
    try:
        yield tracker
    finally:
        await tracker.finalize()
