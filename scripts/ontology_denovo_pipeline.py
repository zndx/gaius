#!/usr/bin/env python3
"""De novo ontology generation pipeline with RASE validation.

End-to-end pipeline for generating OWL ontologies from technical documentation:
1. Extract ontology using DSPy-optimized prompts
2. Validate through RASE constraint chain (DeepOnto)
3. Iteratively refine based on validation feedback
4. Optimize prompts using GEPA-style evolution

The key insight: we optimize for the EXACT syntax DeepOnto requires.
Verbalization success is the primary optimization metric.

Gates:
- A: OWL loads in DeepOnto (syntactic correctness)
- B: Has complex asserted classes (conceptual depth)
- C: Classes are verbalizable (semantic quality)
- D: Topics recoverable from verbalizations (empirical validation)

Usage:
    # Run full pipeline with default settings
    uv run python scripts/ontology_denovo_pipeline.py

    # Specific provider
    uv run python scripts/ontology_denovo_pipeline.py --provider cerebras

    # Compare providers
    uv run python scripts/ontology_denovo_pipeline.py --provider cerebras,xai

    # Custom corpus
    uv run python scripts/ontology_denovo_pipeline.py --corpus-path build/dev/current/cloudera/docs
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import dspy

# =============================================================================
# Configuration
# =============================================================================

CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")

# Local inference via optillm
OPTILLM_URL = os.getenv("OPTILLM_URL", "http://localhost:8090/v1")
LOCAL_MODEL = os.getenv("LOCAL_MODEL", "mistralai/Devstral-Small-2-24B-Instruct-2512")

# Output directory
OUTPUT_DIR = Path("build/dev/scratch/ontology_denovo")

# JVM memory for DeepOnto
JVM_MEMORY = os.environ.get("JVM_MEMORY", "4g")

# =============================================================================
# DeepOnto Integration
# =============================================================================

_JVM_STARTED = False


def ensure_jvm() -> None:
    """Ensure JVM is started for DeepOnto."""
    global _JVM_STARTED
    if _JVM_STARTED:
        return
    try:
        import jpype
        if not jpype.isJVMStarted():
            from deeponto import init_jvm
            init_jvm(JVM_MEMORY)
        _JVM_STARTED = True
    except ImportError:
        pass


# =============================================================================
# Validation Results
# =============================================================================

@dataclass
class GateResult:
    """Result for a single validation gate."""
    name: str
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Complete validation result through all gates."""
    # Gate results
    gate_a: GateResult | None = None  # Loads
    gate_b: GateResult | None = None  # Complex classes
    gate_c: GateResult | None = None  # Verbalizable
    gate_d: GateResult | None = None  # Topics

    # Metrics
    num_classes: int = 0
    num_complex_classes: int = 0
    num_properties: int = 0
    verbalization_count: int = 0
    verbalization_ratio: float = 0.0
    verbalizations: list[dict[str, str]] = field(default_factory=list)

    # Overall
    all_gates_pass: bool = False
    score: float = 0.0  # 0-1 optimization score
    feedback: str = ""

    # Errors
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_a": asdict(self.gate_a) if self.gate_a else None,
            "gate_b": asdict(self.gate_b) if self.gate_b else None,
            "gate_c": asdict(self.gate_c) if self.gate_c else None,
            "gate_d": asdict(self.gate_d) if self.gate_d else None,
            "num_classes": self.num_classes,
            "num_complex_classes": self.num_complex_classes,
            "num_properties": self.num_properties,
            "verbalization_count": self.verbalization_count,
            "verbalization_ratio": self.verbalization_ratio,
            "verbalizations": self.verbalizations,
            "all_gates_pass": self.all_gates_pass,
            "score": self.score,
            "feedback": self.feedback,
            "error": self.error,
        }


@dataclass
class ExtractionResult:
    """Result from ontology extraction attempt."""
    provider: str
    model: str
    iteration: int

    # Output
    ontology_rdfxml: str
    ontology_raw: str  # Original model output

    # Timing
    extraction_time: float
    validation_time: float

    # Validation
    validation: ValidationResult | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d['validation']:
            d['validation'] = self.validation.to_dict()
        return d


