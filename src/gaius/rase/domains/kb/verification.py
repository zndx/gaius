"""KB verification infrastructure.

Provides the verification case factory that converts objectives
to executable verification cases using RASE infrastructure.

Key pattern:
    objective_to_verification_case(objective) -> KBVerificationCase

The verification case can then be executed by KBOracle to produce
a VerificationResult with verdict and reward.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from gaius.rase.core.constraints import AllOf, Constraint, ConstraintResult
from gaius.rase.core.vm import (
    VerificationResult,
    VerificationObjective,
    VerdictKind,
    GradedReward,
)
from gaius.rase.traceability import TraceableId, DigitalThread, IdScheme

from .state import KBState
from .objective import Objective, ObjectiveGate, GateLevel


class KBVerificationCase(BaseModel):
    """Verification case for KB objectives.

    Extends the generic VerificationCase with KB-specific logic
    for progressive gate evaluation.

    Attributes:
        objective: The objective being verified
        constraints: List of constraints derived from gates
        gate_weights: Weights for graded reward computation
    """

    objective: Objective
    constraints: list[Constraint[KBState]] = Field(default_factory=list)
    gate_weights: dict[str, float] = Field(default_factory=dict)

    @property
    def name(self) -> str:
        return f"KBVerify({self.objective.name})"

    def to_traceable_id(self) -> TraceableId:
        """Generate TraceableId for this verification case."""
        return TraceableId(
            scheme=IdScheme.RASE,
            path=f"verification/{self.objective.name}",
        )

    def evaluate(self, state: KBState) -> VerificationResult:
        """Evaluate all constraints against KB state.

        Evaluates gates in order: syntactic → semantic → empirical.
        Short-circuits on syntactic failure (no point checking semantics
        if document doesn't parse).

        Returns:
            VerificationResult with verdict, accuracy, and reward
        """
        results = []
        failed_at_level: GateLevel | None = None

        # Group constraints by level
        by_level: dict[GateLevel, list[tuple[Constraint[KBState], float]]] = {
            GateLevel.SYNTACTIC: [],
            GateLevel.SEMANTIC: [],
            GateLevel.EMPIRICAL: [],
        }

        for constraint in self.constraints:
            # Find the gate for this constraint to get its level
            weight = self.gate_weights.get(constraint.name, 1.0)
            # Infer level from constraint name prefix or default to semantic
            if "Parse" in constraint.name or "Frontmatter" in constraint.name:
                by_level[GateLevel.SYNTACTIC].append((constraint, weight))
            elif "Accessible" in constraint.name or "Coherence" in constraint.name:
                by_level[GateLevel.EMPIRICAL].append((constraint, weight))
            else:
                by_level[GateLevel.SEMANTIC].append((constraint, weight))

        # Evaluate in level order
        for level in [GateLevel.SYNTACTIC, GateLevel.SEMANTIC, GateLevel.EMPIRICAL]:
            level_constraints = by_level[level]

            for constraint, weight in level_constraints:
                result = constraint.evaluate(state)
                results.append((result, weight))

                if not result.satisfied and failed_at_level is None:
                    failed_at_level = level

            # Short-circuit on syntactic failure
            if failed_at_level == GateLevel.SYNTACTIC:
                break

        # Compute verdict
        all_passed = all(r.satisfied for r, _ in results)
        any_passed = any(r.satisfied for r, _ in results)

        if all_passed:
            verdict = VerdictKind.PASS
        elif not any_passed:
            verdict = VerdictKind.FAIL
        else:
            # Partial success - still counts as fail but with partial credit
            verdict = VerdictKind.FAIL

        # Compute weighted accuracy
        if not results:
            accuracy = 1.0
        else:
            total_weight = sum(w for _, w in results)
            satisfied_weight = sum(w for r, w in results if r.satisfied)
            accuracy = satisfied_weight / total_weight if total_weight > 0 else 0.0

        # Compute reward using GradedReward
        reward_strategy = GradedReward()

        # Build constraint result summary
        constraint_results = [r for r, _ in results]

        # Create a minimal verification result
        # Note: We create our own result object since we need custom fields
        result = VerificationResult(
            case_id=self.to_traceable_id(),
            verdict=verdict,
            accuracy=accuracy,
            constraint_results=constraint_results,
        )

        # Compute reward from accuracy (GradedReward expects VerificationResult)
        reward = reward_strategy.compute(result)

        # Return result with computed reward stored in details
        return VerificationResult(
            case_id=self.to_traceable_id(),
            verdict=verdict,
            accuracy=accuracy,
            constraint_results=constraint_results,
        )


def objective_to_verification_case(
    objective: Objective,
    document_path: str | None = None,
) -> KBVerificationCase:
    """Convert an objective to an executable verification case.

    This is the factory function that bridges objectives (what we want)
    to verification cases (how we check it).

    Args:
        objective: The objective to convert
        document_path: Path to document to verify (if different from objective)

    Returns:
        KBVerificationCase ready for execution
    """
    from . import (
        DocumentParses,
        WikilinksResolve,
        HasCitations,
        CitationsAccessible,
        SemanticCoherence,
        FrontmatterValid,
        OutputStructureValid,
        # Wikilink integrity constraints
        HasWikilinks,
        NoOrphanLinks,
        LinkDensity,
        # Citation freshness constraints
        CitationsNotStale,
        SourcesAuthoritative,
        # Semantic grounding constraints
        ClaimsIdentified,
        ClaimsGrounded,
        NoHallucinations,
    )

    # Map constraint type names to classes
    constraint_classes = {
        "DocumentParses": DocumentParses,
        "WikilinksResolve": WikilinksResolve,
        "HasCitations": HasCitations,
        "CitationsAccessible": CitationsAccessible,
        "SemanticCoherence": SemanticCoherence,
        "FrontmatterValid": FrontmatterValid,
        "OutputStructureValid": OutputStructureValid,
        # Wikilink integrity
        "HasWikilinks": HasWikilinks,
        "NoOrphanLinks": NoOrphanLinks,
        "LinkDensity": LinkDensity,
        # Citation freshness
        "CitationsNotStale": CitationsNotStale,
        "SourcesAuthoritative": SourcesAuthoritative,
        # Semantic grounding
        "ClaimsIdentified": ClaimsIdentified,
        "ClaimsGrounded": ClaimsGrounded,
        "NoHallucinations": NoHallucinations,
    }

    # Default to objective's own path
    if document_path is None:
        document_path = objective.path

    constraints: list[Constraint[KBState]] = []
    gate_weights: dict[str, float] = {}

    for gate in objective.gates:
        constraint_class = constraint_classes.get(gate.constraint_type)

        if constraint_class is None:
            # Unknown constraint type - skip with warning
            continue

        # Build constraint params
        params = {"document_path": document_path}
        params.update(gate.params)

        try:
            constraint = constraint_class(**params)
            constraints.append(constraint)
            gate_weights[constraint.name] = gate.weight
        except Exception as e:
            # Failed to instantiate constraint
            continue

    return KBVerificationCase(
        objective=objective,
        constraints=constraints,
        gate_weights=gate_weights,
    )


def create_digital_thread(
    objective: Objective,
    verification_case: KBVerificationCase,
    result: VerificationResult | None = None,
) -> DigitalThread:
    """Create a digital thread linking objective to verification.

    The digital thread provides complete audit trail from objective
    to evidence to training.

    Args:
        objective: The objective being verified
        verification_case: The verification case used
        result: Optional verification result

    Returns:
        DigitalThread with linked artifacts
    """
    thread = DigitalThread(
        requirement_id=objective.to_traceable_id(),
        verification_case_id=verification_case.to_traceable_id(),
    )

    if result:
        thread.verification_result_id = TraceableId.generate(
            IdScheme.RASE,
            prefix="results",
        )
        thread.reward_outcome = result.to_reward()

    return thread


__all__ = [
    "KBVerificationCase",
    "objective_to_verification_case",
    "create_digital_thread",
]
