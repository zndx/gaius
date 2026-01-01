"""FMEA data models for RPN-based risk assessment.

This module defines the core data structures for Failure Mode and Effects Analysis:
- RPNScore: Risk Priority Number calculation result
- FailureMode: Failure mode catalog entry
- ActionPolicy: Remediation decision based on RPN
- FMEAIncident: Runtime failure mode incident
- AnalysisOrder: RCA abstraction ladder levels
- RCAObservation: Individual RCA observation at an abstraction level
- RCAResult: Complete RCA analysis result
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum
from typing import Any


class EscalationTier(IntEnum):
    """Remediation escalation tiers based on RPN."""
    TIER_0 = 0  # Auto-remediate immediately
    TIER_1 = 1  # Auto-remediate with agent validation
    TIER_2 = 2  # Require user approval
    MANUAL = 3  # Manual intervention required


class AnalysisOrder(IntEnum):
    """RCA abstraction ladder levels.

    Inspired by numerical PDE methods, RCA climbs from local to global understanding:
    - Order 0 (Euler): Symptom - What is the observable failure?
    - Order 1 (RK2): Immediate Cause - What action triggered the symptom?
    - Order 2 (RK4): Structural Cause - What configuration allowed this?
    - Order 3 (BDF/Implicit): Invariant Violation - What constraint was violated?
    - Order 4 (Spectral): Design Principle - How should the system be modeled?

    Higher-order observations connect symptoms to CP-SAT constraints in the scheduler.
    """
    SYMPTOM = 0
    IMMEDIATE_CAUSE = 1
    STRUCTURAL_CAUSE = 2
    INVARIANT = 3
    DESIGN_PRINCIPLE = 4


class RCAClassification(Enum):
    """Root cause classification determining next action.

    OPERATIONAL: Transient issue - close incident after remediation
    ARCHITECTURAL: Systemic issue - open GitHub issue for code fix
    """
    OPERATIONAL = "operational"
    ARCHITECTURAL = "architectural"


@dataclass
class RPNScore:
    """Risk Priority Number calculation result.

    RPN = Severity × Occurrence × Detection

    Attributes:
        severity: Impact on system availability (1-10, 10=catastrophic)
        occurrence: Probability of recurrence (1-10, 10=almost certain)
        detection: Ability to detect before impact (1-10, 10=no detection)
        rpn: Calculated RPN = S × O × D (1-1000)
        failure_mode_id: Link to FMEA catalog entry
        context_adjustments: Context that modified base scores
    """
    severity: int
    occurrence: int
    detection: int
    rpn: int
    failure_mode_id: str
    context_adjustments: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate scores and calculate RPN."""
        for name, value in [
            ("severity", self.severity),
            ("occurrence", self.occurrence),
            ("detection", self.detection),
        ]:
            if not 1 <= value <= 10:
                raise ValueError(f"{name} must be between 1 and 10, got {value}")

        expected_rpn = self.severity * self.occurrence * self.detection
        if self.rpn != expected_rpn:
            # Auto-calculate if not provided correctly
            object.__setattr__(self, "rpn", expected_rpn)

    @property
    def tier(self) -> EscalationTier:
        """Determine escalation tier from RPN."""
        if self.rpn <= 100:
            return EscalationTier.TIER_0
        elif self.rpn <= 200:
            return EscalationTier.TIER_1
        elif self.rpn <= 400:
            return EscalationTier.TIER_2
        else:
            return EscalationTier.MANUAL

    @property
    def requires_approval(self) -> bool:
        """Check if RPN requires user approval."""
        return self.tier >= EscalationTier.TIER_2

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "severity": self.severity,
            "occurrence": self.occurrence,
            "detection": self.detection,
            "rpn": self.rpn,
            "failure_mode_id": self.failure_mode_id,
            "tier": self.tier.name,
            "requires_approval": self.requires_approval,
            "context_adjustments": self.context_adjustments,
        }


@dataclass
class FailureMode:
    """Failure mode catalog entry.

    Attributes:
        failure_mode_id: Unique identifier (e.g., GPU_001, VLLM_002)
        category: Category (gpu, vllm, model_quality, evolution, emergent, resource, infra)
        name: Human-readable name
        description: Detailed description
        base_severity: Default severity score (1-10)
        base_occurrence: Default occurrence score (1-10)
        base_detection: Default detection score (1-10)
        detection_method: How this failure is detected
        recommended_actions: List of remediation actions
        escalation_tier: Default tier (can be overridden by RPN)
    """
    failure_mode_id: str
    category: str
    name: str
    description: str | None
    base_severity: int
    base_occurrence: int
    base_detection: int
    detection_method: str | None = None
    recommended_actions: list[str] = field(default_factory=list)
    escalation_tier: int = 0
    preventive_controls: list[str] = field(default_factory=list)
    detective_controls: list[str] = field(default_factory=list)
    mitigative_controls: list[str] = field(default_factory=list)

    @property
    def base_rpn(self) -> int:
        """Calculate base RPN from default scores."""
        return self.base_severity * self.base_occurrence * self.base_detection

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "failure_mode_id": self.failure_mode_id,
            "category": self.category,
            "name": self.name,
            "description": self.description,
            "base_severity": self.base_severity,
            "base_occurrence": self.base_occurrence,
            "base_detection": self.base_detection,
            "base_rpn": self.base_rpn,
            "detection_method": self.detection_method,
            "recommended_actions": self.recommended_actions,
            "escalation_tier": self.escalation_tier,
        }


