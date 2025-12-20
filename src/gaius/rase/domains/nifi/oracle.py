"""NiFi Oracle for RLVR reward computation.

The NiFi Oracle is the domain-specific verification oracle that uses
the NiFi REST API to provide ground-truth verification of agent actions.

Implements the generic Oracle[S] interface from gaius.rase.core,
parameterized with NiFiInstance as the state type.

Key concepts:
- Oracle: Provides authoritative verification using API (not UI)
- RewardStrategy: Converts verification results to training rewards
- Curriculum: Progressive training from easy to hard scenarios
"""

from __future__ import annotations

from typing import Any

from gaius.rase.core import (
    Oracle as GenericOracle,
    RewardStrategy,
    GradedReward,
    VerificationResult,
    VerificationCase,
    VerdictKind,
    ConstraintResult,
)
from gaius.rase.traceability import TraceableId

from .state import NiFiInstance, ProcessorGroup
from .constraints import Constraint


class NiFiOracle(GenericOracle[NiFiInstance]):
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
        """Fetch current NiFi state via API.

        Required by Oracle[NiFiInstance] interface.

        Returns:
            Current NiFiInstance state snapshot

        Raises:
            ValueError: If NiFi client not configured
            NotImplementedError: Pending client integration
        """
        if self.nifi_client is None:
            raise ValueError("NiFi client not configured")

        # This would use the actual NiFi client to fetch state
        # For now, return a placeholder that would be replaced
        # with actual client integration
        raise NotImplementedError(
            "NiFi client integration pending. "
            "Use NiFiStateManager.capture_state() for actual state capture."
        )

    async def verify(
        self,
        case: VerificationCase[NiFiInstance],
        current_state: NiFiInstance | None = None,
        **kwargs: Any,
    ) -> VerificationResult:
        """Verify a case against NiFi state.

        Args:
            case: The verification case to execute
            current_state: Current NiFi state (if already captured)
            **kwargs: Additional context

        Returns:
            VerificationResult with detailed constraint results
        """
        # Get current state if not provided
        if current_state is None:
            current_state = await self.get_current_state()

        # Execute the case
        return await case.execute(current_state, **kwargs)

    async def verify_constraints(
        self,
        constraints: list[Constraint],
        state: NiFiInstance,
    ) -> VerificationResult:
        """Verify a list of constraints against state.

        Convenience method for direct constraint verification
        without requiring a full VerificationCase.

        Args:
            constraints: List of NiFi constraints to check
            state: NiFi state to verify against

        Returns:
            VerificationResult with all constraint results
        """
        results: list[ConstraintResult] = []
        failed_constraints: list[str] = []

        for constraint in constraints:
            result = constraint.evaluate(state)
            results.append(result)
            if not result.satisfied:
                failed_constraints.append(constraint.name)

        # Determine verdict
        all_passed = len(failed_constraints) == 0

        if all_passed:
            verdict = VerdictKind.PASS
        elif results:
            verdict = VerdictKind.FAIL
        else:
            verdict = VerdictKind.INCONCLUSIVE

        # Compute accuracy for partial credit
        if results:
            passed_count = sum(1 for r in results if r.satisfied)
            accuracy = passed_count / len(results)
        else:
            accuracy = 0.0

        return VerificationResult(
            case_id=TraceableId.generate(scheme="rase", prefix="verify"),
            verdict=verdict,
            accuracy=accuracy,
            constraint_results=results,
            state_after_id=state.to_traceable_id(),
        )

    async def verify_transition(
        self,
        before: NiFiInstance,
        after: NiFiInstance,
        transition_constraints: list[Any],  # list[TransitionConstraint]
    ) -> VerificationResult:
        """Verify a state transition.

        Checks transition constraints that compare before/after states.

        Args:
            before: State before the action
            after: State after the action
            transition_constraints: Transition constraints to check

        Returns:
            VerificationResult for the transition
        """
        results: list[ConstraintResult] = []

        for constraint in transition_constraints:
            result = constraint.evaluate(before, after)
            results.append(result)

        # Determine verdict
        all_passed = all(r.satisfied for r in results)

        if all_passed:
            verdict = VerdictKind.PASS
        elif results:
            verdict = VerdictKind.FAIL
        else:
            verdict = VerdictKind.INCONCLUSIVE

        # Compute accuracy
        if results:
            passed_count = sum(1 for r in results if r.satisfied)
            accuracy = passed_count / len(results)
        else:
            accuracy = 0.0

        return VerificationResult(
            case_id=TraceableId.generate(scheme="rase", prefix="transition"),
            verdict=verdict,
            accuracy=accuracy,
            constraint_results=results,
            state_before_id=before.to_traceable_id(),
            state_after_id=after.to_traceable_id(),
        )


class CurriculumNiFiOracle(NiFiOracle):
    """NiFi Oracle with curriculum learning support.

    Tracks training progress and adjusts difficulty over time.
    Enables progressive training from easy to hard scenarios.

    Attributes:
        difficulty_level: Current curriculum difficulty (0-1)
    """

    def __init__(
        self,
        nifi_client: Any = None,
        reward_strategy: RewardStrategy | None = None,
        initial_difficulty: float = 0.0,
    ):
        super().__init__(nifi_client, reward_strategy)
        self.difficulty_level = initial_difficulty
        self._completed_scenarios: set[str] = set()

    async def verify(
        self,
        case: VerificationCase[NiFiInstance],
        current_state: NiFiInstance | None = None,
        **kwargs: Any,
    ) -> VerificationResult:
        """Verify and track progress for curriculum."""
        result = await super().verify(case, current_state, **kwargs)

        # Track completed scenarios for curriculum progression
        if result.verdict == VerdictKind.PASS:
            self._completed_scenarios.add(str(case.id))

        return result

    def advance_difficulty(self, increment: float = 0.1) -> float:
        """Advance curriculum difficulty level."""
        self.difficulty_level = min(1.0, self.difficulty_level + increment)
        return self.difficulty_level

    def get_success_rate(self, total_scenarios: int) -> float:
        """Get proportion of scenarios completed."""
        if total_scenarios == 0:
            return 0.0
        return len(self._completed_scenarios) / total_scenarios

    @property
    def completed_count(self) -> int:
        """Number of scenarios completed."""
        return len(self._completed_scenarios)

    def reset_progress(self) -> None:
        """Reset curriculum progress."""
        self._completed_scenarios.clear()
        self.difficulty_level = 0.0


__all__ = [
    "NiFiOracle",
    "CurriculumNiFiOracle",
]