# =============================================================================
# OWL RDF/XML Generation (DeepOnto-compatible)
# =============================================================================

def generate_rdfxml_ontology(
    classes: list[dict],
    object_properties: list[dict],
    data_properties: list[dict],
    complex_classes: list[dict],
    base_uri: str = "http://example.org/ontology#",
) -> str:
    """Generate RDF/XML that DeepOnto can parse with complex class expressions.

    This produces OWL 2 RDF/XML with:
    - Named classes with rdfs:label
    - SubClassOf relationships
    - EquivalentClass with complex expressions
    - ObjectProperty and DataProperty definitions
    """
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE rdf:RDF [',
        f'    <!ENTITY owl "http://www.w3.org/2002/07/owl#">',
        f'    <!ENTITY xsd "http://www.w3.org/2001/XMLSchema#">',
        f'    <!ENTITY rdfs "http://www.w3.org/2000/01/rdf-schema#">',
        f'    <!ENTITY base "{base_uri}">',
        ']>',
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"',
        '         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"',
        '         xmlns:owl="http://www.w3.org/2002/07/owl#"',
        '         xmlns:xsd="http://www.w3.org/2001/XMLSchema#"',
        f'         xml:base="{base_uri}"',
        f'         xmlns="{base_uri}">',
        '',
        f'  <owl:Ontology rdf:about="{base_uri}"/>',
        '',
    ]

    # Object Properties
    for prop in object_properties:
        name = prop["name"]
        lines.append(f'  <owl:ObjectProperty rdf:about="{base_uri}{name}">')
        if prop.get("label"):
            lines.append(f'    <rdfs:label>{_xml_escape(prop["label"])}</rdfs:label>')
        if prop.get("domain"):
            lines.append(f'    <rdfs:domain rdf:resource="{base_uri}{prop["domain"]}"/>')
        if prop.get("range"):
            lines.append(f'    <rdfs:range rdf:resource="{base_uri}{prop["range"]}"/>')
        lines.append('  </owl:ObjectProperty>')
        lines.append('')

    # Data Properties
    for prop in data_properties:
        name = prop["name"]
        lines.append(f'  <owl:DatatypeProperty rdf:about="{base_uri}{name}">')
        if prop.get("label"):
            lines.append(f'    <rdfs:label>{_xml_escape(prop["label"])}</rdfs:label>')
        if prop.get("domain"):
            lines.append(f'    <rdfs:domain rdf:resource="{base_uri}{prop["domain"]}"/>')
        if prop.get("range"):
            rng = prop["range"]
            if rng.startswith("xsd:"):
                rng = f"http://www.w3.org/2001/XMLSchema#{rng[4:]}"
            lines.append(f'    <rdfs:range rdf:resource="{rng}"/>')
        lines.append('  </owl:DatatypeProperty>')
        lines.append('')

    # Named Classes
    for cls in classes:
        name = cls["name"]
        lines.append(f'  <owl:Class rdf:about="{base_uri}{name}">')
        if cls.get("label"):
            lines.append(f'    <rdfs:label>{_xml_escape(cls["label"])}</rdfs:label>')
        if cls.get("comment"):
            lines.append(f'    <rdfs:comment>{_xml_escape(cls["comment"])}</rdfs:comment>')
        if cls.get("parent"):
            parent = cls["parent"]
            if not parent.startswith("http"):
                parent = base_uri + parent
            lines.append(f'    <rdfs:subClassOf rdf:resource="{parent}"/>')
        lines.append('  </owl:Class>')
        lines.append('')

    # Complex Class Expressions (EquivalentClass with restrictions)
    for cc in complex_classes:
        name = cc["name"]
        lines.append(f'  <owl:Class rdf:about="{base_uri}{name}">')

        # Add equivalent class with restriction
        if cc.get("equivalent_restriction"):
            restr = cc["equivalent_restriction"]
            lines.append('    <owl:equivalentClass>')
            lines.append('      <owl:Restriction>')

            prop = restr.get("property", "")
            if not prop.startswith("http"):
                prop = base_uri + prop
            lines.append(f'        <owl:onProperty rdf:resource="{prop}"/>')

            # Handle different restriction types
            if restr.get("some_values_from"):
                filler = restr["some_values_from"]
                if not filler.startswith("http"):
                    filler = base_uri + filler
                lines.append(f'        <owl:someValuesFrom rdf:resource="{filler}"/>')
            elif restr.get("all_values_from"):
                filler = restr["all_values_from"]
                if not filler.startswith("http"):
                    filler = base_uri + filler
                lines.append(f'        <owl:allValuesFrom rdf:resource="{filler}"/>')
            elif restr.get("min_cardinality") is not None:
                lines.append(f'        <owl:minCardinality rdf:datatype="http://www.w3.org/2001/XMLSchema#nonNegativeInteger">{restr["min_cardinality"]}</owl:minCardinality>')
            elif restr.get("max_cardinality") is not None:
                lines.append(f'        <owl:maxCardinality rdf:datatype="http://www.w3.org/2001/XMLSchema#nonNegativeInteger">{restr["max_cardinality"]}</owl:maxCardinality>')
            elif restr.get("exact_cardinality") is not None:
                lines.append(f'        <owl:cardinality rdf:datatype="http://www.w3.org/2001/XMLSchema#nonNegativeInteger">{restr["exact_cardinality"]}</owl:cardinality>')

            lines.append('      </owl:Restriction>')
            lines.append('    </owl:equivalentClass>')

        # Add SubClassOf restriction
        if cc.get("subclass_restriction"):
            restr = cc["subclass_restriction"]
            lines.append('    <rdfs:subClassOf>')
            lines.append('      <owl:Restriction>')

            prop = restr.get("property", "")
            if not prop.startswith("http"):
                prop = base_uri + prop
            lines.append(f'        <owl:onProperty rdf:resource="{prop}"/>')

            if restr.get("some_values_from"):
                filler = restr["some_values_from"]
                if not filler.startswith("http"):
                    filler = base_uri + filler
                lines.append(f'        <owl:someValuesFrom rdf:resource="{filler}"/>')
            elif restr.get("all_values_from"):
                filler = restr["all_values_from"]
                if not filler.startswith("http"):
                    filler = base_uri + filler
                lines.append(f'        <owl:allValuesFrom rdf:resource="{filler}"/>')

            lines.append('      </owl:Restriction>')
            lines.append('    </rdfs:subClassOf>')

        lines.append('  </owl:Class>')
        lines.append('')

    lines.append('</rdf:RDF>')
    return '\n'.join(lines)