@dataclass
class ActionPolicy:
    """Remediation action policy based on RPN assessment.

    Attributes:
        tier: Escalation tier (0, 1, 2, or MANUAL)
        requires_approval: Whether user approval is needed
        auto_execute: Whether remediation can proceed automatically
        manual_required: Whether manual intervention is required
        recommended_actions: Actions to take
        conservative_override: Reason for conservative escalation (e.g., low detection)
    """
    tier: EscalationTier
    requires_approval: bool
    auto_execute: bool
    manual_required: bool = False
    recommended_actions: list[str] = field(default_factory=list)
    conservative_override: str | None = None

    def with_override(self, reason: str) -> ActionPolicy:
        """Create a more conservative policy with an override reason."""
        return ActionPolicy(
            tier=max(self.tier, EscalationTier.TIER_2),
            requires_approval=True,
            auto_execute=False,
            manual_required=self.manual_required,
            recommended_actions=self.recommended_actions,
            conservative_override=reason,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "tier": self.tier.name,
            "tier_value": int(self.tier),
            "requires_approval": self.requires_approval,
            "auto_execute": self.auto_execute,
            "manual_required": self.manual_required,
            "recommended_actions": self.recommended_actions,
            "conservative_override": self.conservative_override,
        }


@dataclass
class FMEAIncident:
    """Runtime FMEA incident detected by a detector.

    Attributes:
        failure_mode_id: Link to FMEA catalog entry
        endpoint: Affected endpoint (if applicable)
        context: Detection context and metrics
        detected_at: When the incident was detected
        detected_by: Detection method (health_check, metric_threshold, anomaly, manual)
    """
    failure_mode_id: str
    endpoint: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    detected_at: datetime = field(default_factory=datetime.now)
    detected_by: str = "health_check"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "failure_mode_id": self.failure_mode_id,
            "endpoint": self.endpoint,
            "context": self.context,
            "detected_at": self.detected_at.isoformat(),
            "detected_by": self.detected_by,
        }


@dataclass
class RCAObservation:
    """Individual observation at an abstraction level in the RCA ladder.

    Attributes:
        order: Abstraction level (0=Symptom to 4=Design Principle)
        statement: The observation text
        evidence: Supporting evidence (log lines, metrics, etc.)
        confidence: Confidence in the observation (0.0-1.0)
        constraint_id: Link to CP-SAT constraint if Order 3+ (e.g., GPU_MUTUAL_EXCLUSION)
    """
    order: AnalysisOrder
    statement: str
    evidence: list[str] = field(default_factory=list)
    confidence: float = 1.0
    constraint_id: str | None = None

    def __post_init__(self) -> None:
        """Validate confidence range."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be 0.0-1.0, got {self.confidence}")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "order": self.order.value,
            "order_name": self.order.name,
            "statement": self.statement,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "constraint_id": self.constraint_id,
        }


@dataclass
class RCAResult:
    """Complete RCA analysis result.

    Determines whether an incident is operational (transient) or architectural
    (requires code changes), and captures observations across abstraction levels.

    Attributes:
        classification: OPERATIONAL or ARCHITECTURAL
        observations: Observations at each abstraction level reached
        highest_order_reached: Maximum abstraction level achieved
        constraint_violations: CP-SAT constraints identified as violated
        github_issue_needed: Whether to open a GitHub issue
        fix_location: File path for proposed fix (if architectural)
        proposed_fix: Description of the fix (if architectural)
        fingerprint: Incident fingerprint this RCA applies to
    """
    classification: RCAClassification
    observations: list[RCAObservation] = field(default_factory=list)
    highest_order_reached: AnalysisOrder = AnalysisOrder.SYMPTOM
    constraint_violations: list[dict[str, Any]] = field(default_factory=list)
    github_issue_needed: bool = False
    fix_location: str | None = None
    proposed_fix: str | None = None
    fingerprint: str | None = None

    def __post_init__(self) -> None:
        """Compute highest order from observations if not set."""
        if self.observations:
            max_order = max(obs.order for obs in self.observations)
            if max_order > self.highest_order_reached:
                object.__setattr__(self, "highest_order_reached", max_order)

    @property
    def is_architectural(self) -> bool:
        """Check if this is an architectural issue."""
        return self.classification == RCAClassification.ARCHITECTURAL

    @property
    def has_constraint_violations(self) -> bool:
        """Check if any CP-SAT constraints were violated."""
        return len(self.constraint_violations) > 0

    @property
    def avg_confidence(self) -> float:
        """Average confidence across all observations."""
        if not self.observations:
            return 0.0
        return sum(obs.confidence for obs in self.observations) / len(self.observations)

    def observations_by_order(self) -> dict[AnalysisOrder, list[RCAObservation]]:
        """Group observations by abstraction order."""
        result: dict[AnalysisOrder, list[RCAObservation]] = {}
        for obs in self.observations:
            if obs.order not in result:
                result[obs.order] = []
            result[obs.order].append(obs)
        return result

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "classification": self.classification.value,
            "observations": [obs.to_dict() for obs in self.observations],
            "highest_order_reached": self.highest_order_reached.value,
            "highest_order_name": self.highest_order_reached.name,
            "constraint_violations": self.constraint_violations,
            "github_issue_needed": self.github_issue_needed,
            "fix_location": self.fix_location,
            "proposed_fix": self.proposed_fix,
            "fingerprint": self.fingerprint,
            "avg_confidence": self.avg_confidence,
        }
