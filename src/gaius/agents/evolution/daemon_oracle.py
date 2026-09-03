"""Daemon Oracle for intrinsic verification.

Provides the scoring interface for the evolution daemon using RASE
intrinsic verification. This replaces external model evaluation with
verifiable ground truth from the KB state.

Key principle: The operational environment (KB state) is the verification
oracle. We don't need frontier models to determine if a task succeeded -
we can check it directly against the objective's gates.

Architecture:
    Evolution Engine → Daemon Oracle → RASE KBOracle → KB State
                                ↓
                        Evidence Capture → HX Iceberg

Usage:
    oracle = DaemonOracle(kb_root="build/dev")

    # Score a trajectory using intrinsic verification
    score = await oracle.score_trajectory(trajectory, task)

    # Run full objective verification
    result = await oracle.verify_objective(objective_name, document_path)
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .engine import TaskItem, Trajectory
from .objective_generator import ObjectiveTask
from gaius.core.budgets import REASONING_MAX_TOKENS

logger = logging.getLogger(__name__)


@dataclass
class VerificationScore:
    """Score from intrinsic verification.

    Combines gate results with reasoning quality assessment.
    """

    # Core verification result
    verdict: str  # pass, fail, inconclusive, error
    accuracy: float  # 0.0-1.0 gate accuracy
    reward: float  # Computed reward for training

    # Breakdown
    gates_total: int
    gates_passed: int
    gate_scores: dict[str, bool]

    # Reasoning quality (from local model assessment)
    reasoning_quality: float = 0.0
    reasoning_complete: bool = False

    # Combined score
    @property
    def final_score(self) -> float:
        """Compute final score combining accuracy and reasoning."""
        # 60% gate accuracy, 40% reasoning quality
        return 0.6 * self.accuracy + 0.4 * self.reasoning_quality


class DaemonOracle:
    """Intrinsic verification oracle for evolution daemon.

    Provides scoring for agent outputs using RASE verification
    instead of external model evaluation. This enables:

    1. Verifiable rewards - objective gates provide ground truth
    2. Fast scoring - no external API calls needed
    3. Training signal - evidence captured for learning
    4. Audit trail - full digital thread for each verification

    The oracle uses the KB domain's verification infrastructure
    but adds daemon-specific scoring logic.
    """

    def __init__(
        self,
        kb_root: str = "build/dev",
        capture_evidence: bool = True,
        use_local_reasoning: bool = True,
    ):
        """Initialize the daemon oracle.

        Args:
            kb_root: KB root directory
            capture_evidence: Whether to capture evidence to HX
            use_local_reasoning: Whether to assess reasoning quality locally
        """
        self.kb_root = kb_root
        self.capture_evidence = capture_evidence
        self.use_local_reasoning = use_local_reasoning
        self._kb_oracle = None  # Lazy-loaded

    @property
    def kb_oracle(self):
        """Get the KB oracle (lazy load)."""
        if self._kb_oracle is None:
            from gaius.rase.domains.kb import KBOracle
            self._kb_oracle = KBOracle(
                kb_root=self.kb_root,
                use_minio=self.capture_evidence,
            )
        return self._kb_oracle

    async def score_trajectory(
        self,
        trajectory: Trajectory,
        task: TaskItem,
    ) -> float:
        """Score a trajectory using intrinsic verification.

        This is the main scoring method called by the evolution engine.
        For objective tasks, uses RASE verification. For other tasks,
        falls back to local model assessment.

        Args:
            trajectory: Agent execution trajectory
            task: Original task item

        Returns:
            Score between 0.0 and 1.0
        """
        # Check if this is an objective task
        if task.context and task.context.startswith("objective:"):
            objective_name = task.context.split(":", 1)[1]
            return await self._score_objective_task(
                trajectory=trajectory,
                task=task,
                objective_name=objective_name,
            )
        else:
            # Non-objective task - use local model assessment
            return await self._score_generic_task(trajectory, task)

    async def _score_objective_task(
        self,
        trajectory: Trajectory,
        task: TaskItem,
        objective_name: str,
    ) -> float:
        """Score an objective verification task.

        Uses RASE verification to score the agent's output.
        The agent is evaluated on:
        1. Whether their assessment matches actual gate results
        2. Quality of their reasoning/explanation

        Args:
            trajectory: Agent execution trajectory
            task: Original task item
            objective_name: Name of objective being verified

        Returns:
            Score between 0.0 and 1.0
        """
        start_time = time.time()

        try:
            # Load the objective
            from gaius.rase.domains.kb import Objective

            objective = Objective.from_file(
                f"current/objectives/{objective_name}.md",
                kb_root=self.kb_root,
            )

            # Extract document path from task if present
            document_path = None
            if "document at '" in task.prompt:
                # Parse document path from prompt
                import re
                match = re.search(r"document at '([^']+)'", task.prompt)
                if match:
                    document_path = match.group(1)

            # Run verification
            if self.capture_evidence:
                result, thread = await self.kb_oracle.verify_objective_with_evidence(
                    objective=objective,
                    document_path=document_path,
                )
            else:
                result = await self.kb_oracle.verify_objective(
                    objective=objective,
                    document_path=document_path,
                )

            # Compare agent output with verification result
            verification_score = self._compute_verification_score(
                agent_output=trajectory.output,
                result=result,
            )

            # Assess reasoning quality if enabled
            if self.use_local_reasoning:
                reasoning_quality = await self._assess_reasoning_quality(
                    agent_output=trajectory.output,
                    objective=objective,
                    result=result,
                )
                verification_score.reasoning_quality = reasoning_quality

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(
                f"Objective task scored: {objective_name} -> {verification_score.final_score:.2f} "
                f"(gates={verification_score.gates_passed}/{verification_score.gates_total}, "
                f"reasoning={verification_score.reasoning_quality:.2f}, "
                f"duration={duration_ms}ms)"
            )

            return verification_score.final_score

        except Exception as e:
            logger.error(f"Objective scoring failed: {e}")
            return 0.0

    def _compute_verification_score(
        self,
        agent_output: str,
        result,  # VerificationResult
    ) -> VerificationScore:
        """Compute verification score from agent output and result.

        Analyzes how well the agent's assessment matches the actual
        verification outcome.

        Args:
            agent_output: Agent's verification assessment
            result: Actual verification result from oracle

        Returns:
            VerificationScore with breakdown
        """
        # Extract gate scores
        gate_scores = {}
        for cr in result.constraint_results:
            gate_scores[cr.constraint_name] = cr.satisfied

        # Check if agent correctly identified pass/fail
        agent_says_pass = any([
            "pass" in agent_output.lower()[:500],
            "satisfied" in agent_output.lower()[:500],
            "[ok]" in agent_output.lower()[:500],
        ])
        agent_says_fail = any([
            "fail" in agent_output.lower()[:500],
            "not satisfied" in agent_output.lower()[:500],
            "[fail]" in agent_output.lower()[:500],
        ])

        actual_pass = result.verdict.value == "pass"

        # Accuracy based on correct verdict identification
        verdict_accuracy = 1.0 if (agent_says_pass == actual_pass) else 0.0

        # Check if agent mentioned each gate correctly
        gate_mention_accuracy = 0.0
        gates_mentioned = 0
        for gate_name, gate_passed in gate_scores.items():
            # Check if agent mentioned this gate
            if gate_name.lower() in agent_output.lower():
                gates_mentioned += 1
                # Check if agent correctly identified gate status
                gate_context = agent_output.lower().split(gate_name.lower())[1][:200]
                agent_says_gate_pass = "pass" in gate_context or "[ok]" in gate_context
                if agent_says_gate_pass == gate_passed:
                    gate_mention_accuracy += 1

        if gates_mentioned > 0:
            gate_mention_accuracy /= len(gate_scores)
        else:
            gate_mention_accuracy = 0.0  # Agent didn't mention any gates

        # Combined accuracy
        accuracy = 0.5 * verdict_accuracy + 0.5 * gate_mention_accuracy

        return VerificationScore(
            verdict=result.verdict.value,
            accuracy=accuracy,
            reward=result.to_reward(),
            gates_total=len(result.constraint_results),
            gates_passed=sum(1 for g in gate_scores.values() if g),
            gate_scores=gate_scores,
            reasoning_complete=gates_mentioned > 0,
        )

    async def _assess_reasoning_quality(
        self,
        agent_output: str,
        objective,  # Objective
        result,  # VerificationResult
    ) -> float:
        """Assess the quality of agent's reasoning.

        Uses local model to evaluate how well the agent explained
        the verification process.

        Args:
            agent_output: Agent's output
            objective: Objective being verified
            result: Actual verification result

        Returns:
            Quality score 0.0-1.0
        """
        try:
            # Use optillm for fast local assessment
            from gaius.client.engine_client import ask_local

            assessment_prompt = f"""Rate the quality of this verification assessment.