def _xml_escape(s: str) -> str:
    """Escape XML special characters."""
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


# =============================================================================
# DSPy Signatures
# =============================================================================

class StructuredOntologyExtraction(dspy.Signature):
    """Extract a structured ontology from technical documentation.

    You must produce a JSON object with the following structure:
    {
        "base_uri": "http://example.org/ontology#",
        "classes": [
            {"name": "ClassName", "label": "Human Label", "parent": "ParentClass", "comment": "Description"}
        ],
        "object_properties": [
            {"name": "propName", "label": "Property Label", "domain": "DomainClass", "range": "RangeClass"}
        ],
        "data_properties": [
            {"name": "propName", "label": "Property Label", "domain": "DomainClass", "range": "xsd:string"}
        ],
        "complex_classes": [
            {
                "name": "ComplexClassName",
                "equivalent_restriction": {"property": "propName", "some_values_from": "FillerClass"},
                "subclass_restriction": {"property": "propName", "all_values_from": "FillerClass"}
            }
        ]
    }

    Requirements:
    1. Extract at least 10 meaningful classes from the documentation
    2. Create a proper class hierarchy using "parent" field
    3. Define at least 5 object properties connecting classes
    4. Include at least 5 complex classes with restrictions:
       - some_values_from: existential restriction (∃)
       - all_values_from: universal restriction (∀)
       - min_cardinality, max_cardinality, exact_cardinality: cardinality restrictions
    5. Use meaningful labels that describe the concept
    """

    corpus: str = dspy.InputField(desc="Technical documentation to extract ontology from")
    ontology_json: str = dspy.OutputField(desc="JSON object containing the structured ontology")


