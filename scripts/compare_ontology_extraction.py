#!/usr/bin/env python3
"""Compare ontology extraction across multiple models.

Benchmarks de novo ontology extraction from a sample corpus using:
- Local models (vLLM via optillm) - DeepSeek-R1-Distill-Qwen-32B
- Cerebras GLM-4.6 (remote open weights, ~1000 tokens/sec)
- xAI Grok 4.1 fast (closed source frontier model)
- Claude (objective baseline - run separately)

Optionally tests optillm techniques (CoT, best-of-n, etc.)

Usage:
    # Run all comparisons
    uv run python scripts/compare_ontology_extraction.py

    # Specific models only
    uv run python scripts/compare_ontology_extraction.py --models local,cerebras,grok

    # Include optillm techniques
    uv run python scripts/compare_ontology_extraction.py --optillm-techniques cot_reflection,bon

    # Use specific corpus
    uv run python scripts/compare_ontology_extraction.py --corpus-path build/dev/current/cloudera/docs
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

# =============================================================================
# Configuration
# =============================================================================

OPTILLM_URL = os.getenv("OPTILLM_URL", "http://localhost:8090/v1")
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
CEREBRAS_URL = "https://api.cerebras.ai/v1"
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
XAI_URL = "https://api.x.ai/v1"
# Default local model for ontology extraction
DEFAULT_LOCAL_MODEL = "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B"

# Cerebras GLM model - blazing fast inference at 1000+ tokens/sec
CEREBRAS_MODEL = "zai-glm-4.7"

# xAI Grok model - fast mode with 2M context
GROK_MODEL = "grok-4-1-fast-non-reasoning"

# Extraction prompt template
EXTRACTION_PROMPT = """You are an ontology engineer. Extract a structured ontology from the following technical documentation.

## Instructions

1. Identify the main **concepts** (classes) mentioned in the text
2. Identify **relationships** between concepts (e.g., "is-a", "has-part", "manages", "connects-to")
3. Identify key **properties** of each concept
4. Output the ontology in OWL Manchester Syntax

## Example Output Format

```owl
Prefix: : <http://example.org/ontology#>
Prefix: rdfs: <http://www.w3.org/2000/01/rdf-schema#>

Class: FlinkApplication
    SubClassOf: StreamingApplication
    Annotations: rdfs:label "Flink Application"

Class: StreamingApplication
    Annotations: rdfs:label "Streaming Application"

ObjectProperty: runsOn
    Domain: FlinkApplication
    Range: KubernetesCluster
```

## Documentation to Analyze

{corpus}

## Output

