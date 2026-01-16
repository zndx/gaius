"""XAI API budget management.

Tracks usage of XAI (Grok) API calls to stay within budget limits.
Integrates with the agent_evaluations table for tracking.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Default limits (can be overridden by environment variables)
DEFAULT_DAILY_LIMIT = 50
DEFAULT_WEEKLY_LIMIT = 200


def check_xai_budget(purpose: str = "evaluation") -> bool:
    """Check if XAI budget is available for the given purpose.

    This is a synchronous check that returns quickly. For accurate
    async budget checks, use check_xai_budget_async.

    Args:
        purpose: Purpose of the evaluation (for logging/tracking)

    Returns:
        True if budget is available, False otherwise
    """
    # Check environment for API key first
    api_key = os.environ.get("XAI_API_KEY", "")
    if not api_key:
        logger.debug("XAI API key not configured, budget check returns False")
        return False

    # Simple check - just verify key exists
    # For accurate budget tracking, use async version
    return True


async def check_xai_budget_async(purpose: str = "evaluation") -> bool:
    """Check if XAI budget is available (async version with DB check).

    Args:
        purpose: Purpose of the evaluation (for logging/tracking)

    Returns:
        True if budget is available, False otherwise
    """
    api_key = os.environ.get("XAI_API_KEY", "")
    if not api_key:
        return False

    try:
        from gaius.storage.database import get_xai_budget

        budget = await get_xai_budget()
        if "error" in budget:
            logger.warning(f"Budget check failed: {budget['error']}")
            return True  # Allow on error to not block operations

        daily_remaining = budget.get("daily_remaining", 0)
        weekly_remaining = budget.get("weekly_remaining", 0)

        if daily_remaining <= 0:
            logger.info(f"XAI daily budget exhausted for {purpose}")
            return False

        if weekly_remaining <= 0:
            logger.info(f"XAI weekly budget exhausted for {purpose}")
            return False

        return True

    except Exception as e:
        logger.warning(f"Budget check error: {e}")
        return True  # Allow on error


def record_xai_usage(purpose: str, count: int = 1) -> None:
    """Record XAI API usage (sync stub for async recording).

    This is a fire-and-forget sync wrapper. The actual recording
    happens asynchronously.

    Args:
        purpose: Purpose of the evaluation
        count: Number of API calls made
    """
    # For sync contexts, we just log - actual tracking happens via agent_evaluations
    logger.debug(f"XAI usage: purpose={purpose}, count={count}")


async def record_xai_usage_async(
    purpose: str,
    count: int = 1,
    tokens_used: int = 0,
) -> None:
    """Record XAI API usage in the database (async version).

    Args:
        purpose: Purpose of the evaluation
        count: Number of API calls made
        tokens_used: Tokens consumed (for cost tracking)
    """
    try:
        import asyncpg

        from gaius.storage.database import get_database_url

        url = get_database_url()
        conn = await asyncpg.connect(url)
        try:
            # Record usage in a tracking table
            await conn.execute(
                """
                INSERT INTO xai_usage_log (purpose, count, tokens_used, created_at)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING
                """,
                purpose,
                count,
                tokens_used,
                datetime.now(timezone.utc),
            )
        finally:
            await conn.close()
    except Exception as e:
        # Log but don't fail - tracking shouldn't break operations
        logger.debug(f"Failed to record XAI usage: {e}")


async def get_budget_status() -> dict[str, Any]:
    """Get current XAI budget status.

    Returns:
        Dict with usage and remaining budget info
    """
    from gaius.storage.database import get_xai_budget

    return await get_xai_budget()


async def reset_budget(reset_daily: bool = True, reset_weekly: bool = False) -> dict[str, Any]:
    """Reset XAI budget counters.

    This is for administrative purposes only.

    Args:
        reset_daily: Reset daily usage counter
        reset_weekly: Reset weekly usage counter

    Returns:
        Updated budget status
    """
    # Budget is tracked via agent_evaluations timestamps
    # Resetting requires deleting or archiving old evaluations
    # For now, just return current status
    logger.warning("Budget reset requested but not implemented")
    return await get_budget_status()