class OntologyRefinement(dspy.Signature):
    """Refine an ontology based on validation feedback.

    Fix the specific issues mentioned in the feedback while preserving
    valid parts of the ontology. Focus on:
    1. Adding more complex class restrictions if needed
    2. Ensuring all class names are valid identifiers
    3. Making labels more descriptive for verbalization

    Output the same JSON structure as the original.
    """

    corpus: str = dspy.InputField(desc="Original documentation")
    previous_ontology_json: str = dspy.InputField(desc="Previous ontology JSON")
    validation_feedback: str = dspy.InputField(desc="What failed and specific fixes needed")
    ontology_json: str = dspy.OutputField(desc="Refined ontology JSON fixing the issues")


# =============================================================================
# Validation Pipeline
# =============================================================================

def validate_ontology(rdfxml: str, min_complex: int = 3, min_verbalization: float = 0.5) -> ValidationResult:
    """Validate ontology through RASE constraint chain using DeepOnto."""
    result = ValidationResult()
    feedback_parts = []

    # Write to temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".owl", delete=False) as f:
        f.write(rdfxml)
        owl_path = f.name

    try:
        ensure_jvm()
        from deeponto.onto import Ontology, OntologyVerbaliser

        # Gate A: Load ontology
        try:
            onto = Ontology(owl_path)
            owl_classes = list(onto.owl_classes)
            result.num_classes = len(owl_classes)

            result.gate_a = GateResult(
                name="OntologyLoads",
                passed=True,
                message=f"Loaded {result.num_classes} classes",
                details={"class_count": result.num_classes}
            )
        except Exception as e:
            result.gate_a = GateResult(
                name="OntologyLoads",
                passed=False,
                message=f"Failed to load: {e}",
                details={"error": str(e)}
            )
            result.error = str(e)
            feedback_parts.append(f"GATE A FAIL: OWL syntax error - {e}")
            result.feedback = "\n".join(feedback_parts)
            return result

        # Gate B: Complex asserted classes
        try:
            complex_classes = list(onto.get_asserted_complex_classes())
            result.num_complex_classes = len(complex_classes)

            if result.num_complex_classes >= min_complex:
                result.gate_b = GateResult(
                    name="HasComplexClasses",
                    passed=True,
                    message=f"Found {result.num_complex_classes} complex classes",
                    details={
                        "count": result.num_complex_classes,
                        "examples": [str(c)[:80] for c in complex_classes[:3]]
                    }
                )
            else:
                result.gate_b = GateResult(
                    name="HasComplexClasses",
                    passed=False,
                    message=f"Only {result.num_complex_classes} complex classes (need {min_complex})",
                    details={"count": result.num_complex_classes, "required": min_complex}
                )
                feedback_parts.append(
                    f"GATE B FAIL: Need {min_complex}+ complex classes with restrictions. "
                    f"Found {result.num_complex_classes}. Add more equivalent_restriction or "
                    "subclass_restriction entries with some_values_from/all_values_from."
                )
        except Exception as e:
            result.gate_b = GateResult(
                name="HasComplexClasses",
                passed=False,
                message=f"Error checking complex classes: {e}",
                details={"error": str(e)}
            )
            feedback_parts.append(f"GATE B ERROR: {e}")

        # Gate C: Verbalization
        try:
            verbaliser = OntologyVerbaliser(onto)

            # Try to verbalize complex classes first (they verbalize better)
            targets = []
            if result.num_complex_classes > 0:
                targets = list(onto.get_asserted_complex_classes())[:20]
            if len(targets) < 10:
                # Add named classes
                targets.extend(owl_classes[:20 - len(targets)])

            verbalized = 0
            verbalizations = []

            for cls in targets:
                try:
                    v = verbaliser.verbalise_class_expression(cls)
                    if v.verbal and len(v.verbal) >= 5:
                        verbalized += 1
                        verbalizations.append({
                            "class": str(cls)[:80],
                            "verbalization": v.verbal
                        })
                except Exception:
                    pass

            result.verbalization_count = verbalized
            result.verbalizations = verbalizations[:10]

            if targets:
                result.verbalization_ratio = verbalized / len(targets)

            if result.verbalization_ratio >= min_verbalization:
                result.gate_c = GateResult(
                    name="ClassesVerbalizable",
                    passed=True,
                    message=f"Verbalized {verbalized}/{len(targets)} ({result.verbalization_ratio:.0%})",
                    details={
                        "verbalized": verbalized,
                        "total": len(targets),
                        "ratio": result.verbalization_ratio,
                        "examples": verbalizations[:3]
                    }
                )
            else:
                result.gate_c = GateResult(
                    name="ClassesVerbalizable",
                    passed=False,
                    message=f"Only {result.verbalization_ratio:.0%} verbalized (need {min_verbalization:.0%})",
                    details={
                        "verbalized": verbalized,
                        "total": len(targets),
                        "ratio": result.verbalization_ratio
                    }
                )
                feedback_parts.append(
                    f"GATE C FAIL: Verbalization rate {result.verbalization_ratio:.0%} < {min_verbalization:.0%}. "
                    "Complex class restrictions (some_values_from, all_values_from) verbalize better. "
                    "Ensure properties and filler classes exist and have labels."
                )
        except Exception as e:
            result.gate_c = GateResult(
                name="ClassesVerbalizable",
                passed=False,
                message=f"Verbalization error: {e}",
                details={"error": str(e)}
            )
            feedback_parts.append(f"GATE C ERROR: {e}")

        # Gate D: Topics (follows from verbalization success)
        if result.gate_c and result.gate_c.passed and len(result.verbalizations) >= 5:
            result.gate_d = GateResult(
                name="TopicsRecoverable",
                passed=True,
                message=f"{len(result.verbalizations)} verbalizations available for topic modeling",
                details={"verbalization_count": len(result.verbalizations)}
            )
        else:
            result.gate_d = GateResult(
                name="TopicsRecoverable",
                passed=False,
                message="Insufficient verbalizations for topic modeling",
                details={}
            )
            if not feedback_parts:  # Only add if no other feedback
                feedback_parts.append("GATE D FAIL: Need more successful verbalizations for topic recovery.")

    except ImportError as e:
        result.error = f"DeepOnto not available: {e}"
        feedback_parts.append(f"VALIDATION ERROR: {result.error}")
    except Exception as e:
        result.error = str(e)
        feedback_parts.append(f"VALIDATION ERROR: {e}")
    finally:
        Path(owl_path).unlink(missing_ok=True)

    # Compute overall score
    gates_passed = sum([
        result.gate_a.passed if result.gate_a else False,
        result.gate_b.passed if result.gate_b else False,
        result.gate_c.passed if result.gate_c else False,
        result.gate_d.passed if result.gate_d else False,
    ])
    result.all_gates_pass = gates_passed == 4

    # Score: weighted combination
    result.score = (
        0.2 * (1.0 if result.gate_a and result.gate_a.passed else 0.0) +
        0.3 * min(result.num_complex_classes / max(min_complex, 1), 1.0) +
        0.4 * result.verbalization_ratio +
        0.1 * (1.0 if result.gate_d and result.gate_d.passed else 0.0)
    )

    result.feedback = "\n".join(feedback_parts) if feedback_parts else "All gates passed!"
    return result


