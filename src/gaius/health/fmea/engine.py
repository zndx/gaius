"""FMEA Engine for RPN-based autonomous remediation.

This module provides the core FMEAEngine class that:
- Calculates RPN scores with context-aware S/O/D adjustments
- Determines action policies based on RPN thresholds
- Integrates with the existing self-healing infrastructure
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .models import (
    ActionPolicy,
    EscalationTier,
    FailureMode,
    FMEAIncident,
    RPNScore,
)
from .loader import load_failure_mode

if TYPE_CHECKING:
    from asyncpg import Connection, Pool

logger = logging.getLogger(__name__)


class FMEAEngine:
    """FMEA engine for RPN-based autonomous remediation.

    This engine replaces simple severity classification with quantitative
    Risk Priority Number (RPN = S × O × D) calculations.

    RPN Thresholds:
    - RPN < 100: Auto-remediate immediately (Tier 0)
    - RPN 100-200: Auto-remediate with logging (Tier 1)
    - RPN 200-400: Require approval (Tier 2)
    - RPN > 400: Manual intervention required
    """

    # RPN thresholds for escalation tiers
    TIER_0_MAX_RPN = 100      # Auto-remediate immediately
    TIER_1_MAX_RPN = 200      # Auto-remediate with agent validation
    TIER_2_MAX_RPN = 400      # Require approval
    # RPN > 400: Manual intervention required

    # Conservative override thresholds
    LOW_DETECTION_THRESHOLD = 8  # D >= 8 requires approval regardless of RPN

    def __init__(self, pool: Pool | None = None):
        """Initialize the FMEA engine.

        Args:
            pool: Database connection pool
        """
        self._pool = pool
        self._catalog_cache: dict[str, FailureMode] = {}

    async def calculate_rpn(
        self,
        failure_mode_id: str,
        context: dict[str, Any] | None = None,
        endpoint: str | None = None,
        conn: Connection | None = None,
    ) -> RPNScore:
        """Calculate RPN with context-aware S/O/D scores.

        Args:
            failure_mode_id: Failure mode ID (e.g., GPU_001)
            context: Additional context for scoring adjustments
            endpoint: Affected endpoint (for context-specific adjustments)
            conn: Database connection (uses pool if not provided)

        Returns:
            RPNScore with calculated values
        """
        context = context or {}

        # Get failure mode from catalog
        failure_mode = await self._get_failure_mode(failure_mode_id, conn)
        if not failure_mode:
            logger.warning(f"Unknown failure mode: {failure_mode_id}, using defaults")
            failure_mode = FailureMode(
                failure_mode_id=failure_mode_id,
                category="unknown",
                name=failure_mode_id,
                description=None,
                base_severity=5,
                base_occurrence=5,
                base_detection=5,
            )

        # Get historical data for occurrence calculation
        historical = await self._get_historical_data(failure_mode_id, conn)

        # Calculate each component with adjustments
        adjustments: dict[str, Any] = {}

        s = self._calculate_severity(failure_mode, context, historical, adjustments)
        o = self._calculate_occurrence(failure_mode, historical, adjustments)
        d = self._calculate_detection(failure_mode, context, adjustments)

        # Check for runtime adjustments from database
        runtime_adj = await self._get_runtime_adjustments(
            failure_mode_id, endpoint, conn
        )
        if runtime_adj:
            if runtime_adj.get("adjusted_severity"):
                s = runtime_adj["adjusted_severity"]
                adjustments["runtime_severity"] = s
            if runtime_adj.get("adjusted_occurrence"):
                o = runtime_adj["adjusted_occurrence"]
                adjustments["runtime_occurrence"] = o
            if runtime_adj.get("adjusted_detection"):
                d = runtime_adj["adjusted_detection"]
                adjustments["runtime_detection"] = d

        rpn = s * o * d

        logger.info(
            f"FMEA: {failure_mode_id} RPN={rpn} (S={s}, O={o}, D={d})"
        )

        return RPNScore(
            severity=s,
            occurrence=o,
            detection=d,
            rpn=rpn,
            failure_mode_id=failure_mode_id,
            context_adjustments=adjustments,
        )

    def determine_action(
        self,
        rpn_score: RPNScore,
        failure_mode: FailureMode | None = None,
    ) -> ActionPolicy:
        """Determine action policy based on RPN score.

        Args:
            rpn_score: Calculated RPN score
            failure_mode: Optional failure mode for recommended actions

        Returns:
            ActionPolicy with tier, approval requirements, and actions
        """
        tier = rpn_score.tier
        requires_approval = rpn_score.requires_approval
        auto_execute = not requires_approval
        manual_required = tier == EscalationTier.MANUAL

        recommended_actions = []
        if failure_mode:
            recommended_actions = failure_mode.recommended_actions

        policy = ActionPolicy(
            tier=tier,
            requires_approval=requires_approval,
            auto_execute=auto_execute,
            manual_required=manual_required,
            recommended_actions=recommended_actions,
        )

        # Conservative override: low detection capability
        if rpn_score.detection >= self.LOW_DETECTION_THRESHOLD:
            policy = policy.with_override(
                f"Low detection capability (D={rpn_score.detection})"
            )
            logger.warning(
                f"FMEA: Conservative override for {rpn_score.failure_mode_id} "
                f"due to low detection (D={rpn_score.detection})"
            )

        return policy

    async def process_incident(
        self,
        incident: FMEAIncident,
        conn: Connection | None = None,
    ) -> tuple[RPNScore, ActionPolicy]:
        """Process an FMEA incident and determine action.

        Args:
            incident: Detected FMEA incident
            conn: Database connection

        Returns:
            Tuple of (RPNScore, ActionPolicy)
        """
        # Calculate RPN
        rpn_score = await self.calculate_rpn(
            incident.failure_mode_id,
            context=incident.context,
            endpoint=incident.endpoint,
            conn=conn,
        )

        # Get failure mode for actions
        failure_mode = await self._get_failure_mode(
            incident.failure_mode_id, conn
        )

        # Determine action policy
        policy = self.determine_action(rpn_score, failure_mode)

        # Record occurrence for future O calculations
        await self._record_occurrence(incident, conn)

        return rpn_score, policy

    async def record_outcome(
        self,
        failure_mode_id: str,
        rpn_score: RPNScore,
        success: bool,
        action_taken: str,
        tier_used: int,
        duration_ms: int | None = None,
        downtime_seconds: int | None = None,
        sla_breach: bool = False,
        detection_lead_time_seconds: int | None = None,
        detected_by: str = "automation",
        aiops_event_id: int | None = None,
        mlops_event_id: int | None = None,
        conn: Connection | None = None,
    ) -> None:
        """Record remediation outcome for adaptive learning.

        Args:
            failure_mode_id: Failure mode ID
            rpn_score: RPN at time of remediation
            success: Whether remediation succeeded
            action_taken: Action that was taken
            tier_used: Remediation tier used
            duration_ms: Time to remediate in milliseconds
            downtime_seconds: Actual system downtime
            sla_breach: Whether SLA was breached
            detection_lead_time_seconds: How early the failure was detected
            detected_by: Detection method
            aiops_event_id: Link to AIOps event
            mlops_event_id: Link to MLOps event
            conn: Database connection
        """
        if not self._pool and not conn:
            logger.warning("No database connection, skipping outcome recording")
            return

        async with (conn or self._pool.acquire()) as c:
            await c.execute(
                """
                INSERT INTO fmea_outcomes (
                    failure_mode_id, aiops_event_id, mlops_event_id,
                    rpn_score, severity, occurrence, detection,
                    action_taken, tier_used, success,
                    duration_ms, downtime_seconds, sla_breach,
                    detection_lead_time_seconds, detected_by
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                """,
                failure_mode_id,
                aiops_event_id,
                mlops_event_id,
                rpn_score.rpn,
                rpn_score.severity,
                rpn_score.occurrence,
                rpn_score.detection,
                action_taken,
                tier_used,
                success,
                duration_ms,
                downtime_seconds,
                sla_breach,
                detection_lead_time_seconds,
                detected_by,
            )

    # === Private methods ===

    async def _get_failure_mode(
        self,
        failure_mode_id: str,
        conn: Connection | None = None,
    ) -> FailureMode | None:
        """Get failure mode from cache or database."""
        if failure_mode_id in self._catalog_cache:
            return self._catalog_cache[failure_mode_id]

        if not self._pool and not conn:
            return None

        async with (conn or self._pool.acquire()) as c:
            failure_mode = await load_failure_mode(c, failure_mode_id)
            if failure_mode:
                self._catalog_cache[failure_mode_id] = failure_mode
            return failure_mode

    async def _get_historical_data(
        self,
        failure_mode_id: str,
        conn: Connection | None = None,
    ) -> dict[str, Any]:
        """Get historical occurrence and outcome data."""
        if not self._pool and not conn:
            return {}

        async with (conn or self._pool.acquire()) as c:
            # Count occurrences in different time windows
            counts = await c.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (WHERE occurred_at > NOW() - INTERVAL '24 hours') as last_24h,
                    COUNT(*) FILTER (WHERE occurred_at > NOW() - INTERVAL '7 days') as last_7d,
                    COUNT(*) FILTER (WHERE occurred_at > NOW() - INTERVAL '30 days') as last_30d
                FROM fmea_occurrences
                WHERE failure_mode_id = $1
                """,
                failure_mode_id,
            )

            # Get recent outcome success rate
            outcomes = await c.fetchrow(
                """
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE success) as successes,
                    AVG(duration_ms) as avg_duration,
                    AVG(downtime_seconds) as avg_downtime
                FROM fmea_outcomes
                WHERE failure_mode_id = $1
                AND created_at > NOW() - INTERVAL '30 days'
                """,
                failure_mode_id,
            )

            return {
                "occurrences_24h": counts["last_24h"] if counts else 0,
                "occurrences_7d": counts["last_7d"] if counts else 0,
                "occurrences_30d": counts["last_30d"] if counts else 0,
                "total_outcomes": outcomes["total"] if outcomes else 0,
                "success_count": outcomes["successes"] if outcomes else 0,
                "avg_duration_ms": outcomes["avg_duration"] if outcomes else None,
                "avg_downtime_seconds": outcomes["avg_downtime"] if outcomes else None,
            }

    async def _get_runtime_adjustments(
        self,
        failure_mode_id: str,
        endpoint: str | None,
        conn: Connection | None = None,
    ) -> dict[str, Any] | None:
        """Get runtime S/O/D adjustments from database."""
        if not self._pool and not conn:
            return None

        current_hour = datetime.now().hour

        async with (conn or self._pool.acquire()) as c:
            # Try to find specific adjustment for endpoint + hour
            row = await c.fetchrow(
                """
                SELECT adjusted_severity, adjusted_occurrence, adjusted_detection, sample_count
                FROM fmea_adjustments
                WHERE failure_mode_id = $1
                AND (endpoint = $2 OR endpoint IS NULL)
                AND (hour_of_day = $3 OR hour_of_day IS NULL)
                ORDER BY
                    CASE WHEN endpoint IS NOT NULL THEN 1 ELSE 2 END,
                    CASE WHEN hour_of_day IS NOT NULL THEN 1 ELSE 2 END
                LIMIT 1
                """,
                failure_mode_id,
                endpoint,
                current_hour,
            )

            if row and row["sample_count"] >= 3:  # Require minimum samples
                return dict(row)
            return None

    def _calculate_severity(
        self,
        failure_mode: FailureMode,
        context: dict[str, Any],
        historical: dict[str, Any],
        adjustments: dict[str, Any],
    ) -> int:
        """Calculate severity score with context adjustments.

        Adjustments:
        - Multiple endpoints affected: +2-3
        - Critical priority: +2
        - Historical high downtime: +1
        - SLA breaches in history: +2
        """
        s = failure_mode.base_severity

        # Context adjustments
        endpoints_affected = len(context.get("unhealthy_endpoints", []))
        if endpoints_affected >= 3:
            adjustment = min(3, endpoints_affected - 2)
            s = min(10, s + adjustment)
            adjustments["multiple_endpoints"] = f"+{adjustment}"

        if context.get("priority") == "critical":
            s = min(10, s + 2)
            adjustments["critical_priority"] = "+2"

        # Historical adjustments
        avg_downtime = historical.get("avg_downtime_seconds")
        if avg_downtime and avg_downtime > 600:  # >10 min average
            s = min(10, s + 1)
            adjustments["high_historical_downtime"] = "+1"

        return max(1, min(10, s))

    def _calculate_occurrence(
        self,
        failure_mode: FailureMode,
        historical: dict[str, Any],
        adjustments: dict[str, Any],
    ) -> int:
        """Calculate occurrence score from historical data.

        Mapping:
        - 3+ per day: O=10
        - 1-2 per day: O=9
        - 4+ per week: O=8
        - 1-3 per week: O=6
        - 1-4 per month: O=4
        - <1 per month: O=2
        - Never: O=1 (use base)
        """
        last_24h = historical.get("occurrences_24h", 0)
        last_7d = historical.get("occurrences_7d", 0)
        last_30d = historical.get("occurrences_30d", 0)

        if last_24h >= 3:
            o = 10
            adjustments["occurrence_reason"] = f"{last_24h} in 24h"
        elif last_24h >= 1:
            o = 9
            adjustments["occurrence_reason"] = f"{last_24h} in 24h"
        elif last_7d >= 4:
            o = 8
            adjustments["occurrence_reason"] = f"{last_7d} in 7d"
        elif last_7d >= 1:
            o = 6
            adjustments["occurrence_reason"] = f"{last_7d} in 7d"
        elif last_30d >= 4:
            o = 4
            adjustments["occurrence_reason"] = f"{last_30d} in 30d"
        elif last_30d >= 1:
            o = 3
            adjustments["occurrence_reason"] = f"{last_30d} in 30d"
        elif last_30d == 0 and historical.get("total_outcomes", 0) > 0:
            o = 2
            adjustments["occurrence_reason"] = "rare"
        else:
            # No historical data, use base
            o = failure_mode.base_occurrence
            adjustments["occurrence_reason"] = "base (no history)"

        return max(1, min(10, o))

    def _calculate_detection(
        self,
        failure_mode: FailureMode,
        context: dict[str, Any],
        adjustments: dict[str, Any],
    ) -> int:
        """Calculate detection score.

        Adjustments:
        - Early warning (warn status): -2
        - Manual detection (user report): +2
        - Automation level A (full): base - 2
        - Automation level B (partial): base
        - No automation: base + 2
        """
        d = failure_mode.base_detection

        # Detection method adjustments
        detection_method = failure_mode.detection_method
        if detection_method == "health_check":
            d = max(1, d - 1)
            adjustments["detection_automated"] = "-1"
        elif detection_method == "manual":
            d = min(10, d + 2)
            adjustments["detection_manual"] = "+2"

        # Context adjustments
        if context.get("status") == "warn":
            d = max(1, d - 2)
            adjustments["early_warning"] = "-2"

        if context.get("detected_by") == "user_report":
            d = min(10, d + 2)
            adjustments["user_reported"] = "+2"

        return max(1, min(10, d))

    async def _record_occurrence(
        self,
        incident: FMEAIncident,
        conn: Connection | None = None,
    ) -> None:
        """Record occurrence for future O calculations."""
        if not self._pool and not conn:
            return

        async with (conn or self._pool.acquire()) as c:
            await c.execute(
                """
                INSERT INTO fmea_occurrences (failure_mode_id, endpoint, context, occurred_at)
                VALUES ($1, $2, $3, $4)
                """,
                incident.failure_mode_id,
                incident.endpoint,
                incident.context,
                incident.detected_at,
            )

    def clear_cache(self) -> None:
        """Clear the failure mode cache."""
        self._catalog_cache.clear()

    async def get_heuristics_for_failure_mode(
        self,
        failure_mode_id: str,
    ) -> dict[str, Any]:
        """Get KB heuristics relevant to a failure mode.

        Maps failure modes to KB heuristic paths and retrieves them.
        This integrates the existing KB heuristics as FMEA controls.

        Args:
            failure_mode_id: Failure mode ID (e.g., GPU_001)

        Returns:
            Dict with heuristic content including:
            - symptom, cause, observation, solution
            - automation_level
            - observable_patterns
        """
        # Map failure modes to heuristic paths
        FMEA_TO_HEURISTIC: dict[str, str] = {
            # GPU failures
            "GPU_001": "current/heuristics/gaius/inference/gpu_memory_exhausted.md",
            "GPU_002": "current/heuristics/gaius/inference/gpu_temperature.md",

            # vLLM failures
            "VLLM_001": "current/heuristics/gaius/inference/endpoint_stuck.md",
            "VLLM_002": "current/heuristics/gaius/inference/endpoint_stuck.md",
            "VLLM_003": "current/heuristics/gaius/inference/endpoint_unhealthy.md",
            "VLLM_004": "current/heuristics/gaius/inference/stale_vllm_processes.md",
            "VLLM_005": "current/heuristics/gaius/inference/gpu_memory_exhausted.md",

            # Infrastructure
            "INFRA_001": "current/heuristics/gaius/engine/grpc_connection_stale.md",
            "INFRA_002": "current/heuristics/gaius/data/database_connection.md",

            # Cognition/Evolution
            "EB_002": "current/heuristics/gaius/cognition/cognition_loop.md",
            "EV_002": "current/heuristics/gaius/evolution/training_divergence.md",
        }

        heuristic_path = FMEA_TO_HEURISTIC.get(failure_mode_id)
        if not heuristic_path:
            return {"found": False, "reason": f"No heuristic mapped for {failure_mode_id}"}

        try:
            from pathlib import Path

            kb_root = Path("build/dev")
            heuristic_file = kb_root / heuristic_path

            if not heuristic_file.exists():
                return {"found": False, "reason": f"Heuristic file not found: {heuristic_path}"}

            content = heuristic_file.read_text()

            # Parse the markdown structure
            result = {
                "found": True,
                "path": heuristic_path,
                "raw_content": content,
            }

            # Extract sections
            sections = ["Symptom", "Cause", "Observation", "Solution"]
            for section in sections:
                start_marker = f"## {section}"
                if start_marker in content:
                    start_idx = content.index(start_marker) + len(start_marker)
                    # Find next section or end
                    end_idx = len(content)
                    for next_section in sections:
                        next_marker = f"## {next_section}"
                        if next_marker in content[start_idx:]:
                            candidate = content.index(next_marker, start_idx)
                            if candidate < end_idx:
                                end_idx = candidate
                    result[section.lower()] = content[start_idx:end_idx].strip()

            # Extract automation level from Observation section
            observation = result.get("observation", "")
            if "Automation Level: A" in observation:
                result["automation_level"] = "A"
                result["automation_description"] = "Full Automation"
            elif "Automation Level: B" in observation:
                result["automation_level"] = "B"
                result["automation_description"] = "Partial Automation"
            elif "Automation Level: C" in observation:
                result["automation_level"] = "C"
                result["automation_description"] = "Knowledge Transfer"
            else:
                result["automation_level"] = "unknown"

            logger.debug(f"Loaded heuristic for {failure_mode_id}: {heuristic_path}")
            return result

        except Exception as e:
            logger.warning(f"Failed to load heuristic for {failure_mode_id}: {e}")
            return {"found": False, "reason": str(e)}

    async def get_controls_from_heuristic(
        self,
        failure_mode_id: str,
    ) -> dict[str, list[str]]:
        """Extract FMEA controls from KB heuristic.

        Maps heuristic sections to FMEA control categories:
        - Preventive Controls: Prevention section
        - Detective Controls: Observation section (signals)
        - Mitigative Controls: Solution section (remediation steps)

        Args:
            failure_mode_id: Failure mode ID

        Returns:
            Dict with preventive, detective, mitigative control lists
        """
        heuristic = await self.get_heuristics_for_failure_mode(failure_mode_id)

        if not heuristic.get("found"):
            return {
                "preventive": [],
                "detective": [],
                "mitigative": [],
            }

        controls = {
            "preventive": [],
            "detective": [],
            "mitigative": [],
        }

        # Extract detective controls from Observation (signals)
        observation = heuristic.get("observation", "")
        if "Signals:" in observation:
            signals_section = observation.split("Signals:")[1]
            # Parse bulleted list
            for line in signals_section.split("\n"):
                line = line.strip()
                if line.startswith("- "):
                    controls["detective"].append(line[2:])

        # Extract mitigative controls from Solution (remediation)
        solution = heuristic.get("solution", "")
        if "Remediation:" in solution:
            remediation = solution.split("Remediation:")[1]
            # Parse numbered or bulleted list
            for line in remediation.split("\n"):
                line = line.strip()
                if line and (line[0].isdigit() or line.startswith("- ")):
                    # Clean up the line
                    if line[0].isdigit():
                        line = line.lstrip("0123456789.").strip()
                    elif line.startswith("- "):
                        line = line[2:]
                    if line and not line.startswith("```"):
                        controls["mitigative"].append(line)

        # Extract preventive controls from Prevention section if present
        if "Prevention:" in solution:
            prevention = solution.split("Prevention:")[1]
            if "**" in prevention:  # Stop at next bold section
                prevention = prevention.split("**")[0]
            for line in prevention.split("\n"):
                line = line.strip()
                if line and not line.startswith("```"):
                    controls["preventive"].append(line)

        return controls
