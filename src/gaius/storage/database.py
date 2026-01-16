"""Centralized database access layer.

Provides a single source of truth for all database queries, eliminating
duplicate implementations across MCP server, widgets, and agents.

All database access should go through this module:
- Evolution cycle data
- Agent evaluation scores
- Daily summaries
- XAI budget tracking

Configuration:
    DATABASE_URL=postgresql://user:pass@host:port/db
"""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Lazy import to avoid hard dependency
_asyncpg = None


def _get_asyncpg():
    """Lazy import asyncpg."""
    global _asyncpg
    if _asyncpg is None:
        import asyncpg
        _asyncpg = asyncpg
    return _asyncpg


def get_database_url() -> str:
    """Get database URL from environment."""
    return os.getenv(
        "DATABASE_URL",
        "postgresql://gaius:gaius@localhost:5432/gaius"
    )


# =============================================================================
# Connection Pool Management
# =============================================================================

# Global connection pool (singleton pattern)
_pool: Any = None


async def get_pool() -> Any:
    """Get or create the global asyncpg connection pool.

    Uses a singleton pattern to reuse the pool across calls.
    Creates a pool with min_size=1, max_size=10.

    Returns:
        asyncpg.Pool instance

    Raises:
        RuntimeError: If pool creation fails
    """
    global _pool
    if _pool is not None:
        return _pool

    asyncpg = _get_asyncpg()
    url = get_database_url()

    _pool = await asyncpg.create_pool(
        url,
        min_size=1,
        max_size=10,
    )
    return _pool


# Alias for internal use (deprecated - use get_pool instead)
_get_pool = get_pool


async def close_pool() -> None:
    """Close the global connection pool if open."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class EvolutionCycle:
    """Evolution cycle record."""
    agent_id: str
    success: bool
    improvement_percent: float
    duration_ms: int
    started_at: datetime
    preempted: bool = False


@dataclass
class AgentScore:
    """Agent evaluation score."""
    agent_id: str
    avg_score: float
    eval_count: int
    last_eval: datetime


@dataclass
class DailySummary:
    """Daily evaluation summary."""
    date: datetime
    total_evals: int
    avg_score: float
    by_agent: dict[str, float]


@dataclass
class EvalComparison:
    """Local vs XAI evaluation comparison."""
    agent_id: str
    local_score: float
    xai_score: float
    correlation: float


# =============================================================================
# Evolution Queries
# =============================================================================

async def get_recent_cycles(limit: int = 10) -> list[EvolutionCycle]:
    """Fetch recent evolution cycles.

    Args:
        limit: Maximum cycles to return

    Returns:
        List of EvolutionCycle records, most recent first
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            rows = await conn.fetch(
                """
                SELECT agent_id, success, improvement_percent,
                       duration_ms, started_at, preempted
                FROM evolution_cycles
                ORDER BY started_at DESC
                LIMIT $1
                """,
                limit
            )
            return [
                EvolutionCycle(
                    agent_id=row["agent_id"],
                    success=row["success"],
                    improvement_percent=row["improvement_percent"] or 0.0,
                    duration_ms=row["duration_ms"] or 0,
                    started_at=row["started_at"],
                    preempted=row.get("preempted", False),
                )
                for row in rows
            ]
        finally:
            await conn.close()
    except Exception:
        return []


async def get_agent_scores() -> list[AgentScore]:
    """Fetch current agent evaluation scores.

    Returns:
        List of AgentScore records for all agents
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            rows = await conn.fetch(
                """
                SELECT agent_id,
                       AVG(overall_score) as avg_score,
                       COUNT(*) as eval_count,
                       MAX(created_at) as last_eval
                FROM agent_evaluations
                GROUP BY agent_id
                ORDER BY avg_score DESC
                """
            )
            return [
                AgentScore(
                    agent_id=row["agent_id"],
                    avg_score=float(row["avg_score"] or 0),
                    eval_count=row["eval_count"],
                    last_eval=row["last_eval"],
                )
                for row in rows
            ]
        finally:
            await conn.close()
    except Exception:
        return []


async def get_evolution_trend(days: int = 7) -> dict[str, Any]:
    """Get evolution performance trend over recent days.

    Args:
        days: Number of days to analyze

    Returns:
        Dict with trend data including daily scores and improvements
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            # Daily summaries
            daily_rows = await conn.fetch(
                """
                SELECT eval_date, total_evals, avg_overall_score,
                       improvement_from_previous
                FROM daily_eval_summaries
                WHERE eval_date >= CURRENT_DATE - $1
                ORDER BY eval_date DESC
                """,
                days
            )

            # Score comparisons
            comparison_rows = await conn.fetch(
                """
                SELECT agent_id, local_score, xai_score, correlation
                FROM eval_score_comparison
                WHERE compared_at >= CURRENT_DATE - $1
                """,
                days
            )

            return {
                "days": days,
                "daily_summaries": [
                    {
                        "date": str(row["eval_date"]),
                        "total_evals": row["total_evals"],
                        "avg_score": float(row["avg_overall_score"] or 0),
                        "improvement": float(row["improvement_from_previous"] or 0),
                    }
                    for row in daily_rows
                ],
                "score_comparisons": [
                    {
                        "agent_id": row["agent_id"],
                        "local_score": float(row["local_score"] or 0),
                        "xai_score": float(row["xai_score"] or 0),
                        "correlation": float(row["correlation"] or 0),
                    }
                    for row in comparison_rows
                ],
            }
        finally:
            await conn.close()
    except Exception as e:
        return {"error": str(e), "days": days, "daily_summaries": [], "score_comparisons": []}