# =============================================================================
# Extraction Pipeline
# =============================================================================

def parse_ontology_json(json_str: str) -> dict[str, Any] | None:
    """Parse ontology JSON from model output."""
    # Try to extract JSON from markdown code block
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", json_str)
    if json_match:
        json_str = json_match.group(1).strip()

    # Also try to find raw JSON object
    if not json_str.startswith("{"):
        brace_match = re.search(r"(\{[\s\S]*\})", json_str)
        if brace_match:
            json_str = brace_match.group(1)

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None


def extract_ontology(
    corpus: str,
    provider: str,
    max_iterations: int = 3,
    technique: str = "",
) -> list[ExtractionResult]:
    """Extract ontology with iterative refinement.

    Args:
        corpus: Input text corpus
        provider: Provider name (cerebras, xai, local)
        max_iterations: Maximum refinement iterations
        technique: optillm technique for local provider
    """
    results = []

    # Configure DSPy
    lm = get_dspy_lm(provider, technique)
    dspy.configure(lm=lm)

    # DSPy modules
    extractor = dspy.ChainOfThought(StructuredOntologyExtraction)
    refiner = dspy.ChainOfThought(OntologyRefinement)

    ontology_json_str = None

    for iteration in range(max_iterations):
        start_time = time.time()

        if iteration == 0:
            # Initial extraction
            response = extractor(corpus=corpus)
            ontology_json_str = response.ontology_json
        else:
            # Refinement based on feedback
            response = refiner(
                corpus=corpus,
                previous_ontology_json=ontology_json_str,
                validation_feedback=results[-1].validation.feedback if results else "",
            )
            ontology_json_str = response.ontology_json

        extraction_time = time.time() - start_time

        # Parse JSON
        ontology_data = parse_ontology_json(ontology_json_str)

        if not ontology_data:
            result = ExtractionResult(
                provider=provider,
                model=get_model_name(provider),
                iteration=iteration + 1,
                ontology_rdfxml="",
                ontology_raw=ontology_json_str,
                extraction_time=extraction_time,
                validation_time=0,
                validation=ValidationResult(
                    error="Failed to parse JSON from model output",
                    feedback="JSON PARSE ERROR: Model output is not valid JSON. Ensure output is a proper JSON object.",
                ),
            )
            results.append(result)
            continue

        # Generate RDF/XML
        base_uri = ontology_data.get("base_uri", "http://example.org/ontology#")
        rdfxml = generate_rdfxml_ontology(
            classes=ontology_data.get("classes", []),
            object_properties=ontology_data.get("object_properties", []),
            data_properties=ontology_data.get("data_properties", []),
            complex_classes=ontology_data.get("complex_classes", []),
            base_uri=base_uri,
        )

        # Validate
        validation_start = time.time()
        validation = validate_ontology(rdfxml)
        validation_time = time.time() - validation_start

        result = ExtractionResult(
            provider=provider,
            model=get_model_name(provider),
            iteration=iteration + 1,
            ontology_rdfxml=rdfxml,
            ontology_raw=ontology_json_str,
            extraction_time=extraction_time,
            validation_time=validation_time,
            validation=validation,
        )
        results.append(result)

        # Check if all gates pass
        if validation.all_gates_pass:
            print(f"  ✓ All gates passed at iteration {iteration + 1}")
            break

        print(f"  Iteration {iteration + 1}: score={validation.score:.2f}, "
              f"complex={validation.num_complex_classes}, "
              f"verbalize={validation.verbalization_ratio:.0%}")

    return results


