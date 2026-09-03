"""External inference router.

Routes requests to external backends (XAI, Cerebras, Bytez) based on
availability, budget, and capabilities.

Also captures successful request-response pairs to Iceberg for training data.
"""

import asyncio
import logging
import os
from typing import Any, Literal, Optional

from .base import ExternalBackend, ExternalResponse
from .budget import ExternalBudget, get_external_budget
from .xai_backend import XAIBackend
from .cerebras_backend import CerebrasBackend
from .bytez_backend import BytezBackend
from gaius.core.budgets import EXTERNAL_MAX_TOKENS

logger = logging.getLogger(__name__)


def _is_exchange_capture_enabled() -> bool:
    """Check if exchange capture is enabled."""
    env_val = os.environ.get("GAIUS_HX_CAPTURE_EXCHANGES", "true")
    return env_val.lower() in ("1", "true", "yes")


class ExternalInferenceRouter:
    """Central router for external inference backends.

    Routes requests to appropriate external backends based on:
    - Availability (API key configured)
    - Budget (per-token limits for XAI/Cerebras)
    - Concurrency (subscription limits for Bytez)
    - Capabilities (model selection based on task)

    Usage:
        router = ExternalInferenceRouter()

        # Auto-route to best available backend
        response = await router.complete(messages, tier="auto")

        # Force specific tier
        response = await router.complete(messages, tier="token")  # XAI or Cerebras
        response = await router.complete(messages, tier="subscription")  # Bytez
    """

    def __init__(
        self,
        budget: Optional[ExternalBudget] = None,
        xai_model: Optional[str] = None,
        cerebras_model: Optional[str] = None,
        bytez_model: Optional[str] = None,
        capture_exchanges: Optional[bool] = None,
    ):
        """Initialize external inference router.

        Args:
            budget: Budget tracker (uses singleton if not provided)
            xai_model: XAI model override
            cerebras_model: Cerebras model override
            bytez_model: Bytez model override
            capture_exchanges: Whether to capture exchanges to Iceberg.
                               If None, reads from GAIUS_HX_CAPTURE_EXCHANGES env.
        """
        self.budget = budget or get_external_budget()

        # Initialize exchange capture (lazy - only import if enabled)
        if capture_exchanges is None:
            capture_exchanges = _is_exchange_capture_enabled()
        self._capture_enabled = capture_exchanges
        self._exchange_capture = None  # Lazy initialization

        # Initialize backends
        self._backends: dict[str, ExternalBackend] = {}

        xai = XAIBackend(model=xai_model)
        if xai.is_available:
            self._backends["xai"] = xai
            logger.info(f"XAI backend initialized (model: {xai._model})")

        cerebras = CerebrasBackend(model=cerebras_model)
        if cerebras.is_available:
            self._backends["cerebras"] = cerebras
            logger.info(f"Cerebras backend initialized (model: {cerebras._model})")

        bytez = BytezBackend(model=bytez_model)
        if bytez.is_available:
            self._backends["bytez"] = bytez
            logger.info(f"Bytez backend initialized (model: {bytez._model})")

        if not self._backends:
            logger.warning("No external backends available (missing API keys)")

        if self._capture_enabled:
            logger.info("Exchange capture enabled (will store to Iceberg)")

    def _get_exchange_capture(self):
        """Get or create exchange capture instance (lazy initialization)."""
        if not self._capture_enabled:
            return None
        if self._exchange_capture is None:
            try:
                from gaius.hx.exchange import get_exchange_capture
                self._exchange_capture = get_exchange_capture()
            except Exception as e:
                logger.warning(f"Failed to initialize exchange capture: {e}")
                self._capture_enabled = False
                return None
        return self._exchange_capture

    @property
    def available_backends(self) -> list[str]:
        """List of available backend names."""
        return list(self._backends.keys())

    @property
    def token_tier_backends(self) -> list[str]:
        """Backends using per-token pricing."""
        return [
            name for name, backend in self._backends.items()
            if backend.pricing_model == "per_token"
        ]

    @property
    def subscription_tier_backends(self) -> list[str]:
        """Backends using subscription pricing."""
        return [
            name for name, backend in self._backends.items()
            if backend.pricing_model == "subscription"
        ]

    def get_backend(self, name: str) -> Optional[ExternalBackend]:
        """Get a specific backend by name."""
        return self._backends.get(name)

    async def complete(
        self,
        messages: list[dict[str, str]],
        tier: Literal["auto", "token", "subscription"] = "auto",
        prefer_fast: bool = False,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = EXTERNAL_MAX_TOKENS,
        source_context: Optional[dict[str, Any]] = None,
        emit_lineage: bool = True,
        **kwargs: Any,
    ) -> ExternalResponse:
        """Route completion to best available backend.

        Args:
            messages: Chat messages in OpenAI format
            tier: Which tier to use:
                - "auto": Best available based on budget
                - "token": XAI or Cerebras only
                - "subscription": Bytez only
            prefer_fast: Prefer faster backend (Cerebras) when available
            provider: Force specific provider (xai, cerebras, bytez)
            model: Model override for the backend
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            source_context: Additional context for provenance tracking:
                - agent_alias: Agent making the call (metaagent, swarm, etc.)
                - task_type: Type of task (audit, synthesis, etc.)
                - parent_run_id: Parent lineage run ID for nested chains
            emit_lineage: Whether to emit OpenLineage events (default: True)

        Returns:
            ExternalResponse with completion result (includes exchange_id for linkage)
        """
        # If provider specified, use that directly
        if provider:
            return await self._complete_with_provider(
                provider, messages, model, temperature, max_tokens,
                source_context=source_context, emit_lineage=emit_lineage, **kwargs
            )

        # Select backend based on tier
        if tier == "subscription":
            backend_name = self._select_subscription_backend()
        elif tier == "token":
            backend_name = self._select_token_backend(prefer_fast=prefer_fast)
        else:  # auto
            backend_name = self._select_auto_backend(prefer_fast=prefer_fast)

        if not backend_name:
            return ExternalResponse(
                content="",
                model="",
                provider="none",
                error="No external backend available (all budgets exhausted or unconfigured)",
            )

        return await self._complete_with_provider(
            backend_name, messages, model, temperature, max_tokens,
            source_context=source_context, emit_lineage=emit_lineage, **kwargs
        )

    async def _complete_with_provider(
        self,
        provider: str,
        messages: list[dict[str, str]],
        model: Optional[str],
        temperature: float,
        max_tokens: int,
        source_context: Optional[dict[str, Any]] = None,
        emit_lineage: bool = True,
        **kwargs: Any,
    ) -> ExternalResponse:
        """Complete with specific provider, tracking budget."""
        backend = self._backends.get(provider)
        if not backend:
            return ExternalResponse(
                content="",
                model=model or "",
                provider=provider,
                error=f"Backend '{provider}' not available",
            )

        # Check budget before request
        if provider == "xai" and not self.budget.can_use_xai():
            return ExternalResponse(
                content="",
                model=model or "",
                provider=provider,
                error="XAI daily/weekly budget exhausted",
            )
        elif provider == "cerebras" and not self.budget.can_use_cerebras():
            return ExternalResponse(
                content="",
                model=model or "",
                provider=provider,
                error="Cerebras daily/weekly budget exhausted",
            )
        elif provider == "bytez" and not self.budget.can_use_bytez():
            return ExternalResponse(
                content="",
                model=model or "",
                provider=provider,
                error="Bytez concurrency limit reached",
            )

        # Track Bytez concurrency
        if provider == "bytez":
            self.budget.record_bytez_start()

        try:
            response = await backend.complete(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

            # Record budget usage for token-based backends
            if response.success:
                if provider == "xai":
                    self.budget.record_xai_use(response.total_tokens)
                elif provider == "cerebras":
                    self.budget.record_cerebras_use(response.total_tokens)

                # Capture successful exchange to Iceberg with provenance
                capture = self._get_exchange_capture()
                if capture:
                    try:
                        from gaius.hx.exchange import ExchangeRecord

                        # Build enriched source_context with provider + caller context
                        full_context = {"provider": provider}
                        if source_context:
                            full_context.update(source_context)

                        record = ExchangeRecord(
                            provider=provider,
                            request_messages=messages,
                            request_model=model or response.model or "unknown",
                            request_params={
                                "temperature": temperature,
                                "max_tokens": max_tokens,
                                **kwargs,
                            },
                            response_content=response.content,
                            response_model=response.model,
                            response_reasoning=response.reasoning,  # GLM-4.7 chain-of-thought
                            input_tokens=response.input_tokens,
                            output_tokens=response.output_tokens,
                            latency_ms=response.latency_ms,
                            source_context=full_context,
                        )

                        # Capture to Iceberg (fire-and-forget)
                        asyncio.create_task(capture.capture(record))

                        # Populate exchange linkage fields on response
                        response.exchange_id = record.id
                        response.request_hash = record.request_hash

                        # Emit OpenLineage event for provenance graph
                        if emit_lineage:
                            asyncio.create_task(
                                self._emit_exchange_lineage(record, full_context)
                            )

                    except Exception as e:
                        logger.debug(f"Failed to capture exchange: {e}")

            return response

        finally:
            # Release Bytez slot
            if provider == "bytez":
                self.budget.record_bytez_end()

    async def _emit_exchange_lineage(
        self,
        record: Any,  # ExchangeRecord - using Any to avoid import
        source_context: dict[str, Any],
    ) -> None:
        """Emit OpenLineage event for an exchange.

        Creates a lineage edge from the exchange to derived artifacts.
        The exchange becomes an output Dataset that can be linked to
        downstream KB artifacts created from the LLM response.

        Args:
            record: ExchangeRecord with id and request_hash
            source_context: Context including agent_alias, task_type, parent_run_id
        """
        try:
            from gaius.hx.lineage import Dataset, Job, Run, RunEvent, get_emitter

            # Build job name from context
            agent_alias = source_context.get("agent_alias", "external_inference")
            task_type = source_context.get("task_type", "completion")
            job_name = f"{agent_alias}_{task_type}"

            # Create run with optional parent linkage
            parent_run_id = source_context.get("parent_run_id")
            if parent_run_id:
                from uuid import UUID
                run = Run.with_parent(UUID(parent_run_id) if isinstance(parent_run_id, str) else parent_run_id)
            else:
                run = Run()

            # Create exchange output dataset
            exchange_dataset = Dataset.from_exchange(
                provider=record.provider,
                request_hash=record.request_hash,
                exchange_id=record.id,
            )

            # Emit complete event
            emitter = get_emitter()
            event = RunEvent.complete(
                run=run,
                job=Job.agent(job_name),
                inputs=[],  # Exchange has no upstream inputs at this layer
                outputs=[exchange_dataset],
            )
            await emitter.emit(event)

            logger.debug(
                f"Emitted lineage for exchange: id={record.id[:8]}... "
                f"job={job_name} provider={record.provider}"
            )

        except Exception as e:
            # Don't fail the inference for lineage errors
            logger.warning(
                f"Failed to emit exchange lineage: {e}\n"
                f"  Guru Meditation: #HX.00000002.LINEAGEFAIL"
            )

    def _select_token_backend(self, prefer_fast: bool = False) -> Optional[str]:
        """Select best token-tier backend."""
        candidates = []

        if "cerebras" in self._backends and self.budget.can_use_cerebras():
            candidates.append(("cerebras", 1 if prefer_fast else 2))

        if "xai" in self._backends and self.budget.can_use_xai():
            candidates.append(("xai", 2 if prefer_fast else 1))

        if not candidates:
            return None

        # Sort by priority (lower = better)
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]

    def _select_subscription_backend(self) -> Optional[str]:
        """Select subscription-tier backend."""
        if "bytez" in self._backends and self.budget.can_use_bytez():
            return "bytez"
        return None

    def _select_auto_backend(self, prefer_fast: bool = False) -> Optional[str]:
        """Select best backend across all tiers.

        Strategy:
        1. If token budget available, prefer token tier (better models)
        2. Fall back to subscription tier (always available if configured)
        """
        # Try token tier first
        token_backend = self._select_token_backend(prefer_fast=prefer_fast)
        if token_backend:
            return token_backend

        # Fall back to subscription
        return self._select_subscription_backend()

    async def health_check(self, provider: Optional[str] = None) -> dict[str, bool]:
        """Check health of external backends and exchange capture.

        Args:
            provider: Specific provider to check, or None for all

        Returns:
            Dict mapping provider name to health status.
            Includes "exchange_capture" key if capture is enabled.
        """
        if provider:
            backend = self._backends.get(provider)
            if backend:
                return {provider: await backend.health_check()}
            return {provider: False}

        results = {}
        for name, backend in self._backends.items():
            try:
                results[name] = await backend.health_check()
            except Exception as e:
                logger.debug(f"Health check failed for {name}: {e}")
                results[name] = False

        # Check exchange capture health (CRITICAL for training data)
        if self._capture_enabled:
            capture = self._get_exchange_capture()
            if capture:
                results["exchange_capture"] = await capture.health_check()
                if not results["exchange_capture"]:
                    logger.error(
                        "CRITICAL: Exchange capture storage unhealthy! "
                        "External API responses will NOT be persisted."
                    )

        return results

    def get_status(self) -> dict[str, Any]:
        """Get router status including all backends, budget, and exchange capture."""
        backend_status = {}
        for name, backend in self._backends.items():
            status = backend.get_status()
            # Add budget info
            if name == "xai":
                status["budget"] = self.budget.xai.to_dict()
            elif name == "cerebras":
                status["budget"] = self.budget.cerebras.to_dict()
            elif name == "bytez":
                status["concurrency"] = {
                    "active": self.budget.bytez_active_requests,
                    "max": self.budget.bytez_max_concurrent,
                }
            backend_status[name] = status

        # Get exchange capture status (CRITICAL component)
        exchange_status = {"enabled": self._capture_enabled}
        if self._capture_enabled:
            capture = self._get_exchange_capture()
            if capture:
                exchange_status.update(capture.get_status())
                # Highlight if there are failed captures
                if capture.failed_count > 0:
                    logger.warning(
                        f"Exchange capture has {capture.failed_count} failed records pending retry"
                    )

        return {
            "backends": backend_status,
            "available": self.available_backends,
            "token_tier": self.token_tier_backends,
            "subscription_tier": self.subscription_tier_backends,
            "budget_summary": self.budget.to_dict(),
            "exchange_capture": exchange_status,
        }

    def get_budget_status(self) -> dict[str, Any]:
        """Get budget status for all providers."""
        return self.budget.to_dict()

    async def close(self) -> None:
        """Clean up resources, flushing any pending exchange captures."""
        # Flush exchange capture first (CRITICAL - don't lose training data)
        if self._capture_enabled and self._exchange_capture:
            try:
                result = await self._exchange_capture.flush()
                if result.items_written > 0:
                    logger.info(f"Flushed {result.items_written} pending exchanges to Iceberg")
                if self._exchange_capture.failed_count > 0:
                    logger.error(
                        f"CRITICAL: {self._exchange_capture.failed_count} exchanges failed to persist! "
                        "Training data has been lost."
                    )
            except Exception as e:
                logger.error(f"CRITICAL: Failed to flush exchanges on shutdown: {e}")

        for backend in self._backends.values():
            await backend.close()


# Module-level singleton
_external_router: ExternalInferenceRouter | None = None


def get_external_router() -> ExternalInferenceRouter:
    """Get or create the external router singleton."""
    global _external_router
    if _external_router is None:
        _external_router = ExternalInferenceRouter()
    return _external_router


def reset_external_router() -> None:
    """Reset the external router singleton (for testing)."""
    global _external_router
    _external_router = None
