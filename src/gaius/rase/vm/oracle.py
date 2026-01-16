"""Oracle definitions for RLVR reward computation.

The Oracle is the key component that enables RLVR (Reinforcement Learning
with Verifiable Reward). It provides ground-truth verification of agent
actions against requirements.

Maps to SysML v2 concept of verification as a first-class concern:
    The verifier is not just a test—it's a safety-critical artifact that
    must be specified, reviewed, tested, and versioned.

Key concepts:
- Oracle: Provides authoritative verification using API (not UI)
- RewardStrategy: Converts verification results to training rewards
- RewardShaping: Adjusts rewards based on trajectory characteristics

The Oracle pattern enables:
1. Automated verification: No human in the loop for reward
2. Graded feedback: Partial credit for partial success
3. Curriculum learning: Progressively harder scenarios
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel, Field

from gaius.rase.traceability import TraceableId, DigitalThread, IdScheme
from gaius.rase.ssm import NiFiInstance, Constraint, ConstraintResult
from gaius.rase.uom import TraceOfMarks, ScreenshotWithSoM
from .requirements import ScenarioRequirement, StepRequirement
from .verification import (
    VerdictKind,
    VerificationCase,
    APIVerificationCase,
    UIVerificationCase,
    VerificationResult,
)


class RewardStrategy(BaseModel, ABC):
    """Strategy for computing rewards from verification results.

    Different training objectives may require different reward shaping.
    This abstraction enables experimentation with reward functions.

    Maps to RLHF/RLVR reward model concepts but with verifiable
    (not learned) reward computation.
    """

    @abstractmethod
    def compute(self, result: VerificationResult) -> float:
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

    def compute(self, result: VerificationResult) -> float:
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

    def compute(self, result: VerificationResult) -> float:
        if result.verdict == VerdictKind.PASS:
            return min(1.0, result.accuracy + self.pass_bonus)
        elif result.verdict == VerdictKind.FAIL:
            return max(0.0, result.accuracy - self.fail_penalty)
        elif result.verdict == VerdictKind.INCONCLUSIVE:
            return self.inconclusive_value
        else:  # ERROR
            return 0.0


class StepwiseReward(RewardStrategy):
    """Reward based on step-by-step progress.

    Provides dense rewards by evaluating each step, not just
    the final state. Better for learning long sequences.

    Attributes:
        step_weight: Weight per successful step
        completion_bonus: Bonus for completing all steps
        order_penalty: Penalty for out-of-order execution
    """

    step_weight: float = 0.1
    completion_bonus: float = 0.3
    order_penalty: float = 0.05

    # Step results (filled during computation)
    step_results: list[tuple[TraceableId, bool]] = Field(default_factory=list)

    def compute(self, result: VerificationResult) -> float:
        # Use accuracy as base (proportion of constraints passed)
        base_reward = result.accuracy

        # Add completion bonus if all passed
        if result.verdict == VerdictKind.PASS:
            base_reward += self.completion_bonus

        return min(1.0, base_reward)


class TrajectoryShaping(RewardStrategy):
    """Reward shaping based on trajectory characteristics.

    Considers not just outcome but how the agent got there:
    - Efficiency (fewer steps is better)
    - Directness (no unnecessary detours)
    - Safety (no constraint violations along the way)

    Attributes:
        efficiency_weight: Weight for step efficiency
        optimal_steps: Expected number of steps (for efficiency calc)
        violation_penalty: Penalty per constraint violation
    """

    efficiency_weight: float = 0.1
    optimal_steps: int = 10
    violation_penalty: float = 0.1

    def compute(self, result: VerificationResult) -> float:
        base_reward = result.accuracy

        if result.verdict == VerdictKind.PASS:
            base_reward = 1.0

        # Could add efficiency bonus based on trace length
        # (would need trace info passed in result)

        return base_reward


class Oracle(ABC):
    """Base class for verification oracles.

    An Oracle provides ground-truth verification using authoritative
    sources (APIs, databases) rather than learned approximations.

    This is the key to RLVR: the reward comes from verifiable
    computation, not human feedback or learned reward models.

    Subclasses implement domain-specific verification logic.
    """

    def __init__(self, reward_strategy: RewardStrategy | None = None):
        self.reward_strategy = reward_strategy or GradedReward()

    @abstractmethod
    async def verify(
        self,
        scenario: ScenarioRequirement,
        trace: TraceOfMarks | None = None,
        **kwargs: Any,
    ) -> VerificationResult:
        """Verify a scenario execution.

        Args:
            scenario: The scenario requirement to verify
            trace: Optional UI action trace
            **kwargs: Additional context (e.g., current state)

        Returns:
            VerificationResult with verdict and evidence
        """
        ...

    def compute_reward(self, result: VerificationResult) -> float:
        """Compute training reward from verification result."""
        return self.reward_strategy.compute(result)

    async def verify_and_reward(
        self,
        scenario: ScenarioRequirement,
        trace: TraceOfMarks | None = None,
        **kwargs: Any,
    ) -> tuple[VerificationResult, float]:
        """Verify scenario and compute reward in one call."""
        result = await self.verify(scenario, trace, **kwargs)
        reward = self.compute_reward(result)
        return result, reward


class NiFiOracle(Oracle):
    """Oracle for NiFi flow verification.

    Uses the NiFi REST API to verify flow state, providing
    ground-truth verification of agent actions.

    This is the primary oracle for MetaAgent training:
    1. Agent takes UI actions to modify NiFi
    2. Oracle queries NiFi API to check resulting state
    3. State is compared against scenario requirements
    4. Reward is computed from verification result

    Attributes:
        nifi_client: Client for NiFi API access
        capture_screenshots: Whether to capture before/after screenshots
    """

    def __init__(
        self,
        nifi_client: Any = None,  # NiFiClient from metaagent
        reward_strategy: RewardStrategy | None = None,
        capture_screenshots: bool = True,
    ):
        super().__init__(reward_strategy)
        self.nifi_client = nifi_client
        self.capture_screenshots = capture_screenshots

    async def get_current_state(self) -> NiFiInstance:
        """Fetch current NiFi state via API."""
        if self.nifi_client is None:
            raise ValueError("NiFi client not configured")

        # This would use the actual NiFi client to fetch state
        # For now, return a placeholder that would be replaced
        # with actual client integration
        from gaius.rase.ssm import ProcessorGroup

        # In practice, this calls:
        # flow = await self.nifi_client.get_process_group("root")
        # return NiFiInstance.from_api_response(flow)
        raise NotImplementedError(
            "NiFi client integration pending. "
            "Use NiFiStateManager.capture_state() for actual state capture."
        )

    async def verify(
        self,
        scenario: ScenarioRequirement,
        trace: TraceOfMarks | None = None,
        current_state: NiFiInstance | None = None,
        **kwargs: Any,
    ) -> VerificationResult:
        """Verify scenario against NiFi state.

        Args:
            scenario: The scenario requirement to verify
            trace: Optional UI action trace
            current_state: Current NiFi state (if already captured)
            **kwargs: Additional context

        Returns:
            VerificationResult with detailed constraint results
        """
        # Get current state if not provided
        if current_state is None:
            current_state = await self.get_current_state()

        # Create appropriate verification case
        if trace is not None:
            # UI verification (checks trace + final state)
            case = UIVerificationCase(
                id=TraceableId.generate(scheme=IdScheme.RASE, prefix="verify"),
                name=f"Verify_{scenario.name}",
                objective=VerificationObjective(
                    requirement_ids=[scenario.id],
                ),
                scenario_requirement=scenario,
            )
            return await case.execute(current_state, actual_trace=trace)
        else:
            # API-only verification
            case = APIVerificationCase(
                id=TraceableId.generate(scheme=IdScheme.RASE, prefix="verify"),
                name=f"Verify_{scenario.name}",
                objective=VerificationObjective(
                    requirement_ids=[scenario.id],
                ),
                scenario_requirement=scenario,
            )
            return await case.execute(current_state)

    async def verify_step(
        self,
        step: StepRequirement,
        state_before: NiFiInstance,
        state_after: NiFiInstance,
    ) -> ConstraintResult:
        """Verify a single step's transition.

        Useful for step-by-step verification during execution.
        """
        # Check assume constraints on before state
        for constraint in step.assume_constraints:
            result = constraint.evaluate(state_before)
            if not result.satisfied:
                return ConstraintResult(
                    constraint_name=str(step.id),
                    satisfied=False,
                    message=f"Precondition not met: {result.message}",
                )

        # Check require constraints on after state
        for constraint in step.require_constraints:
            result = constraint.evaluate(state_after)
            if not result.satisfied:
                return ConstraintResult(
                    constraint_name=str(step.id),
                    satisfied=False,
                    message=f"Postcondition not met: {result.message}",
                )

        # Check transition constraints
        for constraint in step.transition_constraints:
            result = constraint.evaluate(state_before, state_after)
            if not result.satisfied:
                return ConstraintResult(
                    constraint_name=str(step.id),
                    satisfied=False,
                    message=f"Transition failed: {result.message}",
                )

        return ConstraintResult(
            constraint_name=str(step.id),
            satisfied=True,
            message="Step verified successfully",
        )


# Import for type hints
from .verification import VerificationObjective


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


class CurriculumOracle(Oracle):
    """Oracle with curriculum learning support.

    Wraps another oracle and adjusts difficulty over time.
    Enables progressive training from easy to hard scenarios.

    Attributes:
        base_oracle: The underlying oracle
        difficulty_level: Current curriculum difficulty (0-1)
        scenarios_by_difficulty: Scenarios grouped by difficulty
    """

    def __init__(
        self,
        base_oracle: Oracle,
        initial_difficulty: float = 0.0,
    ):
        super().__init__(base_oracle.reward_strategy)
        self.base_oracle = base_oracle
        self.difficulty_level = initial_difficulty
        self._completed_scenarios: set[str] = set()

    async def verify(
        self,
        scenario: ScenarioRequirement,
        trace: TraceOfMarks | None = None,
        **kwargs: Any,
    ) -> VerificationResult:
        """Verify and track progress for curriculum."""
        result = await self.base_oracle.verify(scenario, trace, **kwargs)

        # Track completed scenarios for curriculum progression
        if result.verdict == VerdictKind.PASS:
            self._completed_scenarios.add(str(scenario.id))

        return result

    def advance_difficulty(self, increment: float = 0.1) -> float:
        """Advance curriculum difficulty level."""
        self.difficulty_level = min(1.0, self.difficulty_level + increment)
        return self.difficulty_level

    def get_success_rate(self) -> float:
        """Get proportion of scenarios completed."""
        # Would need total scenario count from curriculum config
        return len(self._completed_scenarios) / 100.0  # Placeholder


class EnsembleOracle(Oracle):
    """Ensemble of multiple oracles for robust verification.

    Combines results from multiple verification sources for
    higher confidence in verdicts.

    Attributes:
        oracles: List of oracles to consult
        voting_threshold: Proportion needed for PASS (0.5 = majority)
    """

    def __init__(
        self,
        oracles: list[Oracle],
        voting_threshold: float = 0.5,
        reward_strategy: RewardStrategy | None = None,
    ):
        super().__init__(reward_strategy)
        self.oracles = oracles
        self.voting_threshold = voting_threshold

    async def verify(
        self,
        scenario: ScenarioRequirement,
        trace: TraceOfMarks | None = None,
        **kwargs: Any,
    ) -> VerificationResult:
        """Verify using all oracles and combine results."""
        results: list[VerificationResult] = []

        for oracle in self.oracles:
            result = await oracle.verify(scenario, trace, **kwargs)
            results.append(result)

        # Count verdicts
        pass_count = sum(1 for r in results if r.verdict == VerdictKind.PASS)
        pass_rate = pass_count / len(results)

        # Combine results
        if pass_rate >= self.voting_threshold:
            combined_verdict = VerdictKind.PASS
        elif pass_rate == 0:
            combined_verdict = VerdictKind.FAIL
        else:
            combined_verdict = VerdictKind.INCONCLUSIVE

        # Average accuracy
        avg_accuracy = sum(r.accuracy for r in results) / len(results)

        # Combine constraint results
        all_constraints = []
        for r in results:
            all_constraints.extend(r.constraint_results)

        return VerificationResult(
            case_id=results[0].case_id if results else TraceableId.generate(
                scheme=IdScheme.RASE, prefix="ensemble"
            ),
            verdict=combined_verdict,
            accuracy=avg_accuracy,
            constraint_results=all_constraints,
        )


__all__ = [
    "RewardStrategy",
    "BinaryReward",
    "GradedReward",
    "StepwiseReward",
    "TrajectoryShaping",
    "Oracle",
    "NiFiOracle",
    "CurriculumOracle",
    "EnsembleOracle",
    "compute_reward",
]
