"""Batch xAI review of architecture pages for GTC 2026 audience."""

import asyncio
import sys
from pathlib import Path


PAGES = [
    "docs/current/src/introduction.md",
    "docs/current/src/architecture/overview.md",
    "docs/current/src/architecture/visualization.md",
    "docs/current/src/architecture/rase.md",
    "docs/current/src/architecture/fmea.md",
]

SYSTEM_PROMPT = (
    "You are an expert reviewer of technical documentation targeting TDA researchers "
    "at NVIDIA GTC 2026 — specifically, people from Gunnar Carlsson's lab at BluelightAI "
    "who understand persistent homology, Rips complexes, and discrete curvature deeply.\n\n"
    "Review criteria:\n"
    "1. Mathematical precision: Are claims about homology, curvature, filtration correct?\n"
    "2. Technical depth: Would a researcher find this credible?\n"
    "3. Tone: Flag promotional or vague language\n"
    "4. Specific improvements: Reference specific lines or sections\n\n"
    "Score each page 1-10 on: precision, depth, tone. Then list specific improvements.\n"
    "Be direct. No flattery."
)

CONTEXT = (
    "Gaius is a real 252K-line Python system deployed on 6 NVIDIA GPUs. "
    "TDA pipeline: ripser (Vietoris-Rips persistent homology over cosine distance), "
    "GraphRicciCurvature (Ollivier-Ricci, OTD method, alpha=0.5), UMAP for projection. "
    "Gunnar Carlsson co-invented persistent homology and co-founded Ayasdi/BluelightAI."
)


async def review_page(router, page_path: str) -> dict:
    """Review a single page and return results."""
    root = Path(__file__).parent.parent
    content = (root / page_path).read_text()

    prompt = f"## Context\n{CONTEXT}\n\n## Page: {page_path}\n\n{content}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    response = await router.complete(
        messages=messages,
        provider="xai",
        max_tokens=4096,
        temperature=0.3,
    )

    return {
        "page": page_path,
        "model": response.model,
        "tokens_in": response.input_tokens,
        "tokens_out": response.output_tokens,
        "latency_ms": response.latency_ms,
        "error": response.error,
        "content": response.content,
    }


async def main():
    from gaius.engine.backends.external.router import get_external_router

    router = get_external_router()

    pages = PAGES
    if len(sys.argv) > 1:
        pages = sys.argv[1:]

    for page_path in pages:
        print(f"\n{'='*80}")
        print(f"REVIEWING: {page_path}")
        print(f"{'='*80}\n")

        result = await review_page(router, page_path)

        if result["error"]:
            print(f"ERROR: {result['error']}")
        else:
            print(f"Model: {result['model']}")
            print(f"Tokens: {result['tokens_in']} in / {result['tokens_out']} out")
            print(f"Latency: {result['latency_ms']}ms")
            print("---")
            print(result["content"])


asyncio.run(main())
