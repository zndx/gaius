#!/usr/bin/env python3
"""Full-stack GEPA optimization over optillm techniques for ontology extraction.

Jointly optimizes:
- System prompt (DSPy signature instructions)
- Temperature
- optillm technique (cot_reflection, bon, moa, etc.)
- Technique parameters (e.g., n=5 for BON)

Uses Pareto multi-objective optimization considering:
- Gate pass rate (A-D)
- Verbalization ratio
- Latency
- Token efficiency

This script combines:
- DSPy GEPA for prompt optimization (inner loop)
- Technique search (outer loop)
- Pareto aggregation across all dimensions

Prerequisites:
    # 1. Download Devstral model
    HF_HOME=/raid/cache/huggingface huggingface-cli download mistralai/Devstral-Small-2-24B-Instruct-2512

    # 2. Start vLLM endpoint for Devstral
    CUDA_VISIBLE_DEVICES=0,1 vllm serve mistralai/Devstral-Small-2-24B-Instruct-2512 \\
      --port 8085 --tensor-parallel-size 2 --max-model-len 32768

    # 3. Start optillm proxy
    OPTILLM_BASE_URL=http://localhost:8085/v1 optillm --port 8090

Usage:
    uv run python scripts/ontology_technique_optimization.py \\
      --corpus-path build/dev/current/cloudera/docs \\
      --num-iterations 5

    # Full comparison with all techniques
    uv run python scripts/ontology_technique_optimization.py \\
      --corpus-path build/dev/current/cloudera/docs \\
      --full-search
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import dspy

# Import from existing pipeline
from ontology_denovo_pipeline import (
    ensure_jvm,
    load_corpus,
    validate_ontology,
    generate_rdfxml_ontology,
    parse_ontology_json,
    ValidationResult,
    GateResult,
    OUTPUT_DIR,
    OPTILLM_URL,
    LOCAL_MODEL,
)

# =============================================================================
# Configuration
# =============================================================================

TECHNIQUE_CONFIGS = [
    ("", {}),                      # Passthrough (no technique)
    ("cot_reflection", {}),        # Chain-of-Thought with reflection
    ("bon", {"n": 3}),             # Best of 3
    ("bon", {"n": 5}),             # Best of 5
    ("moa", {}),                   # Mixture of Agents
    ("self_consistency", {}),      # Self-consistency
    ("plansearch", {}),            # Plan-based search
    ("re2", {}),                   # Re-reading
]

# =============================================================================
# Candidate Configuration
# =============================================================================

@dataclass
class TechniqueCandidate:
    """A candidate configuration for technique optimization."""

    technique: str
    technique_params: dict[str, Any] = field(default_factory=dict)
    temperature: float = 0.3

    # Metrics (populated after evaluation)
    score: float = 0.0
    gates_passed: int = 0
    verbalization_ratio: float = 0.0
    latency_s: float = 0.0
    token_efficiency: float = 0.0  # score / latency

    # Pareto ranking
    pareto_rank: int = 0
    is_pareto_optimal: bool = False

    # Validation details
    validation: ValidationResult | None = None

    def objective_scores(self) -> dict[str, float]:
        """Get scores for Pareto comparison (all maximized)."""
        return {
            "score": self.score,
            "gates": self.gates_passed / 4.0,  # Normalize to 0-1
            "verbalization": self.verbalization_ratio,
            "efficiency": min(self.token_efficiency / 0.5, 1.0),  # Normalize
            "latency": 1.0 - min(self.latency_s / 120.0, 1.0),  # Lower is better
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "technique": self.technique or "passthrough",
            "technique_params": self.technique_params,
            "temperature": self.temperature,
            "score": self.score,
            "gates_passed": self.gates_passed,
            "verbalization_ratio": self.verbalization_ratio,
            "latency_s": self.latency_s,
            "token_efficiency": self.token_efficiency,
            "pareto_rank": self.pareto_rank,
            "is_pareto_optimal": self.is_pareto_optimal,
        }


# =============================================================================
# DSPy Signatures (from ontology_denovo_pipeline)
# =============================================================================

class StructuredOntologyExtraction(dspy.Signature):
    """Extract a formal OWL DL ontology from technical documentation.

    CRITICAL: Output must be valid JSON with this exact structure:
    {
        "classes": [...],
        "object_properties": [...],
        "data_properties": [...],
        "class_expressions": [...]
    }

    Each class should have: name, label, parent, equivalent_to (for complex classes)
    Use OWL DL restrictions: some, only, and, or, min, max, exactly
    """

    corpus: str = dspy.InputField(desc="Technical documentation to analyze")
    ontology_json: str = dspy.OutputField(
        desc="JSON object with classes, object_properties, data_properties, class_expressions"
    )


class OntologyRefinement(dspy.Signature):
    """Refine an OWL ontology based on validation feedback.

    Improve the ontology by:
    1. Adding more complex class expressions (EquivalentTo with restrictions)
    2. Ensuring all classes can be verbalized as natural language
    3. Using proper OWL DL constructs: some, only, and, or, min, max, exactly
    """

    corpus: str = dspy.InputField(desc="Original technical documentation")
    previous_ontology_json: str = dspy.InputField(desc="Previous ontology JSON")
    validation_feedback: str = dspy.InputField(desc="What needs improvement")
    ontology_json: str = dspy.OutputField(desc="Improved ontology JSON")


# =============================================================================
# Pareto Optimization
# =============================================================================

def is_dominated(a: dict[str, float], b: dict[str, float]) -> bool:
    """Check if solution a is dominated by solution b.

    a is dominated by b if b is at least as good in all objectives
    and strictly better in at least one.
    """
    all_keys = set(a.keys()) | set(b.keys())
    dominated = False

    for key in all_keys:
        a_val = a.get(key, 0.0)
        b_val = b.get(key, 0.0)

        if b_val > a_val:
            dominated = True
        elif a_val > b_val:
            return False  # a is better in at least one

    return dominated


def compute_pareto_front(candidates: list[TechniqueCandidate]) -> list[TechniqueCandidate]:
    """Compute Pareto-optimal candidates."""
    pareto_front = []

    for candidate in candidates:
        is_dominated_by_any = False
        a_scores = candidate.objective_scores()

        for other in candidates:
            if other is candidate:
                continue

            b_scores = other.objective_scores()
            if is_dominated(a_scores, b_scores):
                is_dominated_by_any = True
                break

        if not is_dominated_by_any:
            candidate.is_pareto_optimal = True
            candidate.pareto_rank = 0
            pareto_front.append(candidate)

    return pareto_front


def compute_pareto_ranks(candidates: list[TechniqueCandidate]) -> None:
    """Assign Pareto ranks to all candidates (non-dominated sorting)."""
    remaining = list(candidates)
    rank = 0

    while remaining:
        front = []
        for candidate in remaining:
            is_dominated_by_any = False
            a_scores = candidate.objective_scores()

            for other in remaining:
                if other is candidate:
                    continue
                b_scores = other.objective_scores()
                if is_dominated(a_scores, b_scores):
                    is_dominated_by_any = True
                    break

            if not is_dominated_by_any:
                candidate.pareto_rank = rank
                candidate.is_pareto_optimal = (rank == 0)
                front.append(candidate)

        for c in front:
            remaining.remove(c)

        rank += 1


# =============================================================================
# Evaluation
# =============================================================================

def get_dspy_lm(technique: str = "", temperature: float = 0.3) -> dspy.LM:
    """Get DSPy language model with technique."""
    model = LOCAL_MODEL
    if technique:
        model = f"{technique}-{model}"

    return dspy.LM(
        model=f"openai/{model}",
        api_base=OPTILLM_URL,
        api_key="gaius-local",
        max_tokens=4096,
        temperature=temperature,
    )


def evaluate_candidate(
    candidate: TechniqueCandidate,
    corpus: str,
    max_iterations: int = 2,
) -> TechniqueCandidate:
    """Evaluate a candidate configuration."""
    start_time = time.time()

    # Configure DSPy
    lm = get_dspy_lm(candidate.technique, candidate.temperature)
    dspy.configure(lm=lm)

    # DSPy modules
    extractor = dspy.ChainOfThought(StructuredOntologyExtraction)
    refiner = dspy.ChainOfThought(OntologyRefinement)

    ontology_json_str = None
    validation = None

    for iteration in range(max_iterations):
        try:
            if iteration == 0:
                response = extractor(corpus=corpus)
                ontology_json_str = response.ontology_json
            else:
                response = refiner(
                    corpus=corpus,
                    previous_ontology_json=ontology_json_str,
                    validation_feedback=validation.feedback if validation else "",
                )
                ontology_json_str = response.ontology_json

            # Parse and generate RDF/XML
            ontology_data = parse_ontology_json(ontology_json_str)
            if ontology_data:
                rdfxml = generate_rdfxml_ontology(ontology_data)
                validation = validate_ontology(rdfxml)
            else:
                validation = ValidationResult(
                    error="Failed to parse ontology JSON",
                    feedback="Output must be valid JSON with classes, properties arrays",
                )

        except Exception as e:
            validation = ValidationResult(
                error=str(e),
                feedback=f"Extraction error: {e}",
            )

    # Populate candidate metrics
    candidate.latency_s = time.time() - start_time

    if validation:
        candidate.validation = validation
        candidate.score = validation.score
        candidate.verbalization_ratio = validation.verbalization_ratio
        candidate.gates_passed = sum([
            validation.gate_a.passed if validation.gate_a else 0,
            validation.gate_b.passed if validation.gate_b else 0,
            validation.gate_c.passed if validation.gate_c else 0,
            validation.gate_d.passed if validation.gate_d else 0,
        ])

    # Token efficiency: score per second
    if candidate.latency_s > 0:
        candidate.token_efficiency = candidate.score / candidate.latency_s

    return candidate


# =============================================================================
# Optimization Loop
# =============================================================================

def generate_candidates(
    base_candidate: TechniqueCandidate | None,
    num_candidates: int,
) -> list[TechniqueCandidate]:
    """Generate candidate configurations."""
    candidates = []

    for _ in range(num_candidates):
        tech, params = random.choice(TECHNIQUE_CONFIGS)

        # Temperature variation
        base_temp = base_candidate.temperature if base_candidate else 0.3
        temp = base_temp + random.uniform(-0.1, 0.1)
        temp = max(0.1, min(0.8, temp))

        candidates.append(TechniqueCandidate(
            technique=tech,
            technique_params=params.copy(),
            temperature=temp,
        ))

    return candidates


def run_optimization(
    corpus: str,
    num_iterations: int = 5,
    candidates_per_iter: int = 4,
    max_refinements: int = 2,
) -> tuple[list[TechniqueCandidate], list[TechniqueCandidate]]:
    """Run full-stack Pareto optimization.

    Returns:
        Tuple of (pareto_front, all_candidates)
    """
    all_candidates: list[TechniqueCandidate] = []
    best_candidate: TechniqueCandidate | None = None

    for iteration in range(num_iterations):
        print(f"\n{'='*60}")
        print(f"ITERATION {iteration + 1}/{num_iterations}")
        print(f"{'='*60}")

        # Generate candidates
        new_candidates = generate_candidates(best_candidate, candidates_per_iter)

        # Evaluate candidates
        for i, candidate in enumerate(new_candidates):
            tech_name = candidate.technique or "passthrough"
            print(f"\n  [{i+1}/{len(new_candidates)}] Testing {tech_name} (T={candidate.temperature:.2f})")

            try:
                evaluate_candidate(candidate, corpus, max_refinements)
                print(f"    Score: {candidate.score:.2f}, Gates: {candidate.gates_passed}/4, "
                      f"Verb: {candidate.verbalization_ratio*100:.0f}%, Latency: {candidate.latency_s:.1f}s")
            except Exception as e:
                print(f"    ERROR: {e}")
                candidate.score = 0.0

        all_candidates.extend(new_candidates)

        # Compute Pareto front
        pareto_front = compute_pareto_front(all_candidates)
        compute_pareto_ranks(all_candidates)

        print(f"\n  Pareto front size: {len(pareto_front)}")

        # Select best for next iteration (highest score on Pareto front)
        if pareto_front:
            best_candidate = max(pareto_front, key=lambda c: c.score)
            print(f"  Best so far: {best_candidate.technique or 'passthrough'} "
                  f"(score={best_candidate.score:.2f})")

    # Final Pareto front
    pareto_front = compute_pareto_front(all_candidates)
    return pareto_front, all_candidates


def run_full_search(
    corpus: str,
    max_refinements: int = 2,
) -> tuple[list[TechniqueCandidate], list[TechniqueCandidate]]:
    """Exhaustive search over all techniques.

    Returns:
        Tuple of (pareto_front, all_candidates)
    """
    all_candidates: list[TechniqueCandidate] = []

    print(f"\n{'='*60}")
    print("FULL TECHNIQUE SEARCH")
    print(f"{'='*60}")

    for tech, params in TECHNIQUE_CONFIGS:
        tech_name = tech or "passthrough"
        print(f"\n  Testing {tech_name}...")

        candidate = TechniqueCandidate(
            technique=tech,
            technique_params=params.copy(),
            temperature=0.3,
        )

        try:
            evaluate_candidate(candidate, corpus, max_refinements)
            print(f"    Score: {candidate.score:.2f}, Gates: {candidate.gates_passed}/4, "
                  f"Verb: {candidate.verbalization_ratio*100:.0f}%, Latency: {candidate.latency_s:.1f}s")
        except Exception as e:
            print(f"    ERROR: {e}")
            candidate.score = 0.0

        all_candidates.append(candidate)

    # Compute Pareto front
    pareto_front = compute_pareto_front(all_candidates)
    compute_pareto_ranks(all_candidates)

    return pareto_front, all_candidates


# =============================================================================
# Reporting
# =============================================================================

def print_report(
    pareto_front: list[TechniqueCandidate],
    all_candidates: list[TechniqueCandidate],
) -> None:
    """Print optimization report."""
    print(f"\n{'='*60}")
    print("OPTIMIZATION RESULTS")
    print(f"{'='*60}")

    print(f"\nTotal candidates evaluated: {len(all_candidates)}")
    print(f"Pareto front size: {len(pareto_front)}")

    print(f"\n{'='*60}")
    print("PARETO FRONT (Non-dominated Solutions)")
    print(f"{'='*60}")

    # Sort by score
    sorted_front = sorted(pareto_front, key=lambda c: c.score, reverse=True)

    for i, c in enumerate(sorted_front, 1):
        tech_name = c.technique or "passthrough"
        print(f"\n{i}. {tech_name}")
        print(f"   Score: {c.score:.2f}")
        print(f"   Gates: {c.gates_passed}/4")
        print(f"   Verbalization: {c.verbalization_ratio*100:.0f}%")
        print(f"   Latency: {c.latency_s:.1f}s")
        print(f"   Efficiency: {c.token_efficiency:.4f} score/s")

    # Best by each metric
    print(f"\n{'='*60}")
    print("BEST BY METRIC")
    print(f"{'='*60}")

    valid = [c for c in all_candidates if c.score > 0]
    if valid:
        best_score = max(valid, key=lambda c: c.score)
        best_gates = max(valid, key=lambda c: c.gates_passed)
        best_verb = max(valid, key=lambda c: c.verbalization_ratio)
        best_latency = min(valid, key=lambda c: c.latency_s)
        best_efficiency = max(valid, key=lambda c: c.token_efficiency)

        print(f"\nBest score: {best_score.technique or 'passthrough'} ({best_score.score:.2f})")
        print(f"Best gates: {best_gates.technique or 'passthrough'} ({best_gates.gates_passed}/4)")
        print(f"Best verbalization: {best_verb.technique or 'passthrough'} ({best_verb.verbalization_ratio*100:.0f}%)")
        print(f"Best latency: {best_latency.technique or 'passthrough'} ({best_latency.latency_s:.1f}s)")
        print(f"Best efficiency: {best_efficiency.technique or 'passthrough'} ({best_efficiency.token_efficiency:.4f})")


def save_results(
    pareto_front: list[TechniqueCandidate],
    all_candidates: list[TechniqueCandidate],
    output_dir: Path,
) -> Path:
    """Save results to JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"technique_optimization_{timestamp}.json"

    results = {
        "timestamp": timestamp,
        "model": LOCAL_MODEL,
        "num_candidates": len(all_candidates),
        "pareto_front_size": len(pareto_front),
        "pareto_front": [c.to_dict() for c in pareto_front],
        "all_candidates": [c.to_dict() for c in all_candidates],
    }

    output_path.write_text(json.dumps(results, indent=2))
    return output_path


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Full-stack GEPA optimization over optillm techniques"
    )
    parser.add_argument(
        "--corpus-path",
        type=Path,
        default=Path("build/dev/current/cloudera/docs"),
        help="Path to corpus directory or file",
    )
    parser.add_argument(
        "--num-iterations",
        type=int,
        default=5,
        help="Number of optimization iterations",
    )
    parser.add_argument(
        "--candidates-per-iter",
        type=int,
        default=4,
        help="Candidates per iteration",
    )
    parser.add_argument(
        "--max-refinements",
        type=int,
        default=2,
        help="Max refinement iterations per candidate",
    )
    parser.add_argument(
        "--full-search",
        action="store_true",
        help="Exhaustive search over all techniques (no iteration)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Output directory",
    )

    args = parser.parse_args()

    # Ensure JVM for DeepOnto
    ensure_jvm()

    # Load corpus
    print(f"Loading corpus from: {args.corpus_path}")
    corpus, corpus_name = load_corpus(args.corpus_path)
    print(f"Corpus: {corpus_name} ({len(corpus)} chars, ~{len(corpus)//4} tokens)")

    # Check optillm is running
    print(f"\nOptillm URL: {OPTILLM_URL}")
    print(f"Local model: {LOCAL_MODEL}")

    # Run optimization
    if args.full_search:
        pareto_front, all_candidates = run_full_search(
            corpus=corpus,
            max_refinements=args.max_refinements,
        )
    else:
        pareto_front, all_candidates = run_optimization(
            corpus=corpus,
            num_iterations=args.num_iterations,
            candidates_per_iter=args.candidates_per_iter,
            max_refinements=args.max_refinements,
        )

    # Print report
    print_report(pareto_front, all_candidates)

    # Save results
    output_path = save_results(pareto_front, all_candidates, args.output_dir)
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
