"""Engine-backed inference client.

Routes all inference through the Gaius Engine's gRPC scheduler for:
- Centralized metrics export (OTel → Prometheus)
- Proper resource management
- Request queuing and prioritization
- Consistent observability

This is the preferred client for federated engine operations.

Usage:
    from gaius.inference.engine_client import get_engine_client

    client = await get_engine_client()
    result = await client.complete([Message(role="user", content="Hello")])
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Re-export common types for backwards compatibility
from .client import Message
from ..client.engine_proxy import CompletionResult


@dataclass
class EngineCompletionResult:
    """Result from engine completion."""

    content: str
    model: str
    input_tokens: int
    output_tokens: int
    technique: Optional[str] = None
    backend: str = "grpc_engine"
    latency_ms: float = 0.0
    raw_response: Optional[dict] = None


class EngineInferenceClient:
    """Inference client that routes through the Gaius Engine.

    All inference requests go through the engine's scheduler service,
    which records metrics and manages resources centrally.

    Architecture:
        CLI/TUI/MCP → EngineInferenceClient → gRPC → Engine Scheduler → vLLM/optillm
                                                          ↓
                                                    OTel Metrics
    """

    def __init__(self):
        """Initialize the engine client."""
        self._scheduler = None
        self._connected = False

    async def _ensure_connection(self) -> bool:
        """Ensure we have a connection to the engine scheduler."""
        if self._scheduler is not None and self._connected:
            return True

        try:
            from ..client.engine_proxy import get_scheduler_proxy

            self._scheduler = await get_scheduler_proxy()
            self._connected = True
            logger.debug("Connected to engine scheduler")
            return True
        except Exception as e:
            logger.warning(f"Failed to connect to engine scheduler: {e}")
            self._connected = False
            return False

    async def complete(
        self,
        messages: list[Message],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        technique: Optional[str] = None,
    ) -> CompletionResult:
        """Complete a chat message sequence.

        Routes through the engine scheduler for centralized metrics.

        Args:
            messages: List of chat messages
            model: Model/agent to use (default: auto-select)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            technique: Optional optillm technique

        Returns:
            CompletionResult with response
        """
        if not await self._ensure_connection():
            raise RuntimeError(
                "Cannot connect to Gaius Engine. Is it running? "
                "Start with: devenv processes up"
            )

        # Type narrowing: _ensure_connection guarantees scheduler is set
        scheduler = self._scheduler
        if scheduler is None:
            raise RuntimeError("Scheduler unexpectedly None after connection")

        # Extract system prompt and user prompt from messages
        system_prompt = None
        user_prompt = ""

        for msg in messages:
            if msg.role == "system":
                system_prompt = msg.content
            elif msg.role == "user":
                user_prompt = msg.content
            elif msg.role == "assistant":
                # For multi-turn, append to user prompt as context
                user_prompt += f"\nAssistant: {msg.content}\n"

        # Default to instruct model if not specified
        agent = model or "instruct"

        # Route through scheduler
        result = await scheduler.complete(
            prompt=user_prompt,
            agent=agent,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            technique=technique,
        )

        return result

    async def complete_simple(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        technique: Optional[str] = None,
    ) -> CompletionResult:
        """Simple completion with a single prompt.

        Args:
            prompt: User prompt
            model: Model/agent to use
            system_prompt: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            technique: Optional optillm technique

        Returns:
            CompletionResult
        """
        messages = []
        if system_prompt:
            messages.append(Message(role="system", content=system_prompt))
        messages.append(Message(role="user", content=prompt))

        return await self.complete(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            technique=technique,
        )

    async def evaluate(
        self,
        prompt: str,
        force_xai: bool = False,
    ) -> CompletionResult:
        """Evaluate using tiered strategy (local → XAI).

        Args:
            prompt: Prompt to evaluate
            force_xai: Force XAI evaluation if budget allows

        Returns:
            CompletionResult
        """
        if not await self._ensure_connection():
            raise RuntimeError("Cannot connect to Gaius Engine")

        scheduler = self._scheduler
        if scheduler is None:
            raise RuntimeError("Scheduler unexpectedly None after connection")

        return await scheduler.evaluate(prompt, force_xai=force_xai)

    async def run_swarm(
        self,
        query: str,
        domain: str = "",
        num_agents: int = 7,
        context: str = "",
    ) -> tuple[dict, Optional[str]]:
        """Run swarm analysis.

        Args:
            query: Query to analyze
            domain: Domain context
            num_agents: Number of agents
            context: Additional context (if empty, query is used)

        Returns:
            Tuple of (result_dict, saved_path)
        """
        if not await self._ensure_connection():
            raise RuntimeError("Cannot connect to Gaius Engine")

        scheduler = self._scheduler
        if scheduler is None:
            raise RuntimeError("Scheduler unexpectedly None after connection")

        # Import AgentRole to determine role subset
        from ..agents.roles import AgentRole

        all_roles = [r.value for r in AgentRole]
        roles = all_roles[:num_agents] if num_agents < len(all_roles) else None

        return await scheduler.run_swarm(
            domain=domain or query,
            context=context or query,
            roles=roles,
        )

    async def close(self) -> None:
        """Close the connection."""
        self._scheduler = None
        self._connected = False


# Module-level singleton
_engine_client: Optional[EngineInferenceClient] = None


async def get_engine_client() -> EngineInferenceClient:
    """Get or create the engine inference client singleton."""
    global _engine_client
    if _engine_client is None:
        _engine_client = EngineInferenceClient()
    return _engine_client


def use_engine_client() -> bool:
    """Check if engine client should be used.

    Returns True if the engine is available and should be the
    primary inference route.
    """
    import os

    # Check if we should use engine (default: yes if available)
    use_engine = os.getenv("GAIUS_USE_ENGINE", "true").lower() != "false"

    if not use_engine:
        return False

    # Check if engine is reachable
    try:
        from ..client.engine_proxy import use_engine_proxy
        return use_engine_proxy()
    except Exception:
        return False
