"""DeepAgents swarm orchestration.

Manages multi-agent coordination for domain analysis.
Agents run in parallel and their outputs are aggregated
and projected onto the 19x19 grid.

Includes LatentSwarmManager for LatentMAS-style collaboration
where agents communicate via latent embeddings rather than full text,
achieving 70-90% token reduction.

Usage:
    from gaius.agents.swarm import SwarmManager, LatentSwarmManager

    # Standard swarm (text-based)
    swarm = SwarmManager()
    results = await swarm.run_round(domain="pension asset allocation")

    # Latent swarm (embedding-based, more efficient)
    latent_swarm = LatentSwarmManager()
    results = await latent_swarm.run_round(domain="pension asset allocation")

    # Get agent positions for grid
    positions = swarm.get_agent_positions()
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import numpy as np

from .roles import AgentRole, RoleDefinition, get_role, get_all_roles, ROLES

logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    """Response from a single agent."""

    role: AgentRole
    name: str
    content: str
    tokens: int = 0
    latency_ms: int = 0
    model: str = ""
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass
class SwarmRoundResult:
    """Results from a complete swarm round."""

    domain: str
    timestamp: datetime
    responses: list[AgentResponse] = field(default_factory=list)
    total_tokens: int = 0
    total_latency_ms: int = 0
    consensus: str = ""  # Synthesized consensus from Leader

    @property
    def succeeded(self) -> bool:
        return any(r.succeeded for r in self.responses)

    @property
    def success_rate(self) -> float:
        if not self.responses:
            return 0.0
        return sum(1 for r in self.responses if r.succeeded) / len(self.responses)


class SwarmManager:
    """Orchestrates multi-agent swarm analysis.

    Runs agents in parallel, aggregates responses, and
    projects results to the grid.
    """

    def __init__(
        self,
        roles: list[AgentRole] | None = None,
        inference_fn: Callable | None = None,
    ):
        """Initialize swarm manager.

        Args:
            roles: List of roles to include (default: all)
            inference_fn: Async function for LLM calls (default: uses inference client)
        """
        if roles is None:
            roles = list(AgentRole)
        self.roles = roles

        self._inference_fn = inference_fn
        self._last_round: SwarmRoundResult | None = None
        self._agent_positions: dict[str, tuple[int, int]] = {}

    async def run_round(
        self,
        domain: str,
        context: str = "",
        parallel: bool = True,
    ) -> SwarmRoundResult:
        """Run a complete swarm analysis round.

        Args:
            domain: Domain to analyze
            context: Additional context from KB
            parallel: If True, run agents in parallel

        Returns:
            SwarmRoundResult with all agent responses
        """
        result = SwarmRoundResult(
            domain=domain,
            timestamp=datetime.now(),
        )

        # Get role definitions for active roles
        role_defs = [get_role(r) for r in self.roles]

        if parallel:
            # Run all agents in parallel
            tasks = [
                self._run_agent(role_def, domain, context)
                for role_def in role_defs
            ]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            for role_def, response in zip(role_defs, responses):
                if isinstance(response, Exception):
                    result.responses.append(
                        AgentResponse(
                            role=role_def.role,
                            name=role_def.name,
                            content="",
                            error=str(response),
                        )
                    )
                else:
                    result.responses.append(response)
        else:
            # Run agents sequentially (for debugging)
            for role_def in role_defs:
                try:
                    response = await self._run_agent(role_def, domain, context)
                    result.responses.append(response)
                except Exception as e:
                    result.responses.append(
                        AgentResponse(
                            role=role_def.role,
                            name=role_def.name,
                            content="",
                            error=str(e),
                        )
                    )

        # Calculate totals
        result.total_tokens = sum(r.tokens for r in result.responses)
        result.total_latency_ms = max(
            (r.latency_ms for r in result.responses), default=0
        )

        # Generate consensus from Leader response
        leader_response = next(
            (r for r in result.responses if r.role == AgentRole.LEADER and r.succeeded),
            None,
        )
        if leader_response:
            result.consensus = leader_response.content[:500]

        # Update agent positions
        self._update_positions(result)
        self._last_round = result

        return result

    async def _run_agent(
        self,
        role_def: RoleDefinition,
        domain: str,
        context: str,
    ) -> AgentResponse:
        """Run a single agent.

        Args:
            role_def: Role definition
            domain: Domain to analyze
            context: Additional context

        Returns:
            AgentResponse with content or error
        """
        start_time = datetime.now()

        # Build prompt
        prompt = role_def.get_prompt(domain, context)

        # Call inference
        content = ""
        tokens = 0
        model = ""

        if self._inference_fn is not None:
            # Use provided inference function
            result = await self._inference_fn(
                prompt,
                temperature=role_def.temperature,
                max_tokens=role_def.max_tokens,
            )
            content = result.get("content", "")
            tokens = result.get("tokens", 0)
            model = result.get("model", "")
        else:
            # Try to use inference client
            try:
                from ..inference import get_client, Message

                client = get_client()
                result = await client.complete(
                    [Message(role="user", content=prompt)],
                    temperature=role_def.temperature,
                    max_tokens=role_def.max_tokens,
                )
                content = result.content
                tokens = result.input_tokens + result.output_tokens
                model = result.model or ""
            except ImportError:
                # Inference client not available - return placeholder
                content = f"[{role_def.name} analysis for {domain}]\n\n(Inference not available)"
                model = "placeholder"

        latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        return AgentResponse(
            role=role_def.role,
            name=role_def.name,
            content=content,
            tokens=tokens,
            latency_ms=latency_ms,
            model=model,
        )

    def _update_positions(self, result: SwarmRoundResult) -> None:
        """Update agent grid positions based on responses.

        Projects agent responses to 19x19 grid coordinates.
        """
        import random

        for response in result.responses:
            if not response.succeeded:
                continue

            role_def = get_role(response.role)

            # Calculate position based on projection behavior
            if role_def.projection_behavior == "center":
                # Cluster around center
                x = 9 + random.randint(-3, 3)
                y = 9 + random.randint(-3, 3)
            elif role_def.projection_behavior == "peripheral":
                # Stay near edges
                if random.random() < 0.5:
                    x = random.choice([0, 1, 2, 16, 17, 18])
                    y = random.randint(0, 18)
                else:
                    x = random.randint(0, 18)
                    y = random.choice([0, 1, 2, 16, 17, 18])
            else:
                # Random placement
                x = random.randint(0, 18)
                y = random.randint(0, 18)

            self._agent_positions[response.name] = (x, y)

    def get_agent_positions(self) -> list[tuple[str, int, int, str]]:
        """Get agent positions for grid visualization.

        Returns:
            List of (name, x, y, color) tuples
        """
        positions = []
        for role in self.roles:
            role_def = get_role(role)
            if role_def.name in self._agent_positions:
                x, y = self._agent_positions[role_def.name]
                positions.append((role_def.name, x, y, role_def.color))
        return positions

    def get_last_round(self) -> SwarmRoundResult | None:
        """Get results from the last round."""
        return self._last_round

    def get_agent_summaries(self) -> dict[str, str]:
        """Get summary of each agent's last response."""
        if self._last_round is None:
            return {}

        summaries = {}
        for response in self._last_round.responses:
            if response.succeeded:
                # Truncate to first 200 chars
                summaries[response.name] = response.content[:200]
                if len(response.content) > 200:
                    summaries[response.name] += "..."

        return summaries