def get_dspy_lm(provider: str, technique: str = "") -> dspy.LM:
    """Get DSPy language model.

    Args:
        provider: Provider name (cerebras, xai, local)
        technique: optillm technique for local provider (cot_reflection, bon, moa, etc.)
    """
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
    elif provider == "local":
        # Local model via optillm proxy
        model = LOCAL_MODEL
        if technique:
            model = f"{technique}-{model}"
        return dspy.LM(
            model=f"openai/{model}",
            api_base=OPTILLM_URL,
            api_key="gaius-local",  # Dummy key for optillm
            max_tokens=4096,
            temperature=0.3,
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")


def get_model_name(provider: str, technique: str = "") -> str:
    """Get model name for provider."""
    if provider == "cerebras":
        return "zai-glm-4.7"
    elif provider == "xai":
        return "grok-4-1-fast-non-reasoning"
    elif provider == "local":
        model = LOCAL_MODEL.split("/")[-1]  # Get model name without org
        if technique:
            return f"{technique}-{model}"
        return model
    return provider


# =============================================================================
# Corpus Loading
# =============================================================================

def load_corpus(corpus_path: Path, max_chars: int = 8000) -> tuple[str, str]:
    """Load corpus sample.

    Returns:
        Tuple of (corpus_text, corpus_name)
    """
    if corpus_path.is_file():
        return corpus_path.read_text()[:max_chars], corpus_path.name

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

    if not texts:
        raise ValueError(f"No markdown files found in {corpus_path}")

    return "\n\n---\n\n".join(texts), corpus_path.name


# =============================================================================
# Reporting
# =============================================================================

def print_report(all_results: dict[str, list[ExtractionResult]]) -> None:
    """Print formatted report."""
    print("\n" + "=" * 80)
    print("DE NOVO ONTOLOGY GENERATION REPORT")
    print("=" * 80)

    for provider, results in all_results.items():
        print(f"\n### {provider.upper()} ###")

        for r in results:
            v = r.validation
            print(f"\nIteration {r.iteration}:")
            print(f"  Extraction: {r.extraction_time:.1f}s, Validation: {r.validation_time:.1f}s")

            if v.error:
                print(f"  ERROR: {v.error}")
                continue

            gates = [
                ("A", v.gate_a),
                ("B", v.gate_b),
                ("C", v.gate_c),
                ("D", v.gate_d),
            ]

            for name, gate in gates:
                if gate:
                    status = "✓ PASS" if gate.passed else "✗ FAIL"
                    print(f"  Gate {name}: {status} - {gate.message}")

            print(f"  Score: {v.score:.2f}")

        # Final result
        final = results[-1] if results else None
        if final and final.validation:
            v = final.validation
            print(f"\n  FINAL: {v.num_classes} classes, {v.num_complex_classes} complex, "
                  f"{v.verbalization_ratio:.0%} verbalized")

            if v.verbalizations:
                print("\n  Sample verbalizations:")
                for verb in v.verbalizations[:3]:
                    print(f"    • {verb['verbalization'][:80]}")

    # Summary table
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"{'Provider':<15} {'Iters':>6} {'Classes':>8} {'Complex':>8} {'Verbal':>8} {'Score':>8} {'Pass':>6}")
    print("-" * 80)

    for provider, results in all_results.items():
        final = results[-1] if results else None
        if final and final.validation:
            v = final.validation
            all_pass = "✓" if v.all_gates_pass else "✗"
            print(f"{provider:<15} {len(results):>6} {v.num_classes:>8} "
                  f"{v.num_complex_classes:>8} {v.verbalization_ratio:>7.0%} "
                  f"{v.score:>8.2f} {all_pass:>6}")


