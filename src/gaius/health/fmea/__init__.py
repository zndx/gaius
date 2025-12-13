"""FMEA (Failure Mode and Effects Analysis) module for Gaius AIOps.

This module provides quantitative risk assessment using RPN (Risk Priority Number)
scoring to replace simple severity classifications with S×O×D calculations.

RPN = Severity × Occurrence × Detection (max 1000)

Thresholds:
- RPN < 100: Auto-remediate immediately (Tier 0)
- RPN 100-200: Auto-remediate with logging (Tier 1)
- RPN 200-400: Require approval (Tier 2)
- RPN > 400: Manual intervention required
"""

from .models import RPNScore, FailureMode, ActionPolicy, FMEAIncident, EscalationTier
from .engine import FMEAEngine
from .loader import HEALTH_CHECK_TO_FMEA, map_health_check_to_failure_mode
from .learning import AdaptiveLearner

__all__ = [
    "RPNScore",
    "FailureMode",
    "ActionPolicy",
    "FMEAIncident",
    "EscalationTier",
    "FMEAEngine",
    "AdaptiveLearner",
    "HEALTH_CHECK_TO_FMEA",
    "map_health_check_to_failure_mode",
]
