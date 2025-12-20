"""Generic Verification Model for RASE.

Provides domain-agnostic verification infrastructure that can be
parameterized by any SystemState type. Each domain creates concrete
verification types by specifying their state type.

Key concepts:
- VerdictKind: PASS/FAIL/INCONCLUSIVE/ERROR outcomes
- VerificationResult: Domain-agnostic verification outcome with evidence
- VerificationCase[S]: Generic verification case parameterized by state
- Oracle[S]: Generic verification oracle
- RewardStrategy: Reward computation strategies for RLVR

Design principles:
1. Generic: Parameterized by state type S
2. Composable: Cases can be combined
3. Debuggable: Rich results with evidence links
4. RLVR-ready: Built-in reward computation

Example:
    # Define NiFi-specific oracle
    class NiFiOracle(Oracle[NiFiInstance]):
        async def get_current_state(self) -> NiFiInstance: ...
        async def verify(self, case, **kwargs) -> VerificationResult: ...

    # Define verification case
    case = VerificationCase[NiFiInstance](
        id=TraceableId.generate("rase", "verify"),
        name="Verify_CreateFlow",
        ...
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Generic

from pydantic import BaseModel, Field

from .state import S
from .constraints import ConstraintResult


class VerdictKind(str, Enum):
    """Outcome of a verification case.

    Mirrors SysML v2 VerdictKind:
    - PASS: All requirements satisfied
    - FAIL: One or more requirements not satisfied
    - INCONCLUSIVE: Could not determine (e.g., missing data)
    - ERROR: Verification itself failed (infrastructure issue)
    """

    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    ERROR = "error"

    def to_reward(self) -> float:
        """Convert verdict to basic reward value."""
        if self == VerdictKind.PASS:
            return 1.0
        elif self == VerdictKind.FAIL:
            return 0.0
        elif self == VerdictKind.INCONCLUSIVE:
            return 0.5
        else:  # ERROR
            return 0.0


class RewardStrategy(BaseModel, ABC):
    """Strategy for computing rewards from verification results.

    Different training objectives may require different reward shaping.
    This abstraction enables experimentation with reward functions.

    Maps to RLHF/RLVR reward model concepts but with verifiable
    (not learned) reward computation.
    """

    @abstractmethod
    def compute(self, result: "VerificationResult") -> float:
        """Compute reward from verification result.

        Args:
            result: The verification result

        Returns:
            Reward value (typically 0-1, but can be shaped)
        """
        ...


class BinaryReward(RewardStrategy):
    """Simple binary reward: 1.0 for pass, 0.0 for fail.

    Use for:
    - Initial training where partial credit might confuse
    - Tasks with clear pass/fail criteria
    - Evaluation (not training) metrics
    """

    def compute(self, result: "VerificationResult") -> float:
        if result.verdict == VerdictKind.PASS:
            return 1.0
        return 0.0


class GradedReward(RewardStrategy):
    """Graded reward based on accuracy (partial credit).

    Use for:
    - Complex multi-step tasks
    - Training where intermediate progress matters
    - Scenarios with many requirements

    Attributes:
        pass_bonus: Additional reward for full success
        fail_penalty: Penalty for complete failure
        inconclusive_value: Value for inconclusive results
    """

    pass_bonus: float = 0.1  # Extra reward for PASS
    fail_penalty: float = 0.0  # No penalty beyond accuracy
    inconclusive_value: float = 0.5

    def compute(self, result: "VerificationResult") -> float:
        if result.verdict == VerdictKind.PASS:
            return min(1.0, result.accuracy + self.pass_bonus)
        elif result.verdict == VerdictKind.FAIL:
            return max(0.0, result.accuracy - self.fail_penalty)
        elif result.verdict == VerdictKind.INCONCLUSIVE:
            return self.inconclusive_value
        else:  # ERROR
            return 0.0


class VerificationObjective(BaseModel):
    """Specification of what a verification case verifies.

    Maps to SysML v2:
        objective { verify requirement1; verify requirement2; }

    Attributes:
        requirement_ids: IDs of requirements being verified
        partial_credit: Whether to give partial credit for partial satisfaction
    """

    # Use forward reference to avoid circular import with TraceableId
    requirement_ids: list[Any]  # list[TraceableId]
    partial_credit: bool = True

    model_config = {"frozen": True}


class VerificationResult(BaseModel):
    """Result of executing a verification case.

    Contains the verdict, evidence, and details for debugging.
    This is the domain-agnostic result type.

    Attributes:
        id: Unique result identifier
        case_id: ID of the verification case
        verdict: The outcome (PASS/FAIL/INCONCLUSIVE/ERROR)
        accuracy: Proportion of constraints satisfied (0-1)
        constraint_results: Results from individual constraints
        failed_requirements: IDs of requirements that failed
        timestamp: When verification completed
        duration_ms: How long verification took

    Evidence links:
        - state_before_id: State before execution
        - state_after_id: State after execution
        - trace_id: Trace if UI verification
    """

    id: Any = None  # TraceableId - set via default_factory
    case_id: Any  # TraceableId
    verdict: VerdictKind
    accuracy: float = 0.0

    # Detailed results
    constraint_results: list[ConstraintResult] = Field(default_factory=list)
    failed_requirements: list[Any] = Field(default_factory=list)  # list[TraceableId]

    # Timing
    timestamp: datetime = Field(default_factory=datetime.now)
    duration_ms: int = 0

    # Evidence links
    state_before_id: Any | None = None  # TraceableId
    state_after_id: Any | None = None  # TraceableId
    trace_id: Any | None = None  # TraceableId

    # Error details
    error_message: str | None = None
    error_traceback: str | None = None

    model_config = {"frozen": True}

    @property
    def passed(self) -> bool:
        """Whether verification passed."""
        return self.verdict == VerdictKind.PASS

    @property
    def failed(self) -> bool:
        """Whether verification failed."""
        return self.verdict == VerdictKind.FAIL

    def to_reward(self) -> float:
        """Convert to training reward.

        Uses accuracy for partial credit if available,
        otherwise uses verdict-based binary reward.
        """
        if self.verdict == VerdictKind.PASS:
            return 1.0
        elif self.verdict == VerdictKind.FAIL:
            # Use accuracy for partial credit
            return self.accuracy
        elif self.verdict == VerdictKind.INCONCLUSIVE:
            return 0.5
        else:
            return 0.0


class VerificationCase(BaseModel, ABC, Generic[S]):
    """Base class for verification cases.

    A verification case defines what to verify and how. Subclasses
    implement specific verification strategies (API-based, UI-based).

    Type parameter S specifies what state type this case verifies against.

    Maps to SysML v2:
        verification def X {
            subject s : Type;
            objective { verify <requirements>; }
            return verdict : VerdictKind;
        }

    Attributes:
        id: Traceable identifier
        name: Human-readable name
        objective: What requirements are verified
        timeout_seconds: Maximum execution time
    """

    id: Any  # TraceableId
    name: str
    objective: VerificationObjective
    timeout_seconds: int = 300

    model_config = {"frozen": True}

    @abstractmethod
    async def execute(
        self,
        subject: S,
        **kwargs: Any,
    ) -> VerificationResult:
        """Execute the verification case.

        Args:
            subject: The system state to verify
            **kwargs: Additional execution context

        Returns:
            VerificationResult with verdict and evidence
        """
        ...


class Oracle(ABC, Generic[S]):
    """Base class for verification oracles.

    An Oracle provides ground-truth verification using authoritative
    sources (APIs, databases) rather than learned approximations.

    Type parameter S specifies what state type this oracle operates on.

    This is the key to RLVR: the reward comes from verifiable
    computation, not human feedback or learned reward models.

    Subclasses implement domain-specific verification logic.
    """

    def __init__(self, reward_strategy: RewardStrategy | None = None):
        self.reward_strategy = reward_strategy or GradedReward()

    @abstractmethod
    async def get_current_state(self) -> S:
        """Fetch current system state.

        Returns:
            Current state snapshot
        """
        ...

    @abstractmethod
    async def verify(
        self,
        case: VerificationCase[S],
        **kwargs: Any,
    ) -> VerificationResult:
        """Verify a case against current state.

        Args:
            case: The verification case to execute
            **kwargs: Additional context

        Returns:
            VerificationResult with verdict and evidence
        """
        ...

    def compute_reward(self, result: VerificationResult) -> float:
        """Compute training reward from verification result."""
        return self.reward_strategy.compute(result)

    async def verify_and_reward(
        self,
        case: VerificationCase[S],
        **kwargs: Any,
    ) -> tuple[VerificationResult, float]:
        """Verify case and compute reward in one call."""
        result = await self.verify(case, **kwargs)
        reward = self.compute_reward(result)
        return result, reward


def compute_reward(
    result: VerificationResult,
    strategy: RewardStrategy | None = None,
) -> float:
    """Convenience function for reward computation.

    Args:
        result: The verification result
        strategy: Reward strategy (defaults to GradedReward)

    Returns:
        Computed reward value
    """
    if strategy is None:
        strategy = GradedReward()
    return strategy.compute(result)


__all__ = [
    "VerdictKind",
    "RewardStrategy",
    "BinaryReward",
    "GradedReward",
    "VerificationObjective",
    "VerificationResult",
    "VerificationCase",
    "Oracle",
    "compute_reward",
]
