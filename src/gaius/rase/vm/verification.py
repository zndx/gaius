"""VM Verification case definitions.

Verification cases test requirements and produce verdicts. They are the
executable tests that verify agent behavior against specifications.

Maps to SysML v2:
    verification def Verify_X {
        subject nifi : NiFiInstance;
        objective { verify requirement_X; }
        return verdict : VerdictKind;
    }

Key concepts:
- VerificationCase: Definition of what to verify
- VerificationObjective: Which requirements are verified
- VerificationResult: Outcome with evidence
- VerdictKind: PASS/FAIL/INCONCLUSIVE/ERROR

There are two modes of verification:
- API verification: Uses NiFi API to check state (ground truth)
- UI verification: Uses agent's UI actions (what we're training)

The API verification provides the oracle for RLVR reward computation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from gaius.rase.traceability import TraceableId, IdScheme, DigitalThread
from gaius.rase.ssm import NiFiInstance, ConstraintResult
from gaius.rase.uom import TraceOfMarks
from .requirements import Requirement, ScenarioRequirement, StepRequirement


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
            return 0.0  # Treat errors as failures for training


class VerificationObjective(BaseModel):
    """Specification of what a verification case verifies.

    Maps to SysML v2:
        objective { verify requirement1; verify requirement2; }

    Attributes:
        requirement_ids: IDs of requirements being verified
        partial_credit: Whether to give partial credit for partial satisfaction
    """

    requirement_ids: list[TraceableId]
    partial_credit: bool = True

    model_config = {"frozen": True}


class VerificationCase(BaseModel, ABC):
    """Base class for verification cases.

    A verification case defines what to verify and how. Subclasses
    implement specific verification strategies (API-based, UI-based).

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

    id: TraceableId
    name: str
    objective: VerificationObjective
    timeout_seconds: int = 300

    model_config = {"frozen": True}

    @abstractmethod
    async def execute(
        self,
        subject: NiFiInstance,
        **kwargs: Any,
    ) -> "VerificationResult":
        """Execute the verification case.

        Args:
            subject: The system state to verify
            **kwargs: Additional execution context

        Returns:
            VerificationResult with verdict and evidence
        """
        ...


class APIVerificationCase(VerificationCase):
    """Verification case using API (ground truth).

    This is the oracle for RLVR: it checks system state via the
    NiFi REST API, providing authoritative verification.

    Attributes:
        scenario_requirement: The scenario being verified
        capture_state_before: Whether to capture state before
        capture_state_after: Whether to capture state after
    """

    scenario_requirement: ScenarioRequirement

    capture_state_before: bool = True
    capture_state_after: bool = True

    async def execute(
        self,
        subject: NiFiInstance,
        state_before: NiFiInstance | None = None,
        **kwargs: Any,
    ) -> "VerificationResult":
        """Execute API-based verification.

        Checks:
        1. Setup requirements (Given steps)
        2. End-state requirements (Then steps)
        3. Invariants
        """
        constraint_results: list[ConstraintResult] = []
        failed_requirements: list[TraceableId] = []

        # Verify setup (Given)
        for req in self.scenario_requirement.given_requirements:
            for constraint in req.require_constraints:
                result = constraint.evaluate(subject)
                constraint_results.append(result)
                if not result.satisfied:
                    failed_requirements.append(req.id)

        # Verify end state (Then)
        for req in self.scenario_requirement.then_requirements:
            for constraint in req.require_constraints:
                result = constraint.evaluate(subject)
                constraint_results.append(result)
                if not result.satisfied:
                    failed_requirements.append(req.id)

        # Verify end-state constraints
        for constraint in self.scenario_requirement.end_state_constraints:
            result = constraint.evaluate(subject)
            constraint_results.append(result)

        # Verify invariants
        for constraint in self.scenario_requirement.invariants:
            result = constraint.evaluate(subject)
            constraint_results.append(result)

        # Compute verdict
        all_passed = all(r.satisfied for r in constraint_results)

        if all_passed:
            verdict = VerdictKind.PASS
        elif constraint_results:
            verdict = VerdictKind.FAIL
        else:
            verdict = VerdictKind.INCONCLUSIVE

        # Compute accuracy for partial credit
        if constraint_results:
            passed_count = sum(1 for r in constraint_results if r.satisfied)
            accuracy = passed_count / len(constraint_results)
        else:
            accuracy = 0.0

        return VerificationResult(
            case_id=self.id,
            verdict=verdict,
            accuracy=accuracy,
            constraint_results=constraint_results,
            failed_requirements=failed_requirements,
            state_after_id=subject.to_traceable_id() if subject else None,
        )