async def get_eval_comparison() -> dict[str, Any]:
    """Get local vs XAI evaluation comparison stats.

    Returns:
        Dict with comparison statistics and correlations
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            rows = await conn.fetch(
                """
                SELECT
                    ae.agent_id,
                    AVG(CASE WHEN ae.evaluator = 'local' THEN ae.overall_score END) as local_avg,
                    AVG(CASE WHEN ae.evaluator = 'xai' THEN ae.overall_score END) as xai_avg,
                    COUNT(CASE WHEN ae.evaluator = 'local' THEN 1 END) as local_count,
                    COUNT(CASE WHEN ae.evaluator = 'xai' THEN 1 END) as xai_count
                FROM agent_evaluations ae
                GROUP BY ae.agent_id
                HAVING COUNT(CASE WHEN ae.evaluator = 'xai' THEN 1 END) > 0
                """
            )

            comparisons = []
            for row in rows:
                local_avg = float(row["local_avg"] or 0)
                xai_avg = float(row["xai_avg"] or 0)

                comparisons.append({
                    "agent_id": row["agent_id"],
                    "local_avg": local_avg,
                    "xai_avg": xai_avg,
                    "local_count": row["local_count"],
                    "xai_count": row["xai_count"],
                    "difference": abs(local_avg - xai_avg),
                })

            # Calculate overall correlation
            if comparisons:
                local_scores = [c["local_avg"] for c in comparisons]
                xai_scores = [c["xai_avg"] for c in comparisons]

                # Simple correlation calculation
                n = len(local_scores)
                if n > 1:
                    mean_local = sum(local_scores) / n
                    mean_xai = sum(xai_scores) / n

                    numerator = sum(
                        (l - mean_local) * (x - mean_xai)
                        for l, x in zip(local_scores, xai_scores)
                    )

                    denom_local = sum((l - mean_local) ** 2 for l in local_scores) ** 0.5
                    denom_xai = sum((x - mean_xai) ** 2 for x in xai_scores) ** 0.5

                    if denom_local > 0 and denom_xai > 0:
                        correlation = numerator / (denom_local * denom_xai)
                    else:
                        correlation = 0.0
                else:
                    correlation = 0.0
            else:
                correlation = 0.0

            return {
                "comparisons": comparisons,
                "overall_correlation": correlation,
                "total_agents": len(comparisons),
            }
        finally:
            await conn.close()
    except Exception as e:
        return {"error": str(e), "comparisons": [], "overall_correlation": 0.0}


# =============================================================================
# XAI Budget Queries
# =============================================================================

async def get_xai_budget() -> dict[str, Any]:
    """Get XAI evaluation budget status.

    Returns:
        Dict with daily/weekly usage and remaining budget
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            # Get usage from last 24 hours and last 7 days
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours') as daily_usage,
                    COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') as weekly_usage
                FROM agent_evaluations
                WHERE evaluator = 'xai'
                """
            )

            # Default limits
            daily_limit = int(os.getenv("XAI_DAILY_LIMIT", "50"))
            weekly_limit = int(os.getenv("XAI_WEEKLY_LIMIT", "200"))

            daily_usage = row["daily_usage"] if row else 0
            weekly_usage = row["weekly_usage"] if row else 0

            return {
                "daily_usage": daily_usage,
                "daily_limit": daily_limit,
                "daily_remaining": max(0, daily_limit - daily_usage),
                "weekly_usage": weekly_usage,
                "weekly_limit": weekly_limit,
                "weekly_remaining": max(0, weekly_limit - weekly_usage),
            }
        finally:
            await conn.close()
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# Held-Out Query Pool
# =============================================================================

async def get_held_out_stats() -> dict[str, Any]:
    """Get statistics about the held-out query pool.

    Returns:
        Dict with pool size, domain breakdown, category breakdown
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            # Total count
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM held_out_queries WHERE NOT used_for_training"
            )

            # By domain
            domain_rows = await conn.fetch(
                """
                SELECT domain, COUNT(*) as count
                FROM held_out_queries
                WHERE NOT used_for_training
                GROUP BY domain
                """
            )

            # By category
            category_rows = await conn.fetch(
                """
                SELECT category, COUNT(*) as count
                FROM held_out_queries
                WHERE NOT used_for_training
                GROUP BY category
                """
            )

            return {
                "total_queries": total or 0,
                "by_domain": {row["domain"]: row["count"] for row in domain_rows},
                "by_category": {row["category"]: row["count"] for row in category_rows},
            }
        finally:
            await conn.close()
    except Exception as e:
        return {"error": str(e), "total_queries": 0}


