"""One-shot xAI review of introduction.md via ExternalInferenceRouter."""

import asyncio


async def main():
    from gaius.engine.backends.external.router import get_external_router

    router = get_external_router()

    system_prompt = (
        "You are an expert reviewer of technical documentation targeting TDA researchers "
        "at NVIDIA GTC 2026 — specifically, people from Gunnar Carlsson's lab at BluelightAI "
        "who understand persistent homology, Rips complexes, and discrete curvature deeply. "
        "Provide: (1) assessment of mathematical precision, (2) clarity/flow, "
        "(3) tone, (4) specific actionable improvements. Be direct and specific."
    )

    from pathlib import Path
    content = (Path(__file__).parent.parent / "docs/current/src/introduction.md").read_text()

    context = (
        "Gaius is a real 252K-line Python system. TDA uses ripser (Vietoris-Rips persistent homology), "
        "GraphRicciCurvature (Ollivier-Ricci), UMAP for projection. Gunnar Carlsson invented persistent homology."
    )

    prompt = f"## Context\n{context}\n\n## Document to Review\n{content}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    response = await router.complete(
        messages=messages,
        provider="xai",
        max_tokens=4096,
        temperature=0.3,
    )

    if response.error:
        print(f"ERROR: {response.error}")
    else:
        print(f"Model: {response.model}")
        print(f"Tokens: {response.input_tokens} in / {response.output_tokens} out")
        print(f"Latency: {response.latency_ms}ms")
        print("---")
        print(response.content)


asyncio.run(main())