OBJECTIVE: {objective.name}
ACTUAL RESULT: {result.verdict.value} (accuracy: {result.accuracy:.2%})

AGENT OUTPUT:
{agent_output[:2000]}

Rate on a scale of 0-10:
- Clarity (0-3): Is the reasoning clear and well-organized?
- Accuracy (0-4): Does the assessment match the actual result?
- Completeness (0-3): Are all gates addressed?

Respond with just a JSON object: {{"clarity": N, "accuracy": N, "completeness": N}}"""

            response = await ask_local(assessment_prompt, max_tokens=REASONING_MAX_TOKENS)

            # Parse response
            import json
            import re

            json_match = re.search(r'\{[^}]+\}', response)
            if json_match:
                scores = json.loads(json_match.group())
                quality = (
                    scores.get("clarity", 0) / 3 * 0.3 +
                    scores.get("accuracy", 0) / 4 * 0.5 +
                    scores.get("completeness", 0) / 3 * 0.2
                )
                return min(1.0, max(0.0, quality))

            return 0.5  # Default if parsing fails

        except Exception as e:
            logger.debug(f"Reasoning assessment failed: {e}")
            return 0.5  # Default

    async def _score_generic_task(
        self,
        trajectory: Trajectory,
        task: TaskItem,
    ) -> float:
        """Score a generic (non-objective) task.

        Falls back to local model assessment when no intrinsic
        verification is available.

        Args:
            trajectory: Agent execution trajectory
            task: Original task item

        Returns:
            Score between 0.0 and 1.0
        """
        try:
            from gaius.client.engine_client import ask_local

            assessment_prompt = f"""Rate the quality of this task completion.

