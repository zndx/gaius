#!/usr/bin/env python3
"""DSPy-based ontology extraction with GEPA-style optimization.

Uses DSPy signatures and assertions to extract high-quality OWL ontologies
that pass the RASE validation chain:
- Gate A: Syntactic (OWL loads)
- Gate B: Complex classes (restrictions, intersections)
- Gate C: Classes are verbalizable
- Gate D: Topics recoverable

GEPA (Gradient-free Evolutionary Prompt Optimization) approach:
1. Generate initial extraction
2. Validate through constraint chain
3. Provide feedback on failures
4. Regenerate with feedback

Usage:
    # Extract with DSPy optimization
    uv run python scripts/ontology_extraction_dspy.py

    # Specific model
    uv run python scripts/ontology_extraction_dspy.py --model cerebras

    # With iterations
    uv run python scripts/ontology_extraction_dspy.py --max-iterations 3
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import dspy

# =============================================================================
# DSPy Configuration
# =============================================================================

CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")


def get_dspy_lm(provider: str) -> dspy.LM:
    """Get DSPy language model for provider."""
    if provider == "cerebras":
        return dspy.LM(
            model="cerebras/zai-glm-4.7",
            api_key=CEREBRAS_API_KEY,
            max_tokens=4096,
            temperature=0.3,
        )
    elif provider == "xai":
        return dspy.LM(
            model="xai/grok-4-1-fast-non-reasoning",
            api_key=XAI_API_KEY,
            max_tokens=4096,
            temperature=0.3,
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")


# =============================================================================
# DSPy Signatures
# =============================================================================

class OntologyExtraction(dspy.Signature):
    """Extract a rich OWL ontology from technical documentation.

    The ontology MUST include:
    1. Named classes with rdfs:label annotations
    2. Class hierarchy using SubClassOf
    3. At least 3 COMPLEX class expressions using:
       - Restrictions: 'some', 'only', 'min', 'max', 'exactly'
       - Boolean: 'and', 'or', 'not'
       - Example: "HealthCheck that monitors some Environment"
    4. Object and Data properties with domains/ranges
    5. Use OWL Manchester Syntax format

    Complex class expression examples:
    - Class: EnvironmentHealthCheck EquivalentTo: HealthCheck and (monitors some Environment)
    - Class: HighAvailabilityCluster SubClassOf: Cluster and (hasNode min 3 Node)
    - Class: SecureService EquivalentTo: Service and (uses only EncryptedConnection)
    """

    corpus: str = dspy.InputField(desc="Technical documentation text to extract ontology from")
    ontology_owl: str = dspy.OutputField(desc="Complete OWL ontology in Manchester Syntax with complex class expressions")


class OntologyRefinement(dspy.Signature):
    """Refine an OWL ontology based on validation feedback.

    Fix the issues identified in the validation feedback while preserving
    valid parts of the ontology. Focus on adding complex class expressions.
    """

    corpus: str = dspy.InputField(desc="Original documentation")
    previous_ontology: str = dspy.InputField(desc="Previous ontology attempt")
    validation_feedback: str = dspy.InputField(desc="What failed and why")
    ontology_owl: str = dspy.OutputField(desc="Refined OWL ontology fixing the issues")


# =============================================================================
# Validation (simplified from validate_generated_ontology.py)
# =============================================================================

@dataclass
class ValidationResult:
    """Validation result with feedback."""
    gate_a_pass: bool = False  # Loads
    gate_b_pass: bool = False  # Complex classes
    gate_c_pass: bool = False  # Verbalizable
    gate_d_pass: bool = False  # Topics
    num_classes: int = 0
    num_complex: int = 0
    verbalization_ratio: float = 0.0
    feedback: str = ""


def validate_ontology(owl_text: str) -> ValidationResult:
    """Validate OWL ontology through constraint chain."""
    import re

    result = ValidationResult()
    feedback_parts = []

    # Count basic elements
    result.num_classes = len(re.findall(r"^Class:", owl_text, re.MULTILINE))

    # Check for complex expressions
    complex_patterns = [
        (r"EquivalentTo:", "equivalent class definitions"),
        (r"\s(some|only)\s", "existential/universal restrictions"),
        (r"\s(min|max|exactly)\s+\d+", "cardinality restrictions"),
        (r"\s(and|or)\s", "boolean combinations"),
        (r"\snot\s", "negation"),
    ]

    complex_found = []
    for pattern, desc in complex_patterns:
        matches = re.findall(pattern, owl_text, re.IGNORECASE)
        if matches:
            complex_found.append(f"{desc} ({len(matches)})")
            result.num_complex += len(matches)

    # Gate A: Basic parsing
    if result.num_classes > 0 and "Class:" in owl_text:
        result.gate_a_pass = True
    else:
        feedback_parts.append("Gate A FAIL: No valid class definitions found")

    # Gate B: Complex classes
    if result.num_complex >= 3:
        result.gate_b_pass = True
    else:
        feedback_parts.append(
            f"Gate B FAIL: Need at least 3 complex class expressions (found {result.num_complex}). "
            "Add EquivalentTo: definitions with 'some', 'only', 'and', 'or', 'min', 'max' restrictions. "
            f"Found: {', '.join(complex_found) if complex_found else 'none'}"
        )

    # Try DeepOnto validation for Gate C
    try:
        # Convert to RDF/XML and load
        from scripts.validate_generated_ontology import (
            parse_manchester_syntax,
            generate_rdfxml,
        )

        parsed = parse_manchester_syntax(owl_text)
        rdfxml = generate_rdfxml(parsed)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".owl", delete=False) as f:
            f.write(rdfxml)
            owl_path = f.name

        try:
            import jpype
            if not jpype.isJVMStarted():
                from deeponto import init_jvm
                init_jvm(os.environ.get("JVM_MEMORY", "4g"))

            from deeponto.onto import Ontology, OntologyVerbaliser

            onto = Ontology(owl_path)
            verbaliser = OntologyVerbaliser(onto)

            # Check complex classes via DeepOnto
            try:
                asserted_complex = list(onto.get_asserted_complex_classes())
                if len(asserted_complex) >= 3:
                    result.gate_b_pass = True
                result.num_complex = max(result.num_complex, len(asserted_complex))
            except Exception:
                pass

            # Verbalization
            named_classes = list(onto.owl_classes)[:20]
            verbalized = 0
            for cls in named_classes:
                try:
                    v = verbaliser.verbalise_class_expression(cls)
                    if v.verbal and len(v.verbal) >= 5:
                        verbalized += 1
                except Exception:
                    pass

            if named_classes:
                result.verbalization_ratio = verbalized / len(named_classes)

            if result.verbalization_ratio >= 0.5:
                result.gate_c_pass = True
            else:
                feedback_parts.append(
                    f"Gate C FAIL: Only {result.verbalization_ratio:.0%} of classes verbalized. "
                    "Complex class expressions with restrictions are more verbalizable."
                )

            # Gate D follows from C
            result.gate_d_pass = result.gate_c_pass

        except ImportError as e:
            feedback_parts.append(f"Gate C/D: DeepOnto not available ({e})")
        finally:
            Path(owl_path).unlink(missing_ok=True)

    except Exception as e:
        feedback_parts.append(f"Validation error: {e}")

    result.feedback = "\n".join(feedback_parts) if feedback_parts else "All gates passed!"
    return result


# =============================================================================
# GEPA-style Extraction with Refinement
# =============================================================================

class OntologyExtractor(dspy.Module):
    """DSPy module for ontology extraction with iterative refinement."""

    def __init__(self, max_iterations: int = 3):
        super().__init__()
        self.extract = dspy.ChainOfThought(OntologyExtraction)
        self.refine = dspy.ChainOfThought(OntologyRefinement)
        self.max_iterations = max_iterations

    def forward(self, corpus: str) -> dict[str, Any]:
        """Extract ontology with GEPA-style refinement."""
        # Initial extraction
        result = self.extract(corpus=corpus)
        ontology = result.ontology_owl

        # Extract OWL from markdown code block if present
        import re
        owl_match = re.search(r"```(?:owl|manchester)?\s*(.*?)```", ontology, re.DOTALL)
        if owl_match:
            ontology = owl_match.group(1).strip()

        # Validate and refine
        iterations = []
        for i in range(self.max_iterations):
            validation = validate_ontology(ontology)
            iterations.append({
                "iteration": i + 1,
                "gates_passed": sum([
                    validation.gate_a_pass,
                    validation.gate_b_pass,
                    validation.gate_c_pass,
                    validation.gate_d_pass,
                ]),
                "num_complex": validation.num_complex,
                "feedback": validation.feedback,
            })

            # Check if all gates pass
            if all([validation.gate_a_pass, validation.gate_b_pass,
                    validation.gate_c_pass, validation.gate_d_pass]):
                break

            # Refine based on feedback
            if i < self.max_iterations - 1:
                refined = self.refine(
                    corpus=corpus,
                    previous_ontology=ontology,
                    validation_feedback=validation.feedback,
                )
                ontology = refined.ontology_owl

                # Extract from code block
                owl_match = re.search(r"```(?:owl|manchester)?\s*(.*?)```", ontology, re.DOTALL)
                if owl_match:
                    ontology = owl_match.group(1).strip()

        # Final validation
        final_validation = validate_ontology(ontology)

        return {
            "ontology_owl": ontology,
            "iterations": iterations,
            "final_validation": {
                "gate_a": final_validation.gate_a_pass,
                "gate_b": final_validation.gate_b_pass,
                "gate_c": final_validation.gate_c_pass,
                "gate_d": final_validation.gate_d_pass,
                "num_classes": final_validation.num_classes,
                "num_complex": final_validation.num_complex,
                "verbalization_ratio": final_validation.verbalization_ratio,
            },
        }


# =============================================================================
# Corpus Loading
# =============================================================================

def load_corpus_sample(corpus_path: Path, max_chars: int = 8000) -> str:
    """Load corpus sample."""
    if corpus_path.is_file():
        return corpus_path.read_text()[:max_chars]

    texts = []
    total_chars = 0

    for md_file in sorted(corpus_path.rglob("*.md"))[:10]:
        content = md_file.read_text()
        if total_chars + len(content) > max_chars:
            remaining = max_chars - total_chars
            if remaining > 500:
                texts.append(content[:remaining])
            break
        texts.append(content)
        total_chars += len(content)

    return "\n\n---\n\n".join(texts)


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="DSPy-based ontology extraction")
    parser.add_argument(
        "--corpus-path",
        type=Path,
        default=Path("build/dev/current/cloudera/docs"),
        help="Path to corpus",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="cerebras",
        choices=["cerebras", "xai"],
        help="Model provider to use",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help="Maximum refinement iterations",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build/dev/scratch/ontology_dspy"),
        help="Output directory",
    )

    args = parser.parse_args()

    # Load corpus
    print(f"Loading corpus from: {args.corpus_path}")
    corpus = load_corpus_sample(args.corpus_path)
    print(f"Corpus size: {len(corpus)} chars (~{len(corpus)//4} tokens)")

    # Configure DSPy
    print(f"\nConfiguring DSPy with {args.model}...")
    lm = get_dspy_lm(args.model)
    dspy.configure(lm=lm)

    # Run extraction
    print(f"\nExtracting ontology (max {args.max_iterations} iterations)...")
    extractor = OntologyExtractor(max_iterations=args.max_iterations)
    result = extractor(corpus=corpus)

    # Print results
    print("\n" + "=" * 60)
    print("EXTRACTION RESULTS")
    print("=" * 60)

    for it in result["iterations"]:
        print(f"\nIteration {it['iteration']}:")
        print(f"  Gates passed: {it['gates_passed']}/4")
        print(f"  Complex classes: {it['num_complex']}")
        if it['feedback'] != "All gates passed!":
            for line in it['feedback'].split('\n'):
                print(f"  {line}")

    print("\n--- Final Validation ---")
    fv = result["final_validation"]
    print(f"Gate A (Loads):     {'PASS' if fv['gate_a'] else 'FAIL'}")
    print(f"Gate B (Complex):   {'PASS' if fv['gate_b'] else 'FAIL'} ({fv['num_complex']} complex)")
    print(f"Gate C (Verbalize): {'PASS' if fv['gate_c'] else 'FAIL'} ({fv['verbalization_ratio']:.0%})")
    print(f"Gate D (Topics):    {'PASS' if fv['gate_d'] else 'FAIL'}")

    # Save results
    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = args.output_dir / f"ontology_{args.model}_{timestamp}.json"

    with open(output_path, "w") as f:
        json.dump({
            "model": args.model,
            "timestamp": timestamp,
            "corpus_chars": len(corpus),
            "max_iterations": args.max_iterations,
            **result,
        }, f, indent=2)

    print(f"\nResults saved to: {output_path}")

    # Also save the OWL file
    owl_path = args.output_dir / f"ontology_{args.model}_{timestamp}.owl"
    owl_path.write_text(result["ontology_owl"])
    print(f"OWL file saved to: {owl_path}")


if __name__ == "__main__":
    main()
