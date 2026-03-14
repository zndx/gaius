"""Pooled budget manager for MetaAgent service.

Manages shared weekly budget across Grok/Cerebras for all tasks (audits, calibration, etc.)
Uses PostgreSQL for persistence and advisory locks for atomic budget acquisition.

Unlike ExternalBudget which tracks per-provider limits, PooledBudgetManager
tracks a single shared pool where Grok and Cerebras calls count against
the same weekly limit.
"""

import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import asyncpg

from gaius.engine.generated import PooledBudgetStatus

logger = logging.getLogger(__name__)

# Advisory lock key for budget acquisition (hash of "metaagent_budget")
BUDGET_LOCK_KEY = int(hashlib.sha256(b"metaagent_budget").hexdigest()[:15], 16)


@dataclass
class BudgetAcquisitionResult:
    """Result of attempting to acquire budget."""

    success: bool
    weekly_remaining: int
    provider: str
    error: str | None = None


class PooledBudgetManager:
    """Manages shared weekly budget pool for MetaAgent operations.

    Features:
    - Single shared pool across Grok/Cerebras
    - PostgreSQL persistence for crash recovery
    - Advisory locks for atomic acquisition
    - Automatic weekly reset via database trigger
    - Per-provider call tracking for analytics

    Guru Meditation Codes:
    - #MA.00000001.BUDGETEXHAUST - Weekly budget exhausted
    - #MA.00000002.BUDGETLOCK - Failed to acquire budget lock
    - #MA.00000003.BUDGETDB - Database error during budget operation
    """

    def __init__(
        self,
        pool_id: str = "weekly_audit",
        weekly_limit: int = 50,
    ):
        """Initialize budget manager.

        Args:
            pool_id: Budget pool identifier
            weekly_limit: Maximum calls per week (default: 50)
        """
        self.pool_id = pool_id
        self.weekly_limit = weekly_limit
        self._pool: asyncpg.Pool | None = None
        self._initialized = False

    async def _get_pool(self) -> asyncpg.Pool:
        """Get or create database connection pool."""
        if self._pool is None:
            from gaius.core.config import get_database_url

            database_url = get_database_url()
            self._pool = await asyncpg.create_pool(
                database_url,
                min_size=1,
                max_size=3,
            )
        return self._pool

    async def ensure_initialized(self) -> None:
        """Ensure budget pool exists in database."""
        if self._initialized:
            return

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Insert default pool if not exists
            await conn.execute(
                """
                INSERT INTO meta.audit_budget_pool (pool_id, weekly_limit)
                VALUES ($1, $2)
                ON CONFLICT (pool_id) DO NOTHING
                """,
                self.pool_id,
                self.weekly_limit,
            )
        self._initialized = True
        logger.debug(f"Budget pool {self.pool_id!r} initialized")

    async def get_status(self) -> PooledBudgetStatus:
        """Get current budget status.

        Returns:
            PooledBudgetStatus proto message with current budget state
        """
        await self.ensure_initialized()

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    weekly_limit,
                    weekly_used,
                    weekly_limit - weekly_used AS weekly_remaining,
                    grok_calls,
                    cerebras_calls,
                    week_start,
                    last_reset,
                    ROUND(weekly_used::NUMERIC / NULLIF(weekly_limit, 0) * 100, 1) AS usage_pct,
                    CASE
                        WHEN weekly_used >= weekly_limit THEN 'exhausted'
                        WHEN weekly_used >= weekly_limit * 0.8 THEN 'low'
                        WHEN weekly_used >= weekly_limit * 0.5 THEN 'moderate'
                        ELSE 'healthy'
                    END AS budget_health
                FROM meta.audit_budget_pool
                WHERE pool_id = $1
                """,
                self.pool_id,
            )

        if not row:
            # Return empty status if pool not found
            return PooledBudgetStatus(
                weekly_limit=self.weekly_limit,
                weekly_used=0,
                weekly_remaining=self.weekly_limit,
                grok_calls=0,
                cerebras_calls=0,
                week_start="",
                last_reset="",
                usage_pct=0.0,
                budget_health="healthy",
            )

        return PooledBudgetStatus(
            weekly_limit=row["weekly_limit"],
            weekly_used=row["weekly_used"],
            weekly_remaining=row["weekly_remaining"],
            grok_calls=row["grok_calls"],
            cerebras_calls=row["cerebras_calls"],
            week_start=str(row["week_start"]) if row["week_start"] else "",
            last_reset=row["last_reset"].isoformat() if row["last_reset"] else "",
            usage_pct=float(row["usage_pct"]) if row["usage_pct"] else 0.0,
            budget_health=row["budget_health"] or "healthy",
        )

    async def can_use(self) -> bool:
        """Check if budget is available.

        Returns:
            True if budget is available, False if exhausted
        """
        status = await self.get_status()
        return status.weekly_remaining > 0

    async def acquire(self, provider: str, timeout_seconds: float = 5.0) -> BudgetAcquisitionResult:
        """Atomically acquire one unit of budget.

        Uses PostgreSQL advisory lock to ensure atomic acquisition.
        Only one call at a time can acquire budget.

        Args:
            provider: Provider name (grok, cerebras)
            timeout_seconds: Lock acquisition timeout

        Returns:
            BudgetAcquisitionResult with success status and remaining budget
        """
        await self.ensure_initialized()

        provider = provider.lower()
        if provider not in ("grok", "cerebras"):
            return BudgetAcquisitionResult(
                success=False,
                weekly_remaining=0,
                provider=provider,
                error=f"Invalid provider: {provider}. Must be 'grok' or 'cerebras'",
            )

        pool = await self._get_pool()

        try:
            async with pool.acquire() as conn:
                # Try to acquire advisory lock with timeout
                lock_acquired = await asyncio.wait_for(
                    conn.fetchval(
                        "SELECT pg_try_advisory_lock($1)",
                        BUDGET_LOCK_KEY,
                    ),
                    timeout=timeout_seconds,
                )

                if not lock_acquired:
                    logger.warning(
                        f"[#MA.00000002.BUDGETLOCK] Failed to acquire budget lock for {provider}"
                    )
                    return BudgetAcquisitionResult(
                        success=False,
                        weekly_remaining=0,
                        provider=provider,
                        error="Failed to acquire budget lock. Another operation in progress.",
                    )

                try:
                    # Check and update budget atomically
                    # The database trigger will auto-reset if week changed
                    row = await conn.fetchrow(
                        f"""
                        UPDATE meta.audit_budget_pool
                        SET
                            weekly_used = weekly_used + 1,
                            {provider}_calls = {provider}_calls + 1
                        WHERE pool_id = $1
                          AND weekly_used < weekly_limit
                        RETURNING weekly_limit - weekly_used AS weekly_remaining
                        """,
                        self.pool_id,
                    )

                    if not row:
                        # Budget exhausted
                        remaining = await conn.fetchval(
                            """
                            SELECT weekly_limit - weekly_used
                            FROM meta.audit_budget_pool
                            WHERE pool_id = $1
                            """,
                            self.pool_id,
                        )
                        logger.warning(
                            f"[#MA.00000001.BUDGETEXHAUST] Weekly budget exhausted for {provider}"
                        )
                        return BudgetAcquisitionResult(
                            success=False,
                            weekly_remaining=remaining or 0,
                            provider=provider,
                            error="Weekly budget exhausted",
                        )

                    logger.info(
                        f"Budget acquired for {provider}, {row['weekly_remaining']} remaining"
                    )
                    return BudgetAcquisitionResult(
                        success=True,
                        weekly_remaining=row["weekly_remaining"],
                        provider=provider,
                    )

                finally:
                    # Always release lock
                    await conn.execute(
                        "SELECT pg_advisory_unlock($1)",
                        BUDGET_LOCK_KEY,
                    )

        except asyncio.TimeoutError:
            logger.warning(f"[#MA.00000002.BUDGETLOCK] Lock acquisition timed out for {provider}")
            return BudgetAcquisitionResult(
                success=False,
                weekly_remaining=0,
                provider=provider,
                error=f"Lock acquisition timed out after {timeout_seconds}s",
            )
        except Exception as e:
            logger.error(f"[#MA.00000003.BUDGETDB] Database error: {e}")
            return BudgetAcquisitionResult(
                success=False,
                weekly_remaining=0,
                provider=provider,
                error=f"Database error: {e}",
            )

    async def release(self, provider: str) -> None:
        """Release one unit of budget (for rollback on failure).

        Args:
            provider: Provider name (grok, cerebras)
        """
        provider = provider.lower()
        if provider not in ("grok", "cerebras"):
            return

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                UPDATE meta.audit_budget_pool
                SET
                    weekly_used = GREATEST(0, weekly_used - 1),
                    {provider}_calls = GREATEST(0, {provider}_calls - 1)
                WHERE pool_id = $1
                """,
                self.pool_id,
            )
        logger.debug(f"Budget released for {provider}")

    async def reset_weekly(self) -> None:
        """Manually reset weekly budget (admin operation)."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE meta.audit_budget_pool
                SET
                    weekly_used = 0,
                    grok_calls = 0,
                    cerebras_calls = 0,
                    week_start = date_trunc('week', CURRENT_DATE)::DATE,
                    last_reset = NOW()
                WHERE pool_id = $1
                """,
                self.pool_id,
            )
        logger.info(f"Weekly budget reset for pool {self.pool_id!r}")

    async def close(self) -> None:
        """Close database connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._initialized = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict (sync wrapper for status)."""
        # This is a sync method for compatibility; prefer get_status() for async
        return {
            "pool_id": self.pool_id,
            "weekly_limit": self.weekly_limit,
            "note": "Use get_status() for current values",
        }


# Module-level singleton
_pooled_budget: PooledBudgetManager | None = None


def get_pooled_budget() -> PooledBudgetManager:
    """Get or create the pooled budget singleton."""
    global _pooled_budget
    if _pooled_budget is None:
        _pooled_budget = PooledBudgetManager()
    return _pooled_budget


async def reset_pooled_budget() -> None:
    """Reset the pooled budget singleton (for testing)."""
    global _pooled_budget
    if _pooled_budget:
        await _pooled_budget.close()
    _pooled_budget = None