TASK: {task.prompt[:1000]}

OUTPUT:
{trajectory.output[:2000]}

Rate on a scale of 0-10:
- Relevance (0-4): Does the output address the task?
- Quality (0-4): Is the response well-formed and useful?
- Completeness (0-2): Is the task fully completed?

Respond with just a JSON object: {{"relevance": N, "quality": N, "completeness": N}}"""

            response = await ask_local(assessment_prompt, max_tokens=REASONING_MAX_TOKENS)

            # Parse response
            import json
            import re

            json_match = re.search(r'\{[^}]+\}', response)
            if json_match:
                scores = json.loads(json_match.group())
                quality = (
                    scores.get("relevance", 0) / 4 * 0.4 +
                    scores.get("quality", 0) / 4 * 0.4 +
                    scores.get("completeness", 0) / 2 * 0.2
                )
                return min(1.0, max(0.0, quality))

            return 0.5  # Default if parsing fails

        except Exception as e:
            logger.debug(f"Generic assessment failed: {e}")
            return 0.5  # Default

    async def verify_objective(
        self,
        objective_name: str,
        document_path: str | None = None,
    ) -> VerificationScore:
        """Run full objective verification.

        Direct access to verification without trajectory context.
        Useful for testing and debugging.

        Args:
            objective_name: Name of objective to verify
            document_path: Optional document to verify against

        Returns:
            VerificationScore with full breakdown
        """
        from gaius.rase.domains.kb import Objective

        objective = Objective.from_file(
            f"current/objectives/{objective_name}.md",
            kb_root=self.kb_root,
        )

        if self.capture_evidence:
            result, _ = await self.kb_oracle.verify_objective_with_evidence(
                objective=objective,
                document_path=document_path,
            )
        else:
            result = await self.kb_oracle.verify_objective(
                objective=objective,
                document_path=document_path,
            )

        # Build gate scores
        gate_scores = {}
        for cr in result.constraint_results:
            gate_scores[cr.constraint_name] = cr.satisfied

        return VerificationScore(
            verdict=result.verdict.value,
            accuracy=result.accuracy,
            reward=result.to_reward(),
            gates_total=len(result.constraint_results),
            gates_passed=sum(1 for g in gate_scores.values() if g),
            gate_scores=gate_scores,
        )


# Singleton instance
_daemon_oracle: DaemonOracle | None = None


def get_daemon_oracle(
    kb_root: str | None = None,
    capture_evidence: bool = True,
) -> DaemonOracle:
    """Get or create the daemon oracle singleton.

    Args:
        kb_root: KB root (only used on first call)
        capture_evidence: Whether to capture evidence to HX

    Returns:
        DaemonOracle instance
    """
    global _daemon_oracle
    if _daemon_oracle is None:
        kb_root = kb_root or "build/dev"
        _daemon_oracle = DaemonOracle(
            kb_root=kb_root,
            capture_evidence=capture_evidence,
        )
    return _daemon_oracle


__all__ = [
    "VerificationScore",
    "DaemonOracle",
    "get_daemon_oracle",
]