Extract the ontology now. Be thorough but focus on the most important concepts and relationships.
"""


@dataclass
class ExtractionResult:
    """Result from a single model extraction."""
    model_name: str
    provider: str
    technique: str | None  # optillm technique if used

    # Output
    ontology_owl: str
    raw_response: str

    # Metrics
    latency_seconds: float
    input_tokens: int
    output_tokens: int

    # Quality (to be filled in by evaluation)
    num_classes: int = 0
    num_properties: int = 0
    num_relationships: int = 0

    # Errors
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ComparisonRun:
    """A complete comparison run across models."""
    run_id: str
    timestamp: str
    corpus_name: str
    corpus_sample: str  # First 500 chars
    corpus_tokens_approx: int

    results: list[ExtractionResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["results"] = [r.to_dict() for r in self.results]
        return d

    def save(self, output_dir: Path) -> Path:
        """Save results to JSON file."""
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"ontology_comparison_{self.run_id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path


# =============================================================================
# Model Clients
# =============================================================================

async def call_optillm(
    prompt: str,
    model: str = DEFAULT_LOCAL_MODEL,
    technique: str | None = None,
    max_tokens: int = 4096,
    timeout: float = 300.0,
) -> tuple[str, int, int]:
    """Call local model via optillm.

    Args:
        prompt: The prompt to send
        model: Model ID (optionally prefixed with technique)
        technique: optillm technique (cot_reflection, bon, moa, etc.)
        max_tokens: Max tokens to generate
        timeout: Request timeout

    Returns:
        Tuple of (response_text, input_tokens, output_tokens)
    """
    # Optillm technique prefix
    if technique:
        model = f"{technique}-{model}"

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{OPTILLM_URL}/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
        )
        response.raise_for_status()
        data = response.json()

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return content, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


async def call_cerebras(
    prompt: str,
    model: str = CEREBRAS_MODEL,
    max_tokens: int = 4096,
    timeout: float = 120.0,
) -> tuple[str, int, int]:
    """Call Cerebras API (very fast inference)."""
    if not CEREBRAS_API_KEY:
        raise ValueError("CEREBRAS_API_KEY not set")

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{CEREBRAS_URL}/chat/completions",
            headers={"Authorization": f"Bearer {CEREBRAS_API_KEY}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
        )
        response.raise_for_status()
        data = response.json()

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return content, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


async def call_xai(
    prompt: str,
    model: str = GROK_MODEL,
    max_tokens: int = 4096,
    timeout: float = 120.0,
) -> tuple[str, int, int]:
    """Call xAI Grok API."""
    if not XAI_API_KEY:
        raise ValueError("XAI_API_KEY not set")

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{XAI_URL}/chat/completions",
            headers={"Authorization": f"Bearer {XAI_API_KEY}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
        )
        response.raise_for_status()
        data = response.json()

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return content, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


# =============================================================================
# Extraction Logic
# =============================================================================

def extract_owl_from_response(response: str) -> str:
    """Extract OWL content from model response."""
    # Look for ```owl or ```manchester code blocks
    import re

    patterns = [
        r"```owl\s*(.*?)```",
        r"```manchester\s*(.*?)```",
        r"```\s*(Prefix:.*?)```",
    ]

    for pattern in patterns:
        match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()

    # If no code block, return the whole response (might be raw OWL)
    if "Prefix:" in response or "Class:" in response:
        return response

    return ""


def count_ontology_elements(owl_text: str) -> tuple[int, int, int]:
    """Count classes, properties, and relationships in OWL text."""
    import re

    # Count Class: declarations
    classes = len(re.findall(r"^Class:", owl_text, re.MULTILINE))

    # Count ObjectProperty: and DataProperty: declarations
    obj_props = len(re.findall(r"^ObjectProperty:", owl_text, re.MULTILINE))
    data_props = len(re.findall(r"^DataProperty:", owl_text, re.MULTILINE))

    # Count SubClassOf relationships
    subclass_rels = len(re.findall(r"SubClassOf:", owl_text))

    return classes, obj_props + data_props, subclass_rels


async def run_extraction(
    corpus: str,
    provider: str,
    model: str,
    technique: str | None = None,
) -> ExtractionResult:
    """Run ontology extraction with a specific model."""
    prompt = EXTRACTION_PROMPT.format(corpus=corpus)

    start_time = time.time()
    error = None
    response = ""
    input_tokens = 0
    output_tokens = 0

    try:
        if provider == "local":
            response, input_tokens, output_tokens = await call_optillm(
                prompt, model=model, technique=technique
            )
        elif provider == "cerebras":
            response, input_tokens, output_tokens = await call_cerebras(prompt, model=model)
        elif provider == "xai":
            response, input_tokens, output_tokens = await call_xai(prompt, model=model)
        else:
            raise ValueError(f"Unknown provider: {provider}")
    except Exception as e:
        error = str(e)

    latency = time.time() - start_time

    # Extract OWL and count elements
    owl_text = extract_owl_from_response(response) if response else ""
    num_classes, num_props, num_rels = count_ontology_elements(owl_text)

    return ExtractionResult(
        model_name=model,
        provider=provider,
        technique=technique,
        ontology_owl=owl_text,
        raw_response=response,
        latency_seconds=latency,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        num_classes=num_classes,
        num_properties=num_props,
        num_relationships=num_rels,
        error=error,
    )


# =============================================================================
# Corpus Loading
# =============================================================================

def load_corpus_sample(corpus_path: Path, max_chars: int = 8000) -> tuple[str, str]:
    """Load a sample of corpus documents.

    Returns:
        Tuple of (corpus_text, corpus_name)
    """
    if corpus_path.is_file():
        text = corpus_path.read_text()[:max_chars]
        return text, corpus_path.name

    # Directory - concatenate markdown files
    texts = []
    total_chars = 0

    for md_file in sorted(corpus_path.rglob("*.md"))[:10]:  # Max 10 files
        content = md_file.read_text()
        if total_chars + len(content) > max_chars:
            # Truncate this file
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
# Main Comparison
# =============================================================================

async def run_comparison(
    corpus_path: Path,
    models: list[str],
    optillm_techniques: list[str] | None = None,
    output_dir: Path | None = None,
) -> ComparisonRun:
    """Run full comparison across models."""

    # Load corpus
    corpus_text, corpus_name = load_corpus_sample(corpus_path)
    corpus_tokens_approx = len(corpus_text) // 4  # Rough estimate

    run = ComparisonRun(
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S"),
        timestamp=datetime.now().isoformat(),
        corpus_name=corpus_name,
        corpus_sample=corpus_text[:500],
        corpus_tokens_approx=corpus_tokens_approx,
    )

    print(f"=== Ontology Extraction Comparison ===")
    print(f"Corpus: {corpus_name} (~{corpus_tokens_approx} tokens)")
    print(f"Models: {models}")
    if optillm_techniques:
        print(f"optillm techniques: {optillm_techniques}")
    print()

    # Define model configurations
    model_configs = []

    if "local" in models:
        model_configs.append(("local", DEFAULT_LOCAL_MODEL, None))
        # Add optillm techniques
        if optillm_techniques:
            for tech in optillm_techniques:
                model_configs.append(("local", DEFAULT_LOCAL_MODEL, tech))

    if "cerebras" in models:
        model_configs.append(("cerebras", CEREBRAS_MODEL, None))

    if "grok" in models or "xai" in models:
        model_configs.append(("xai", GROK_MODEL, None))

    # Run extractions
    for provider, model, technique in model_configs:
        tech_label = f" ({technique})" if technique else ""
        print(f"Running {provider}/{model}{tech_label}...", end=" ", flush=True)

        result = await run_extraction(corpus_text, provider, model, technique)
        run.results.append(result)

        if result.error:
            print(f"ERROR: {result.error}")
        else:
            print(f"OK ({result.latency_seconds:.1f}s, {result.num_classes} classes, {result.num_properties} props)")

    # Save results
    if output_dir:
        path = run.save(output_dir)
        print(f"\nResults saved to: {path}")

    # Print summary
    print("\n=== Summary ===")
    print(f"{'Model':<40} {'Latency':>8} {'Classes':>8} {'Props':>8} {'Rels':>8}")
    print("-" * 80)
    for r in run.results:
        tech_label = f" ({r.technique})" if r.technique else ""
        name = f"{r.provider}/{r.model_name}{tech_label}"[:40]
        if r.error:
            print(f"{name:<40} {'ERROR':>8}")
        else:
            print(f"{name:<40} {r.latency_seconds:>7.1f}s {r.num_classes:>8} {r.num_properties:>8} {r.num_relationships:>8}")

    return run


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Compare ontology extraction across models")
    parser.add_argument(
        "--corpus-path",
        type=Path,
        default=Path("build/dev/current/cloudera/docs"),
        help="Path to corpus directory or file",
    )
    parser.add_argument(
        "--models",
        type=str,
        default="local,cerebras,grok",
        help="Comma-separated list of models: local,cerebras,grok",
    )
    parser.add_argument(
        "--optillm-techniques",
        type=str,
        default="",
        help="Comma-separated optillm techniques: cot_reflection,bon,moa,rto,z3,self_consistency",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build/dev/scratch/ontology_comparisons"),
        help="Output directory for results",
    )

    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    techniques = [t.strip() for t in args.optillm_techniques.split(",") if t.strip()] or None

    asyncio.run(run_comparison(
        corpus_path=args.corpus_path,
        models=models,
        optillm_techniques=techniques,
        output_dir=args.output_dir,
    ))


if __name__ == "__main__":
    main()
