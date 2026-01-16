"""KB Oracle for intrinsic verification.

The KB Oracle implements the API-as-oracle pattern where the KB itself
serves as ground truth for verification. This enables autonomous
capability development without external labeling dependencies.

Key principle: The operational environment (KB state) is the verification
oracle. We don't need external annotators or frontier models to determine
if a verification passed - we can check it directly.

Usage:
    oracle = KBOracle(kb_root="build/dev")
    result = await oracle.verify_objective(objective)
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from gaius.rase.core.vm import (
    VerificationResult,
    VerdictKind,
    GradedReward,
)
from gaius.rase.core.constraints import Constraint, ConstraintResult
from gaius.rase.traceability import TraceableId, DigitalThread, IdScheme

from .state import KBState, KBDocument
from .objective import Objective, GateLevel
from .verification import (
    KBVerificationCase,
    objective_to_verification_case,
    create_digital_thread,
)
from .evidence import capture_verification_evidence

logger = logging.getLogger(__name__)


class KBOracle(BaseModel):
    """Oracle for KB verification using intrinsic ground truth.

    The KB Oracle provides:
    1. State capture from the KB filesystem
    2. Constraint verification against KB state
    3. Objective verification with gate progression
    4. Evidence recording for training pipeline

    The oracle never uses external models for verification - the KB
    state itself is the oracle. External models (Cerebras, XAI) are
    only used in the outer calibration loop.

    Attributes:
        kb_root: Root directory of the KB
        evidence_root: Where to store verification evidence
        use_minio: Whether to use MinIO for evidence storage
    """

    kb_root: str = "build/dev"
    evidence_root: str = "current/objectives/evidence"
    use_minio: bool = True
    _state_cache: KBState | None = None

    model_config = {"arbitrary_types_allowed": True}

    def get_current_state(self) -> KBState:
        """Capture current KB state from filesystem.

        Returns fresh state snapshot. Override for testing with mock state.
        """
        return KBState.capture(self.kb_root)

    def get_cached_state(self, max_age_seconds: float = 60.0) -> KBState:
        """Get cached state or refresh if stale."""
        if self._state_cache is None:
            self._state_cache = self.get_current_state()
        elif self._state_cache.is_stale(max_age_seconds):
            self._state_cache = self.get_current_state()
        return self._state_cache

    def invalidate_cache(self) -> None:
        """Invalidate state cache, forcing refresh on next access."""
        self._state_cache = None

    async def verify_constraints(
        self,
        constraints: list[Constraint[KBState]],
        state: KBState | None = None,
    ) -> VerificationResult:
        """Verify a list of constraints against KB state.

        Args:
            constraints: Constraints to verify
            state: Optional pre-captured state (captures fresh if None)

        Returns:
            VerificationResult with verdict and accuracy
        """
        if state is None:
            state = self.get_current_state()

        results = []
        for constraint in constraints:
            result = constraint.evaluate(state)
            results.append(result)

        # Compute overall verdict
        all_passed = all(r.satisfied for r in results)
        any_passed = any(r.satisfied for r in results)

        if all_passed:
            verdict = VerdictKind.PASS
        elif not any_passed:
            verdict = VerdictKind.FAIL
        else:
            verdict = VerdictKind.FAIL  # Partial = fail

        # Compute accuracy
        if not results:
            accuracy = 1.0
        else:
            accuracy = sum(1 for r in results if r.satisfied) / len(results)

        # Create result
        result = VerificationResult(
            case_id=TraceableId.generate(IdScheme.RASE, "verify"),
            verdict=verdict,
            accuracy=accuracy,
            constraint_results=results,
        )

        return result

    async def verify_objective(
        self,
        objective: Objective,
        document_path: str | None = None,
        state: KBState | None = None,
    ) -> VerificationResult:
        """Verify an objective against KB state.

        This is the main entry point for objective verification.
        Converts the objective to a verification case and evaluates it.

        Args:
            objective: Objective to verify
            document_path: Optional specific document to verify
            state: Optional pre-captured state

        Returns:
            VerificationResult with verdict, accuracy, and reward
        """
        if state is None:
            state = self.get_current_state()

        # Convert objective to verification case
        verification_case = objective_to_verification_case(
            objective,
            document_path=document_path,
        )

        # Evaluate
        result = verification_case.evaluate(state)

        logger.info(
            f"Verified objective '{objective.name}': "
            f"verdict={result.verdict.value}, accuracy={result.accuracy:.2f}, "
            f"reward={result.to_reward():.2f}"
        )

        return result

    async def verify_objective_with_evidence(
        self,
        objective: Objective,
        document_path: str | None = None,
    ) -> tuple[VerificationResult, DigitalThread]:
        """Verify objective and create evidence thread.

        This version creates a complete digital thread linking
        the objective to verification evidence for training.

        Args:
            objective: Objective to verify
            document_path: Optional specific document to verify

        Returns:
            Tuple of (VerificationResult, DigitalThread)
        """
        state = self.get_current_state()

        verification_case = objective_to_verification_case(
            objective,
            document_path=document_path,
        )

        result = verification_case.evaluate(state)

        # Create digital thread
        thread = create_digital_thread(objective, verification_case, result)

        # Store evidence
        await self._store_evidence(objective, result, thread)

        return result, thread

    async def _store_evidence(
        self,
        objective: Objective,
        result: VerificationResult,
        thread: DigitalThread,
        document_path: str | None = None,
    ) -> str:
        """Store verification evidence to HX Iceberg tables.

        Uses the HX evidence capture infrastructure for consistency
        with the rest of the data lake. Evidence is stored at
        hx://rase.evidence with thin manifests in KB.

        Args:
            objective: The verified objective
            result: Verification result
            thread: Digital thread
            document_path: Optional path to verified document

        Returns:
            Run ID of stored evidence
        """
        if self.use_minio:
            # Use HX evidence capture for Iceberg storage
            write_result = await capture_verification_evidence(
                objective_name=objective.name,
                result=result,
                thread=thread,
                document_path=document_path,
            )

            if write_result.success:
                logger.info(
                    f"Stored evidence to HX: run_id={write_result.run_id}, "
                    f"objective={objective.name}"
                )
                return write_result.run_id or ""
            else:
                logger.warning(
                    f"Failed to store evidence to HX: {write_result.errors}. "
                    "Falling back to KB-only manifest."
                )

        # Fallback: write KB manifest only (no Iceberg)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_id = f"{timestamp}_{thread.thread_id.short_id}"
        reward = result.to_reward()

        # Build constraint summary
        constraint_summary = []
        for cr in result.constraint_results:
            constraint_summary.append({
                "name": cr.constraint_name,
                "satisfied": cr.satisfied,
                "message": cr.message,
            })

        # Build manifest markdown
        manifest_content = f"""---
run_id: {run_id}
objective: {objective.name}
timestamp: {datetime.now().isoformat()}
verdict: {result.verdict.value}
accuracy: {result.accuracy}
reward: {reward}
---

# Verification Evidence: {objective.name}

**Run ID**: {run_id}
**Verdict**: {result.verdict.value}
**Accuracy**: {result.accuracy:.2%}
**Reward**: {reward:.2f}

## Gates

| Gate | Status | Message |
|------|--------|---------|
"""
        for cs in constraint_summary:
            status = "[OK]" if cs["satisfied"] else "[FAIL]"
            manifest_content += f"| {cs['name']} | {status} | {cs['message']} |\n"

        manifest_content += """
## Evidence Storage

**Note**: HX storage unavailable. Evidence stored in KB only.
"""

        # Write manifest to KB
        evidence_dir = Path(self.kb_root) / self.evidence_root / objective.name
        evidence_dir.mkdir(parents=True, exist_ok=True)

        manifest_path = evidence_dir / f"{run_id}.md"
        manifest_path.write_text(manifest_content)

        logger.info(f"Stored evidence manifest (KB-only): {manifest_path}")

        return run_id


__all__ = [
    "KBOracle",
]