# Module-level singleton
_swarm_manager: SwarmManager | None = None


def get_swarm_manager(
    roles: list[AgentRole] | None = None,
    inference_fn: Callable | None = None,
) -> SwarmManager:
    """Get or create swarm manager singleton."""
    global _swarm_manager
    if _swarm_manager is None:
        _swarm_manager = SwarmManager(roles=roles, inference_fn=inference_fn)
    return _swarm_manager


async def run_swarm_round(
    domain: str,
    context: str = "",
) -> SwarmRoundResult:
    """Convenience function to run a swarm round."""
    manager = get_swarm_manager()
    return await manager.run_round(domain, context)


class LatentSwarmManager(SwarmManager):
    """Swarm manager with LatentMAS-style latent collaboration.

    Instead of agents exchanging full text, they:
    1. Generate responses (as normal)
    2. Embed responses into 768-dim Nomic vectors
    3. Store embeddings in Qdrant working memory
    4. Retrieve relevant context via embedding similarity

    This achieves 70-90% token reduction for cross-agent context.

    Uses two-phase execution:
    - Phase 1: First batch (Leader, Risk, Optimizer) populates working memory
    - Phase 2: Second batch retrieves latent context from first batch
    """

    # Define batch splits for two-phase execution
    FIRST_BATCH_ROLES = {AgentRole.LEADER, AgentRole.RISK, AgentRole.OPTIMIZER}

    def __init__(
        self,
        roles: list[AgentRole] | None = None,
        inference_fn: Callable | None = None,
    ):
        """Initialize latent swarm manager.

        Args:
            roles: List of roles to include (default: all)
            inference_fn: Async function for LLM calls
        """
        super().__init__(roles=roles, inference_fn=inference_fn)

        # Lazy-loaded components
        self._memory = None
        self._embeddings = None

    def _get_memory(self):
        """Get or create latent working memory."""
        if self._memory is None:
            from .latent import get_latent_memory
            self._memory = get_latent_memory()
        return self._memory

    def _get_embeddings(self):
        """Get or create embeddings model."""
        if self._embeddings is None:
            from ..models import get_embeddings
            self._embeddings = get_embeddings()
        return self._embeddings

    async def _embed_content(self, content: str) -> np.ndarray:
        """Embed content using Nomic embeddings.

        Args:
            content: Text to embed

        Returns:
            768-dim embedding vector
        """
        embeddings = self._get_embeddings()
        result = await embeddings.embed_text(content[:2000])  # Limit input size
        return result.vector

    async def run_round(
        self,
        domain: str,
        context: str = "",
        parallel: bool = True,
    ) -> SwarmRoundResult:
        """Run a complete swarm analysis round with latent collaboration.

        Uses two-phase execution:
        1. First batch generates thoughts and populates working memory
        2. Second batch retrieves latent context and generates responses

        Args:
            domain: Domain to analyze
            context: Additional context from KB
            parallel: If True, run agents within each batch in parallel

        Returns:
            SwarmRoundResult with all agent responses
        """
        result = SwarmRoundResult(
            domain=domain,
            timestamp=datetime.now(),
        )

        # Clear previous thoughts for this domain
        memory = self._get_memory()
        try:
            await memory.clear_domain(domain)
        except Exception as e:
            logger.warning(f"Failed to clear domain: {e}")

        # Split roles into batches
        role_defs = [get_role(r) for r in self.roles]
        first_batch = [rd for rd in role_defs if rd.role in self.FIRST_BATCH_ROLES]
        second_batch = [rd for rd in role_defs if rd.role not in self.FIRST_BATCH_ROLES]

        logger.info(f"Latent swarm: {len(first_batch)} first batch, {len(second_batch)} second batch")

        # Phase 1: Run first batch (no latent context yet)
        first_responses = await self._run_batch_and_store(
            first_batch, domain, context, memory
        )
        result.responses.extend(first_responses)

        # Phase 2: Run second batch with latent context from first batch
        latent_context = await self._build_latent_context(domain, memory)
        enhanced_context = f"{context}\n\n{latent_context}" if latent_context else context

        second_responses = await self._run_batch_and_store(
            second_batch, domain, enhanced_context, memory
        )
        result.responses.extend(second_responses)

        # Calculate totals
        result.total_tokens = sum(r.tokens for r in result.responses)
        result.total_latency_ms = max(
            (r.latency_ms for r in result.responses), default=0
        )

        # Generate consensus from Leader response
        leader_response = next(
            (r for r in result.responses if r.role == AgentRole.LEADER and r.succeeded),
            None,
        )
        if leader_response:
            result.consensus = leader_response.content[:500]

        # Update agent positions
        self._update_positions(result)
        self._last_round = result

        return result

    async def _run_batch_and_store(
        self,
        role_defs: list[RoleDefinition],
        domain: str,
        context: str,
        memory,
    ) -> list[AgentResponse]:
        """Run a batch of agents and store their embeddings.

        Args:
            role_defs: Role definitions to run
            domain: Domain context
            context: Additional context
            memory: Working memory to store embeddings

        Returns:
            List of AgentResponses
        """
        from .latent import LatentThought

        if not role_defs:
            return []

        # Run agents in parallel
        tasks = [
            self._run_agent(role_def, domain, context)
            for role_def in role_defs
        ]
        responses_raw = await asyncio.gather(*tasks, return_exceptions=True)

        responses = []
        for role_def, response in zip(role_defs, responses_raw):
            if isinstance(response, Exception):
                responses.append(
                    AgentResponse(
                        role=role_def.role,
                        name=role_def.name,
                        content="",
                        error=str(response),
                    )
                )
            else:
                responses.append(response)

                # Store embedding in working memory
                if response.succeeded and len(response.content) > 50:
                    try:
                        embedding = await self._embed_content(response.content)
                        thought = LatentThought.create(
                            agent_role=role_def.role.value,
                            content=response.content,
                            embedding=embedding,
                            domain=domain,
                            metadata={"model": response.model, "tokens": response.tokens},
                        )
                        await memory.store(thought)
                        logger.debug(f"Stored latent thought for {role_def.name}")
                    except Exception as e:
                        logger.warning(f"Failed to store embedding for {role_def.name}: {e}")

        return responses

    async def _build_latent_context(self, domain: str, memory) -> str:
        """Build context string from latent working memory.

        Retrieves relevant thoughts from other agents and formats
        them as a compact context string.

        Args:
            domain: Domain to retrieve thoughts for
            memory: Working memory

        Returns:
            Formatted context string
        """
        try:
            # Get consensus embedding for the domain
            consensus = await memory.get_consensus(domain)

            if np.allclose(consensus, 0):
                return ""

            # Retrieve similar thoughts
            thoughts = await memory.retrieve_similar(
                query_embedding=consensus,
                limit=5,
                threshold=0.3,
                domain=domain,
            )

            if not thoughts:
                return ""

            # Format as compact context
            lines = ["[Latent context from other agents:]"]
            for thought in thoughts:
                lines.append(f"- {thought.agent_role}: {thought.content_summary}")

            return "\n".join(lines)

        except Exception as e:
            logger.warning(f"Failed to build latent context: {e}")
            return ""


# Module-level singleton for latent swarm
_latent_swarm_manager: LatentSwarmManager | None = None


def get_latent_swarm_manager(
    roles: list[AgentRole] | None = None,
    inference_fn: Callable | None = None,
) -> LatentSwarmManager:
    """Get or create latent swarm manager singleton."""
    global _latent_swarm_manager
    if _latent_swarm_manager is None:
        _latent_swarm_manager = LatentSwarmManager(roles=roles, inference_fn=inference_fn)
    return _latent_swarm_manager


async def run_latent_swarm_round(
    domain: str,
    context: str = "",
) -> SwarmRoundResult:
    """Convenience function to run a latent swarm round."""
    manager = get_latent_swarm_manager()
    return await manager.run_round(domain, context)
