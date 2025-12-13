"""Programmatic access to MCP operations.

This module provides direct Python access to the operations
exposed by the MCP server, returning dicts instead of JSON strings.
Used by internal agents and components that need structured data.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def ask_reasoning(
    question: str,
    system_prompt: str = "",
    max_tokens: int = 4096,
) -> dict:
    """Query the reasoning model for complex analysis.

    Uses chain-of-thought reasoning for math, logic, and analysis tasks.
    Falls back to default model if preferred reasoning model unavailable.

    Args:
        question: The question or prompt
        system_prompt: Optional system prompt
        max_tokens: Maximum tokens to generate

    Returns:
        Dict with keys: content, model, input_tokens, output_tokens
    """
    try:
        from ..inference import get_client, Message
        from ..models import get_model_for_task, TaskType

        # Get preferred reasoning model (may not be deployed)
        model_spec = get_model_for_task(TaskType.REASONING)
        client = get_client()

        messages = []
        if system_prompt:
            messages.append(Message(role="system", content=system_prompt))
        messages.append(Message(role="user", content=question))

        # Try with preferred model, fallback to default on error
        try:
            result = await client.complete(
                messages=messages,
                model=model_spec.model_id if model_spec else None,
                temperature=model_spec.default_temperature if model_spec else 0.6,
                max_tokens=max_tokens,
            )
        except Exception:
            # Fallback: use default model (no override)
            result = await client.complete(
                messages=messages,
                temperature=0.6,
                max_tokens=max_tokens,
            )

        return {
            "content": result.content,
            "model": result.model,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        }
    except Exception as e:
        logger.warning(f"ask_reasoning failed: {e}")
        return {"error": str(e), "content": ""}


async def run_swarm(
    query: str,
    domain: str = "",
    num_agents: int = 7,
) -> dict:
    """Run swarm analysis on a query.

    Args:
        query: The query or topic to analyze
        domain: Domain context (pension, kudu, etc.)
        num_agents: Number of specialist agents

    Returns:
        Dict with keys: query, domain, synthesis, perspectives, success_rate, tokens_used
    """
    try:
        from ..client.engine_proxy import get_scheduler_proxy, use_engine_proxy
        from ..agents.roles import AgentRole

        if not use_engine_proxy():
            return {"error": "Gaius engine not running. Start with: devenv up -d"}

        # Select subset of roles based on num_agents
        all_roles = [r.value for r in AgentRole]
        roles = all_roles[:num_agents] if num_agents < len(all_roles) else None

        scheduler = await get_scheduler_proxy()
        raw_results, saved_path = await scheduler.run_swarm(
            domain=domain or query,
            context=query,
            roles=roles,
        )

        # Convert engine response format
        perspectives = []
        total_tokens = 0
        total_latency = 0
        synthesis = ""

        for role_name, data in raw_results.items():
            tokens = data.get("input_tokens", 0) + data.get("output_tokens", 0)
            succeeded = data.get("status") == "completed"
            content = data.get("content", "")

            perspectives.append({
                "agent": role_name,
                "role": role_name.lower(),
                "analysis": content[:500] + "..." if len(content) > 500 else content,
                "tokens": tokens,
                "succeeded": succeeded,
            })
            total_tokens += tokens
            total_latency += data.get("latency_ms", 0)

            # Extract synthesis from Leader
            if role_name == "Leader" and succeeded:
                synthesis = content

        success_count = sum(1 for p in perspectives if p["succeeded"])
        success_rate = success_count / len(perspectives) if perspectives else 0.0

        return {
            "query": query,
            "domain": domain or query,
            "synthesis": synthesis,
            "perspectives": perspectives,
            "success_rate": success_rate,
            "tokens_used": total_tokens,
            "latency_ms": total_latency,
            "saved_to": saved_path,
        }
    except Exception as e:
        logger.warning(f"run_swarm failed: {e}")
        return {"error": str(e), "synthesis": ""}