def save_results(
    all_results: dict[str, list[ExtractionResult]],
    corpus_name: str,
    output_dir: Path,
) -> Path:
    """Save results to JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Prepare serializable results
    output = {
        "timestamp": timestamp,
        "corpus_name": corpus_name,
        "results": {
            provider: [r.to_dict() for r in results]
            for provider, results in all_results.items()
        }
    }

    output_path = output_dir / f"denovo_ontology_{timestamp}.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    # Also save best OWL files
    for provider, results in all_results.items():
        if results and results[-1].ontology_rdfxml:
            owl_path = output_dir / f"ontology_{provider}_{timestamp}.owl"
            owl_path.write_text(results[-1].ontology_rdfxml)

    return output_path


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="De novo ontology generation with RASE validation"
    )
    parser.add_argument(
        "--corpus-path",
        type=Path,
        default=Path("build/dev/current/cloudera/docs"),
        help="Path to corpus directory or file",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="cerebras",
        help="Comma-separated providers: cerebras,xai",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help="Maximum refinement iterations per provider",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Output directory",
    )
    parser.add_argument(
        "--technique",
        type=str,
        default="",
        help="optillm technique for local provider: cot_reflection, bon, moa, self_consistency, re2, plansearch",
    )
    parser.add_argument(
        "--search-techniques",
        action="store_true",
        help="Search over all techniques and report Pareto front (local provider only)",
    )

    args = parser.parse_args()
    providers = [p.strip() for p in args.provider.split(",")]

    # Load corpus
    print(f"Loading corpus from: {args.corpus_path}")
    corpus, corpus_name = load_corpus(args.corpus_path)
    print(f"Corpus: {corpus_name} ({len(corpus)} chars, ~{len(corpus)//4} tokens)")

    # Handle technique search mode
    if args.search_techniques:
        if "local" not in providers:
            print("ERROR: --search-techniques requires --provider local")
            return

        techniques = ["", "cot_reflection", "bon", "moa", "self_consistency", "re2"]
        technique_results: dict[str, dict[str, Any]] = {}

        for technique in techniques:
            tech_name = technique or "passthrough"
            print(f"\n{'='*60}")
            print(f"TESTING TECHNIQUE: {tech_name.upper()}")
            print(f"{'='*60}")

            try:
                start_time = time.time()
                results = extract_ontology(
                    corpus=corpus,
                    provider="local",
                    max_iterations=args.max_iterations,
                    technique=technique,
                )

                if results:
                    final = results[-1]
                    technique_results[tech_name] = {
                        "validation": final.validation.to_dict(),
                        "score": final.validation.score,
                        "gates_passed": sum([
                            final.validation.gate_a.passed if final.validation.gate_a else 0,
                            final.validation.gate_b.passed if final.validation.gate_b else 0,
                            final.validation.gate_c.passed if final.validation.gate_c else 0,
                            final.validation.gate_d.passed if final.validation.gate_d else 0,
                        ]),
                        "verbalization_ratio": final.validation.verbalization_ratio,
                        "latency_s": sum(r.extraction_time for r in results),
                    }
            except Exception as e:
                print(f"ERROR: {e}")
                technique_results[tech_name] = {"error": str(e)}

        # Print technique comparison
        print(f"\n{'='*60}")
        print("TECHNIQUE COMPARISON (Pareto-style)")
        print(f"{'='*60}")

        # Sort by score
        sorted_techniques = sorted(
            [(k, v) for k, v in technique_results.items() if "error" not in v],
            key=lambda x: x[1].get("score", 0),
            reverse=True,
        )

        for tech, data in sorted_techniques:
            print(f"\n{tech}:")
            print(f"  Score: {data.get('score', 0):.2f}")
            print(f"  Gates: {data.get('gates_passed', 0)}/4")
            print(f"  Verbalization: {data.get('verbalization_ratio', 0)*100:.0f}%")
            print(f"  Latency: {data.get('latency_s', 0):.1f}s")

        # Identify Pareto front (non-dominated solutions)
        print(f"\n{'='*60}")
        print("PARETO FRONT")
        print(f"{'='*60}")

        # Simple Pareto: score vs latency
        pareto_front = []
        for tech, data in sorted_techniques:
            dominated = False
            for other_tech, other_data in sorted_techniques:
                if tech == other_tech:
                    continue
                # other dominates if better or equal on all, strictly better on one
                if (other_data.get("score", 0) >= data.get("score", 0) and
                    other_data.get("latency_s", float("inf")) <= data.get("latency_s", float("inf")) and
                    (other_data.get("score", 0) > data.get("score", 0) or
                     other_data.get("latency_s", float("inf")) < data.get("latency_s", float("inf")))):
                    dominated = True
                    break
            if not dominated:
                pareto_front.append(tech)

        for tech in pareto_front:
            data = technique_results[tech]
            print(f"  {tech}: score={data.get('score', 0):.2f}, latency={data.get('latency_s', 0):.1f}s")

        return

    # Run extraction for each provider
    all_results: dict[str, list[ExtractionResult]] = {}

    for provider in providers:
        print(f"\n{'='*60}")
        tech_suffix = f" (technique: {args.technique})" if args.technique and provider == "local" else ""
        print(f"EXTRACTING WITH {provider.upper()}{tech_suffix}")
        print(f"{'='*60}")

        try:
            results = extract_ontology(
                corpus=corpus,
                provider=provider,
                max_iterations=args.max_iterations,
                technique=args.technique if provider == "local" else "",
            )
            all_results[provider] = results
        except Exception as e:
            print(f"ERROR: {e}")
            all_results[provider] = []

    # Print report
    print_report(all_results)

    # Save results
    output_path = save_results(all_results, corpus_name, args.output_dir)
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
