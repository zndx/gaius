"""DeepAgents swarm orchestration.

Manages multi-agent coordination for domain analysis.
Agents run in parallel and their outputs are aggregated
and projected onto the 19x19 grid.

Includes LatentSwarmManager for LatentMAS-style collaboration
where agents communicate via latent embeddings rather than full text,
achieving 70-90% token reduction.

CLTLatentSwarmManager extends this with Cross-Layer Transcoder features,
enabling:
- Interpretable sparse feature communication between agents
- Semantic positioning on the same grid as KB documents
- Time-delay trace embedding for exploration dynamics visualization

Usage:
    from gaius.agents.swarm import SwarmManager, LatentSwarmManager, CLTLatentSwarmManager

    # Standard swarm (text-based)
    swarm = SwarmManager()
    results = await swarm.run_round(domain="pension asset allocation")

    # Latent swarm (embedding-based, more efficient)
    latent_swarm = LatentSwarmManager()
    results = await latent_swarm.run_round(domain="pension asset allocation")

    # CLT swarm (interpretable features + semantic grid positioning)
    clt_swarm = CLTLatentSwarmManager()
    results = await clt_swarm.run_round(domain="pension asset allocation")

    # Get agent positions for grid (semantically projected for CLT swarm)
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
            # Try to use inference client via gRPC
            try:
                from gaius.client import get_grpc_client

                client = await get_grpc_client()
                result = await client.call(
                    service="Scheduler",
                    action="complete",
                    params={
                        "prompt": prompt,
                        "agent": "fast",
                        "max_tokens": role_def.max_tokens,
                        "temperature": role_def.temperature,
                    },
                )
                content = result.get("content", "")
                tokens = result.get("input_tokens", 0) + result.get("output_tokens", 0)
                model = result.get("model", "")
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


@dataclass
class CLTSwarmRoundResult(SwarmRoundResult):
    """Results from a CLT-enhanced swarm round.

    Extends SwarmRoundResult with interpretable CLT features.
    """

    # Consensus features across agents
    consensus_features: dict[int, float] = field(default_factory=dict)

    # Per-agent top features
    agent_features: dict[str, list[tuple[int, float]]] = field(default_factory=dict)

    # Feature overlap matrix (agent pairs)
    feature_overlap: dict[tuple[str, str], float] = field(default_factory=dict)


class CLTLatentSwarmManager(LatentSwarmManager):
    """Swarm manager with CLT-based interpretable collaboration.

    Uses Cross-Layer Transcoders instead of dense embeddings,
    enabling:
    - Interpretable feature-based communication
    - Visible consensus (which features agents agree on)
    - Circuit-level debugging of agent collaboration

    The workflow is:
    1. Agents generate responses
    2. Responses are encoded to CLT sparse features (~115 active per layer)
    3. Features are stored in Qdrant with interpretable structure
    4. Later agents retrieve context via feature overlap similarity
    5. Final consensus is computed as shared features across agents
    """

    def __init__(
        self,
        roles: list[AgentRole] | None = None,
        inference_fn: Callable | None = None,
        clt_model: str = "qwen3-1.7b",
    ):
        """Initialize CLT swarm manager.

        Args:
            roles: List of roles to include (default: all)
            inference_fn: Async function for LLM calls
            clt_model: CLT model for feature extraction
        """
        super().__init__(roles=roles, inference_fn=inference_fn)
        self.clt_model = clt_model
        self._clt_memory = None

    def _get_clt_memory(self):
        """Get or create CLT latent memory."""
        if self._clt_memory is None:
            from .latent import get_clt_memory
            self._clt_memory = get_clt_memory()
        return self._clt_memory

    async def run_round(
        self,
        domain: str,
        context: str = "",
        parallel: bool = True,
    ) -> CLTSwarmRoundResult:
        """Run a complete swarm analysis round with CLT collaboration.

        Uses interpretable sparse features instead of dense embeddings.

        Args:
            domain: Domain to analyze
            context: Additional context from KB
            parallel: If True, run agents within each batch in parallel

        Returns:
            CLTSwarmRoundResult with responses and feature analysis
        """
        result = CLTSwarmRoundResult(
            domain=domain,
            timestamp=datetime.now(),
        )

        # Get CLT memory
        clt_memory = self._get_clt_memory()

        # Clear previous thoughts for this domain
        try:
            await clt_memory.clear_domain(domain)
        except Exception as e:
            logger.warning(f"Failed to clear domain: {e}")

        # Split roles into batches
        role_defs = [get_role(r) for r in self.roles]
        first_batch = [rd for rd in role_defs if rd.role in self.FIRST_BATCH_ROLES]
        second_batch = [rd for rd in role_defs if rd.role not in self.FIRST_BATCH_ROLES]

        logger.info(f"CLT swarm: {len(first_batch)} first batch, {len(second_batch)} second batch")

        # Phase 1: Run first batch with CLT feature extraction
        first_responses, first_features = await self._run_batch_and_extract(
            first_batch, domain, context, clt_memory
        )
        result.responses.extend(first_responses)
        result.agent_features.update(first_features)

        # Phase 2: Build latent context from CLT features
        latent_context = await self._build_clt_context(domain, clt_memory)
        enhanced_context = f"{context}\n\n{latent_context}" if latent_context else context

        # Run second batch with CLT context
        second_responses, second_features = await self._run_batch_and_extract(
            second_batch, domain, enhanced_context, clt_memory
        )
        result.responses.extend(second_responses)
        result.agent_features.update(second_features)

        # Compute consensus features
        result.consensus_features = await clt_memory.compute_feature_consensus(
            domain, min_agents=2
        )

        # Compute feature overlap between agents
        result.feature_overlap = self._compute_feature_overlap(result.agent_features)

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

    async def _run_batch_and_extract(
        self,
        role_defs: list[RoleDefinition],
        domain: str,
        context: str,
        clt_memory,
    ) -> tuple[list[AgentResponse], dict[str, list[tuple[int, float]]]]:
        """Run a batch of agents and extract CLT features.

        Args:
            role_defs: Role definitions to run
            domain: Domain context
            context: Additional context
            clt_memory: CLT working memory

        Returns:
            Tuple of (responses, agent_features dict)
        """
        if not role_defs:
            return [], {}

        # Run agents in parallel
        tasks = [
            self._run_agent(role_def, domain, context)
            for role_def in role_defs
        ]
        responses_raw = await asyncio.gather(*tasks, return_exceptions=True)

        responses = []
        agent_features: dict[str, list[tuple[int, float]]] = {}

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

                # Extract CLT features and store
                if response.succeeded and len(response.content) > 50:
                    try:
                        thought = await clt_memory.store_from_content(
                            agent_role=role_def.role.value,
                            content=response.content,
                            domain=domain,
                            metadata={
                                "model": response.model,
                                "tokens": response.tokens,
                            },
                        )

                        # Record top features for this agent
                        top_features = thought.get_top_features(k=20)
                        agent_features[role_def.role.value] = top_features

                        logger.debug(
                            f"Stored CLT thought for {role_def.name} "
                            f"({thought.total_active} active features)"
                        )

                    except Exception as e:
                        logger.warning(f"Failed to extract CLT features for {role_def.name}: {e}")

        return responses, agent_features

    async def _build_clt_context(self, domain: str, clt_memory) -> str:
        """Build context string from CLT working memory.

        Uses feature-based consensus to build interpretable context.

        Args:
            domain: Domain to retrieve thoughts for
            clt_memory: CLT working memory

        Returns:
            Formatted context string with feature information
        """
        try:
            # Get consensus features
            consensus = await clt_memory.compute_feature_consensus(domain, min_agents=1)

            if not consensus:
                return ""

            # Retrieve thoughts with high feature overlap
            thoughts = await clt_memory.retrieve_similar_clt(
                query_features=consensus,
                limit=5,
                threshold=0.1,
                domain=domain,
            )

            if not thoughts:
                return ""

            # Format as context with feature info
            lines = ["[CLT latent context from other agents:]"]

            # Show consensus features
            top_consensus = sorted(consensus.items(), key=lambda x: x[1], reverse=True)[:10]
            if top_consensus:
                lines.append(f"Consensus features: {[f[0] for f in top_consensus]}")

            # Show agent summaries
            for thought in thoughts:
                top_feats = [f[0] for f in thought.get_top_features(5)]
                lines.append(
                    f"- {thought.agent_role} (features: {top_feats}): "
                    f"{thought.content_summary}"
                )

            return "\n".join(lines)

        except Exception as e:
            logger.warning(f"Failed to build CLT context: {e}")
            return ""

    def _compute_feature_overlap(
        self,
        agent_features: dict[str, list[tuple[int, float]]],
    ) -> dict[tuple[str, str], float]:
        """Compute pairwise feature overlap between agents.

        Args:
            agent_features: Dict of agent -> top features

        Returns:
            Dict of (agent1, agent2) -> Jaccard similarity
        """
        agents = list(agent_features.keys())
        overlap = {}

        for i, agent1 in enumerate(agents):
            for agent2 in agents[i + 1:]:
                feats1 = set(f[0] for f in agent_features[agent1])
                feats2 = set(f[0] for f in agent_features[agent2])

                intersection = len(feats1 & feats2)
                union = len(feats1 | feats2)

                if union > 0:
                    overlap[(agent1, agent2)] = intersection / union
                else:
                    overlap[(agent1, agent2)] = 0.0

        return overlap

    def _update_positions(self, result: SwarmRoundResult) -> None:
        """Update agent grid positions using CLT→ColNomic projection.

        Unlike the parent class which uses random positioning, this method:
        1. Projects CLT sparse features to ColNomic embedding space
        2. Uses the KB's UMAP projector to place agents in the same grid as documents
        3. Updates time-delay traces for exploration dynamics visualization

        This means agents appear WHERE their thoughts are semantically located
        relative to the knowledge base, not at random positions.

        Args:
            result: SwarmRoundResult (must be CLTSwarmRoundResult for CLT features)

        Note:
            Accepts parent type SwarmRoundResult per Liskov Substitution Principle,
            then narrows to CLTSwarmRoundResult at runtime. This enables the override
            to work polymorphically while the isinstance check provides type safety.
        """
        # CLT positioning requires CLTSwarmRoundResult with agent_features
        if not isinstance(result, CLTSwarmRoundResult):
            super()._update_positions(result)
            return

        from .latent.clt_projection import (
            get_clt_projection_bridge,
            get_trace_embedder,
        )

        bridge = get_clt_projection_bridge()
        trace_embedder = get_trace_embedder()

        # Try to get the GridProjector singleton (may not be available)
        try:
            from ..core.projection import get_grid_manager
            grid_manager = get_grid_manager()
            projector = grid_manager.projector if grid_manager else None
        except Exception:
            projector = None

        for response in result.responses:
            if not response.succeeded:
                continue

            role_def = get_role(response.role)
            agent_key = response.role.value

            # Get features for this agent
            if agent_key in result.agent_features:
                features = result.agent_features[agent_key]
                # Convert list of (idx, val) to dict
                feature_dict = {idx: val for idx, val in features}

                # Project to ColNomic embedding space
                embedding = bridge.project_sparse_features(feature_dict)

                # Update trace with new embedding
                trace = trace_embedder.update(agent_key, embedding)

                # Project to grid coordinates
                if projector is not None and projector._fitted and projector._projector is not None:
                    try:
                        coords_2d = projector._projector.transform([embedding])
                        grid_coords = projector._normalize_to_grid(coords_2d)
                        x, y = int(grid_coords[0, 0]), int(grid_coords[0, 1])
                        self._agent_positions[response.name] = (x, y)

                        logger.debug(
                            f"CLT positioned {response.name} at ({x}, {y}) "
                            f"via semantic projection"
                        )
                        continue
                    except Exception as e:
                        logger.debug(f"Projection failed for {response.name}: {e}")

            # Fallback: use random positioning
            self._update_positions_single(response, role_def)

    def _update_positions_single(self, response, role_def) -> None:
        """Position a single agent (called from parent fallback)."""
        import random

        if role_def.projection_behavior == "center":
            x = 9 + random.randint(-3, 3)
            y = 9 + random.randint(-3, 3)
        elif role_def.projection_behavior == "peripheral":
            if random.random() < 0.5:
                x = random.choice([0, 1, 2, 16, 17, 18])
                y = random.randint(0, 18)
            else:
                x = random.randint(0, 18)
                y = random.choice([0, 1, 2, 16, 17, 18])
        else:
            x = random.randint(0, 18)
            y = random.randint(0, 18)

        self._agent_positions[response.name] = (x, y)

    def get_agent_traces(self) -> dict[str, list[tuple[int, int]]]:
        """Get exploration traces for visualization.

        Returns:
            Dict of agent_name -> list of (x, y) positions (most recent first)
        """
        from .latent.clt_projection import get_trace_embedder

        trace_embedder = get_trace_embedder()
        traces: dict[str, list[tuple[int, int]]] = {}

        try:
            from ..core.projection import get_grid_manager
            grid_manager = get_grid_manager()
            projector = grid_manager.projector if grid_manager else None

            if projector is None or not projector._fitted or projector._projector is None:
                return traces

            # Type narrowing: projector._projector is guaranteed non-None here
            umap_projector = projector._projector

            for role, trace in trace_embedder.get_all_traces().items():
                role_name = role  # Could map to role_def.name

                positions = []
                # Current position
                if np.any(trace.current_embedding != 0):
                    coords_2d = umap_projector.transform([trace.current_embedding])
                    grid_coords = projector._normalize_to_grid(coords_2d)
                    positions.append((int(grid_coords[0, 0]), int(grid_coords[0, 1])))

                # Historical positions
                for emb in trace.delayed_embeddings:
                    if np.any(emb != 0):
                        coords_2d = umap_projector.transform([emb])
                        grid_coords = projector._normalize_to_grid(coords_2d)
                        positions.append((int(grid_coords[0, 0]), int(grid_coords[0, 1])))

                if positions:
                    traces[role_name] = positions

        except Exception as e:
            logger.debug(f"Failed to compute traces: {e}")

        return traces


# Module-level singleton for CLT swarm
_clt_swarm_manager: CLTLatentSwarmManager | None = None


def get_clt_swarm_manager(
    roles: list[AgentRole] | None = None,
    inference_fn: Callable | None = None,
    clt_model: str = "qwen3-1.7b",
) -> CLTLatentSwarmManager:
    """Get or create CLT swarm manager singleton."""
    global _clt_swarm_manager
    if _clt_swarm_manager is None:
        _clt_swarm_manager = CLTLatentSwarmManager(
            roles=roles,
            inference_fn=inference_fn,
            clt_model=clt_model,
        )
    return _clt_swarm_manager


async def run_clt_swarm_round(
    domain: str,
    context: str = "",
) -> CLTSwarmRoundResult:
    """Convenience function to run a CLT swarm round."""
    manager = get_clt_swarm_manager()
    return await manager.run_round(domain, context)
