"""Health check system for Gaius.

This module provides comprehensive health diagnostics by applying
heuristics from the KB to detect issues and suggest interventions.

Also provides a tiered self-healing system:
- Tier 0: Procedural restart (code-only, no agents)
- Tier 1: Local agent intervention (using healthy endpoints)
- Tier 2: Remote API escalation (prepared remediation paths)
"""

from .checker import HealthChecker, HealthReport, HealthCheck, CheckResult, CheckStatus
from .heuristics import HeuristicLoader, Heuristic
from .self_healing import (
    SelfHealingCoordinator,
    HealthIssue,
    HealingResult,
    HealingState,
    HealingTier,
    HealingTierType,
    Tier0Procedural,
    Tier1LocalAgent,
    Tier2RemoteEscalation,
)

__all__ = [
    # Health checking
    "HealthChecker",
    "HealthReport",
    "HealthCheck",
    "CheckResult",
    "CheckStatus",
    "HeuristicLoader",
    "Heuristic",
    # Self-healing
    "SelfHealingCoordinator",
    "HealthIssue",
    "HealingResult",
    "HealingState",
    "HealingTier",
    "HealingTierType",
    "Tier0Procedural",
    "Tier1LocalAgent",
    "Tier2RemoteEscalation",
]