class UIVerificationCase(VerificationCase):
    """Verification case using UI agent actions.

    This verifies that a UI agent can accomplish the scenario through
    UI interactions. The final state is still verified via API.

    Attributes:
        scenario_requirement: The scenario being verified
        expected_trace: Optional expected action trace for comparison
    """

    scenario_requirement: ScenarioRequirement
    expected_trace: TraceOfMarks | None = None

    async def execute(
        self,
        subject: NiFiInstance,
        actual_trace: TraceOfMarks | None = None,
        **kwargs: Any,
    ) -> "VerificationResult":
        """Execute UI-based verification.

        Verifies:
        1. Final state matches requirements (via API)
        2. Action trace completes successfully
        3. Optional: Action trace matches expected pattern
        """
        constraint_results: list[ConstraintResult] = []
        failed_requirements: list[TraceableId] = []

        # Verify final state via API (same as APIVerificationCase)
        for req in self.scenario_requirement.then_requirements:
            for constraint in req.require_constraints:
                result = constraint.evaluate(subject)
                constraint_results.append(result)
                if not result.satisfied:
                    failed_requirements.append(req.id)

        # Check trace success if provided
        trace_succeeded = actual_trace.succeeded if actual_trace else None

        # Compute verdict
        state_passed = all(r.satisfied for r in constraint_results)

        if state_passed and trace_succeeded:
            verdict = VerdictKind.PASS
        elif state_passed and trace_succeeded is None:
            # State is correct but no trace to verify
            verdict = VerdictKind.PASS
        elif not state_passed:
            verdict = VerdictKind.FAIL
        else:
            # State correct but trace failed
            verdict = VerdictKind.FAIL

        # Compute accuracy
        if constraint_results:
            passed_count = sum(1 for r in constraint_results if r.satisfied)
            accuracy = passed_count / len(constraint_results)
        else:
            accuracy = 1.0 if trace_succeeded else 0.0

        return VerificationResult(
            case_id=self.id,
            verdict=verdict,
            accuracy=accuracy,
            constraint_results=constraint_results,
            failed_requirements=failed_requirements,
            trace_id=actual_trace.id if actual_trace else None,
            state_after_id=subject.to_traceable_id() if subject else None,
        )


class VerificationResult(BaseModel):
    """Result of executing a verification case.

    Contains the verdict, evidence, and details for debugging.

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
        - state_before_id: SSM state before execution
        - state_after_id: SSM state after execution
        - trace_id: UOM trace if UI verification
        - screenshots: Captured screenshot IDs
    """

    id: TraceableId = Field(
        default_factory=lambda: TraceableId.generate(IdScheme.RASE, "result")
    )
    case_id: TraceableId
    verdict: VerdictKind
    accuracy: float = 0.0

    # Detailed results
    constraint_results: list[ConstraintResult] = Field(default_factory=list)
    failed_requirements: list[TraceableId] = Field(default_factory=list)

    # Timing
    timestamp: datetime = Field(default_factory=datetime.now)
    duration_ms: int = 0

    # Evidence links
    state_before_id: TraceableId | None = None
    state_after_id: TraceableId | None = None
    trace_id: TraceableId | None = None
    screenshots: list[TraceableId] = Field(default_factory=list)

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

    def to_digital_thread(
        self,
        requirement_id: TraceableId,
    ) -> DigitalThread:
        """Create a DigitalThread linking this result to a requirement."""
        thread = DigitalThread(
            requirement_id=requirement_id,
            verification_case_id=self.case_id,
            verification_result_id=self.id,
            api_state_before=self.state_before_id,
            api_state_after=self.state_after_id,
            reward_outcome=self.to_reward(),
        )

        if self.trace_id:
            thread.ui_screenshots.extend(self.screenshots)

        return thread


class VerificationRun(BaseModel):
    """A collection of verification case executions.

    Groups multiple verification results from a single test run,
    enabling aggregate analysis and reporting.

    Attributes:
        id: Unique run identifier
        name: Human-readable name
        results: Individual verification results
        start_time: When the run started
        end_time: When the run completed
    """

    id: TraceableId = Field(
        default_factory=lambda: TraceableId.generate(IdScheme.RASE, "run")
    )
    name: str = ""
    results: list[VerificationResult] = Field(default_factory=list)

    start_time: datetime = Field(default_factory=datetime.now)
    end_time: datetime | None = None

    # Environment info
    environment_id: str | None = None
    agent_id: str | None = None

    model_config = {"frozen": True}

    @property
    def total_count(self) -> int:
        return len(self.results)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.verdict == VerdictKind.PASS)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if r.verdict == VerdictKind.FAIL)

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return self.pass_count / self.total_count

    @property
    def average_accuracy(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.accuracy for r in self.results) / len(self.results)

    def summary(self) -> dict[str, Any]:
        """Generate summary statistics."""
        return {
            "run_id": str(self.id),
            "total": self.total_count,
            "passed": self.pass_count,
            "failed": self.fail_count,
            "pass_rate": self.pass_rate,
            "average_accuracy": self.average_accuracy,
            "duration_ms": (
                int((self.end_time - self.start_time).total_seconds() * 1000)
                if self.end_time else None
            ),
        }


__all__ = [
    "VerdictKind",
    "VerificationObjective",
    "VerificationCase",
    "APIVerificationCase",
    "UIVerificationCase",
    "VerificationResult",
    "VerificationRun",
]
