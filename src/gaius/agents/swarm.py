"""DeepAgents swarm orchestration.

Manages multi-agent coordination for domain analysis.
Agents run in parallel and their outputs are aggregated
and projected onto the 19x19 grid.

Usage:
    from gaius.agents.swarm import SwarmManager

    swarm = SwarmManager()
    results = await swarm.run_round(domain="pension asset allocation")

    # Get agent positions for grid
    positions = swarm.get_agent_positions()
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from .roles import AgentRole, RoleDefinition, get_role, get_all_roles, ROLES


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
                from ..inference.client import get_inference_client

                client = get_inference_client()
                result = await client.chat(
                    prompt,
                    temperature=role_def.temperature,
                    max_tokens=role_def.max_tokens,
                )
                content = result.content
                tokens = result.usage.total_tokens if result.usage else 0
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
