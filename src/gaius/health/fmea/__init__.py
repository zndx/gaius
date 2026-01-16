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

from .models import (
    RPNScore,
    FailureMode,
    ActionPolicy,
    FMEAIncident,
    EscalationTier,
    AnalysisOrder,
    RCAClassification,
    RCAObservation,
    RCAResult,
)
from .engine import FMEAEngine
from .loader import HEALTH_CHECK_TO_FMEA, map_health_check_to_failure_mode
from .learning import AdaptiveLearner
from .registry import (
    FMEA_REGISTRY,
    FMEAMapping,
    get_fmea_by_id,
    get_fmea_for_check,
    get_fmea_for_heuristic,
    get_heuristics_for_fmea,
    incident_matches_check,
)

__all__ = [
    # FMEA core
    "RPNScore",
    "FailureMode",
    "ActionPolicy",
    "FMEAIncident",
    "EscalationTier",
    # RCA (Root Cause Analysis)
    "AnalysisOrder",
    "RCAClassification",
    "RCAObservation",
    "RCAResult",
    # Engine and utilities
    "FMEAEngine",
    "AdaptiveLearner",
    "HEALTH_CHECK_TO_FMEA",
    "map_health_check_to_failure_mode",
    # Registry (consolidated mapping)
    "FMEA_REGISTRY",
    "FMEAMapping",
    "get_fmea_by_id",
    "get_fmea_for_check",
    "get_fmea_for_heuristic",
    "get_heuristics_for_fmea",
    "incident_matches_check",
]