async def add_held_out_query(
    input_prompt: str,
    domain: str = "",
    category: str = "",
    expected_output: str = "",
) -> dict[str, Any]:
    """Add a query to the held-out evaluation pool.

    Args:
        input_prompt: The query/prompt to add
        domain: Domain classification
        category: Task category
        expected_output: Optional gold standard output

    Returns:
        Dict with success status and query ID
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            query_id = await conn.fetchval(
                """
                INSERT INTO held_out_queries (input_prompt, domain, category, expected_output)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                input_prompt,
                domain,
                category,
                expected_output,
            )
            return {"success": True, "query_id": query_id}
        finally:
            await conn.close()
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# Routing Analytics Queries
# =============================================================================

async def get_routing_summary(hours: int = 24) -> dict[str, Any]:
    """Get routing analytics summary for health checks.

    Args:
        hours: Number of hours to look back

    Returns:
        Dict with routing metrics including mismatch_rate, fallback_rate,
        starved_agents, and capability_gaps
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            # Get aggregate stats
            stats = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) as total_requests,
                    SUM(CASE WHEN fallback_used THEN 1 ELSE 0 END) as fallback_count,
                    SUM(CASE WHEN capability_mismatch THEN 1 ELSE 0 END) as mismatch_count
                FROM routing_decisions
                WHERE created_at > NOW() - $1 * INTERVAL '1 hour'
                """,
                hours,
            )

            total = stats["total_requests"] or 0
            if total == 0:
                return {
                    "total_requests": 0,
                    "fallback_rate": 0.0,
                    "mismatch_rate": 0.0,
                    "starved_agents": [],
                    "capability_gaps": [],
                }

            fallback_rate = (stats["fallback_count"] or 0) / total
            mismatch_rate = (stats["mismatch_count"] or 0) / total

            # Get starved agents (>50% suboptimal routing)
            starved = await conn.fetch(
                """
                SELECT
                    agent_alias,
                    COUNT(*) as total,
                    SUM(CASE WHEN capability_mismatch THEN 1 ELSE 0 END) as mismatches
                FROM routing_decisions
                WHERE created_at > NOW() - $1 * INTERVAL '1 hour'
                GROUP BY agent_alias
                HAVING SUM(CASE WHEN capability_mismatch THEN 1 ELSE 0 END)::float /
                       COUNT(*) > 0.5
                """,
                hours,
            )
            starved_agents = [r["agent_alias"] for r in starved]

            # Get capability gaps
            gaps = await conn.fetch(
                """
                SELECT
                    unnest(mismatched_capabilities) as capability,
                    COUNT(*) as count
                FROM routing_decisions
                WHERE capability_mismatch = TRUE
                  AND created_at > NOW() - $1 * INTERVAL '1 hour'
                GROUP BY 1
                ORDER BY count DESC
                LIMIT 10
                """,
                hours,
            )
            capability_gaps = [
                {"capability": r["capability"], "count": r["count"]}
                for r in gaps
            ]

            return {
                "total_requests": total,
                "fallback_rate": fallback_rate,
                "mismatch_rate": mismatch_rate,
                "starved_agents": starved_agents,
                "capability_gaps": capability_gaps,
            }
        finally:
            await conn.close()
    except Exception as e:
        return {"error": str(e)}


async def get_capability_gaps(days: int = 7) -> list[dict[str, Any]]:
    """Get which capabilities are most frequently missing.

    Args:
        days: Number of days to look back

    Returns:
        List of dicts with capability name and mismatch count
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            rows = await conn.fetch(
                """
                SELECT
                    unnest(mismatched_capabilities) as capability,
                    COUNT(*) as count,
                    COUNT(DISTINCT agent_alias) as affected_agents
                FROM routing_decisions
                WHERE capability_mismatch = TRUE
                  AND created_at > NOW() - $1 * INTERVAL '1 day'
                GROUP BY 1
                ORDER BY count DESC
                """,
                days,
            )
            return [
                {
                    "capability": r["capability"],
                    "count": r["count"],
                    "affected_agents": r["affected_agents"],
                }
                for r in rows
            ]
        finally:
            await conn.close()
    except Exception as e:
        return []


async def get_starved_agents(days: int = 7) -> list[str]:
    """Get agents with >50% suboptimal routing.

    Args:
        days: Number of days to look back

    Returns:
        List of agent aliases that are being starved of optimal models
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            rows = await conn.fetch(
                """
                SELECT agent_alias
                FROM routing_decisions
                WHERE created_at > NOW() - $1 * INTERVAL '1 day'
                GROUP BY agent_alias
                HAVING SUM(CASE WHEN capability_mismatch THEN 1 ELSE 0 END)::float /
                       COUNT(*) > 0.5
                """,
                days,
            )
            return [r["agent_alias"] for r in rows]
        finally:
            await conn.close()
    except Exception as e:
        return []
