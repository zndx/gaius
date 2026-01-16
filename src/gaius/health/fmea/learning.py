"""Adaptive learning for FMEA S/O/D scores.

This module adjusts S/O/D scores based on remediation outcomes
to improve RPN accuracy over time.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator

from .models import RPNScore

if TYPE_CHECKING:
    from asyncpg import Connection, Pool

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _get_connection(
    pool: "Pool | None", conn: "Connection | None"
) -> AsyncIterator["Connection"]:
    """Get a database connection from pool or use existing one."""
    if conn is not None:
        yield conn
    elif pool is not None:
        async with pool.acquire() as new_conn:
            yield new_conn
    else:
        raise RuntimeError(
            "No database connection available.\n"
            "  Guru Meditation: #FMEA.00000002.NO_DB_LEARNING\n"
            "  Ensure pool is initialized or connection is provided."
        )


class AdaptiveLearner:
    """Update S/O/D scores based on remediation outcomes.

    Uses exponential moving average (EMA) to gradually adjust
    scores based on actual outcomes.
    """

    LEARNING_RATE = 0.2  # EMA alpha - how quickly to adapt

    def __init__(self, pool: Pool | None = None):
        """Initialize the adaptive learner.

        Args:
            pool: Database connection pool
        """
        self._pool = pool

    async def update_from_outcome(
        self,
        failure_mode_id: str,
        rpn_score: RPNScore,
        success: bool,
        duration_ms: int | None = None,
        downtime_seconds: int | None = None,
        sla_breach: bool = False,
        detection_lead_time_seconds: int | None = None,
        detected_by: str = "automation",
        endpoint: str | None = None,
        conn: Connection | None = None,
    ) -> dict[str, Any]:
        """Adjust S/O/D scores based on actual outcome.

        Args:
            failure_mode_id: Failure mode ID
            rpn_score: RPN at time of remediation
            success: Whether remediation succeeded
            duration_ms: Time to remediate in milliseconds
            downtime_seconds: Actual system downtime
            sla_breach: Whether SLA was breached
            detection_lead_time_seconds: How early the failure was detected
            detected_by: Detection method (automation, user_report, monitoring)
            endpoint: Affected endpoint for context-specific adjustments
            conn: Database connection

        Returns:
            Dictionary with old and new S/O/D values
        """
        adjustments: dict[str, Any] = {
            "old_severity": rpn_score.severity,
            "old_occurrence": rpn_score.occurrence,
            "old_detection": rpn_score.detection,
        }

        new_s = rpn_score.severity
        new_o = rpn_score.occurrence
        new_d = rpn_score.detection

        # === Occurrence adjustments ===
        if success and (duration_ms is None or duration_ms < 30000):
            # Quick success → lower occurrence risk
            new_o = self._ema(rpn_score.occurrence, target=3)
            adjustments["occurrence_reason"] = "quick_success"
        elif not success:
            # Failure → higher occurrence (likely to recur)
            new_o = self._ema(rpn_score.occurrence, target=8)
            adjustments["occurrence_reason"] = "failure"

        # === Detection adjustments ===
        if detected_by == "user_report":
            # Missed by automation → worse detection
            new_d = min(10, rpn_score.detection + 1)
            adjustments["detection_reason"] = "user_reported"
        elif detection_lead_time_seconds and detection_lead_time_seconds > 300:
            # Good early warning (5+ minutes lead time)
            new_d = max(1, rpn_score.detection - 1)
            adjustments["detection_reason"] = f"early_warning_{detection_lead_time_seconds}s"

        # === Severity adjustments ===
        if downtime_seconds and downtime_seconds > 600:
            # Worse impact than expected (>10 min downtime)
            new_s = min(10, rpn_score.severity + 1)
            adjustments["severity_reason"] = f"high_downtime_{downtime_seconds}s"
        elif sla_breach:
            # SLA breach → significantly higher severity
            new_s = min(10, rpn_score.severity + 2)
            adjustments["severity_reason"] = "sla_breach"
        elif success and (downtime_seconds is None or downtime_seconds < 60):
            # Quick recovery → slightly lower severity
            new_s = max(1, rpn_score.severity - 1)
            adjustments["severity_reason"] = "quick_recovery"

        adjustments["new_severity"] = new_s
        adjustments["new_occurrence"] = new_o
        adjustments["new_detection"] = new_d
        adjustments["new_rpn"] = new_s * new_o * new_d

        # Persist the adjustment
        if self._pool or conn:
            await self._save_adjustment(
                failure_mode_id=failure_mode_id,
                endpoint=endpoint,
                severity=new_s,
                occurrence=new_o,
                detection=new_d,
                conn=conn,
            )

        logger.info(
            f"FMEA Learning: {failure_mode_id} "
            f"S:{rpn_score.severity}→{new_s} "
            f"O:{rpn_score.occurrence}→{new_o} "
            f"D:{rpn_score.detection}→{new_d} "
            f"RPN:{rpn_score.rpn}→{adjustments['new_rpn']}"
        )

        return adjustments

    def _ema(self, current: int, target: int) -> int:
        """Exponential moving average for gradual score adjustment.

        Args:
            current: Current score
            target: Target score to move toward

        Returns:
            Adjusted score (rounded to integer)
        """
        new_value = current * (1 - self.LEARNING_RATE) + target * self.LEARNING_RATE
        return max(1, min(10, round(new_value)))

    async def _save_adjustment(
        self,
        failure_mode_id: str,
        endpoint: str | None,
        severity: int,
        occurrence: int,
        detection: int,
        conn: Connection | None = None,
    ) -> None:
        """Save or update runtime adjustment in database.

        Uses UPSERT to maintain one adjustment per failure_mode + endpoint.
        """
        if not self._pool and not conn:
            return

        async with _get_connection(self._pool, conn) as c:
            await c.execute(
                """
                INSERT INTO fmea_adjustments (
                    failure_mode_id, endpoint, hour_of_day,
                    adjusted_severity, adjusted_occurrence, adjusted_detection,
                    sample_count, last_updated
                ) VALUES ($1, $2, NULL, $3, $4, $5, 1, NOW())
                ON CONFLICT (failure_mode_id, endpoint, hour_of_day)
                DO UPDATE SET
                    adjusted_severity = CASE
                        WHEN fmea_adjustments.sample_count >= 10 THEN
                            (fmea_adjustments.adjusted_severity * 0.9 + $3 * 0.1)::int
                        ELSE $3
                    END,
                    adjusted_occurrence = CASE
                        WHEN fmea_adjustments.sample_count >= 10 THEN
                            (fmea_adjustments.adjusted_occurrence * 0.9 + $4 * 0.1)::int
                        ELSE $4
                    END,
                    adjusted_detection = CASE
                        WHEN fmea_adjustments.sample_count >= 10 THEN
                            (fmea_adjustments.adjusted_detection * 0.9 + $5 * 0.1)::int
                        ELSE $5
                    END,
                    sample_count = fmea_adjustments.sample_count + 1,
                    last_updated = NOW()
                """,
                failure_mode_id,
                endpoint,
                severity,
                occurrence,
                detection,
            )

    async def get_adjustment_stats(
        self,
        failure_mode_id: str,
        conn: Connection | None = None,
    ) -> dict[str, Any]:
        """Get adjustment statistics for a failure mode.

        Args:
            failure_mode_id: Failure mode ID
            conn: Database connection

        Returns:
            Dictionary with adjustment statistics
        """
        if not self._pool and not conn:
            return {}

        async with _get_connection(self._pool, conn) as c:
            rows = await c.fetch(
                """
                SELECT
                    endpoint,
                    hour_of_day,
                    adjusted_severity,
                    adjusted_occurrence,
                    adjusted_detection,
                    sample_count,
                    last_updated
                FROM fmea_adjustments
                WHERE failure_mode_id = $1
                ORDER BY sample_count DESC
                """,
                failure_mode_id,
            )

            return {
                "failure_mode_id": failure_mode_id,
                "adjustments": [dict(row) for row in rows],
                "total_adjustments": len(rows),
            }

    async def reset_adjustments(
        self,
        failure_mode_id: str | None = None,
        conn: Connection | None = None,
    ) -> int:
        """Reset runtime adjustments.

        Args:
            failure_mode_id: Specific failure mode to reset (None = all)
            conn: Database connection

        Returns:
            Number of adjustments deleted
        """
        if not self._pool and not conn:
            return 0

        async with _get_connection(self._pool, conn) as c:
            if failure_mode_id:
                result = await c.execute(
                    "DELETE FROM fmea_adjustments WHERE failure_mode_id = $1",
                    failure_mode_id,
                )
            else:
                result = await c.execute("DELETE FROM fmea_adjustments")

            # Parse "DELETE N" result
            count = int(result.split()[-1]) if result else 0
            logger.info(f"FMEA: Reset {count} adjustments")
            return count
