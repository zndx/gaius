"""Gaius Inference Module.

Provides local-first inference with optillm optimization techniques,
web search via Brave API, and KB population tools.

Usage:
    from gaius.inference import get_client, get_search

    # Inference
    client = get_client()
    response = await client.complete([Message(role="user", content="Hello")])

    # Search
    search = get_search()
    results = await search.search("query")

    # Synthesis
    from gaius.inference import synthesize_search
    note = await synthesize_search(query, kb_results, web_results)
"""

from .config import InferenceConfig, InferenceBackend, OptillmTechnique
from .client import InferenceClient, Message, CompletionResult
from .synthesis import (
    ZettelkastenSynthesizer,
    ZettelkastenNote,
    Citation,
    synthesize_search,
)
from .evaluation import (
    SynthesisEvaluator,
    EvaluationResult,
    DimensionScore,
    evaluate_synthesis,
    load_evaluations,
    compute_aggregate_scores,
    EVAL_DIMENSIONS,
)

__all__ = [
    # Config
    "InferenceConfig",
    "InferenceBackend",
    "OptillmTechnique",
    # Client
    "InferenceClient",
    "Message",
    "CompletionResult",
    # Synthesis
    "ZettelkastenSynthesizer",
    "ZettelkastenNote",
    "Citation",
    "synthesize_search",
    # Evaluation
    "SynthesisEvaluator",
    "EvaluationResult",
    "DimensionScore",
    "evaluate_synthesis",
    "load_evaluations",
    "compute_aggregate_scores",
    "EVAL_DIMENSIONS",
    # Factory functions
    "get_client",
    "get_search",
    "ask_local",
]

# Module-level singletons (lazy initialized)
_client: InferenceClient | None = None
_search = None  # Will be BraveSearch when implemented


def get_client(config: InferenceConfig | None = None) -> InferenceClient:
    """Get or create the inference client singleton.

    .. deprecated::
        Use `gaius.client.get_grpc_client()` instead. This function will be
        removed in a future version. See Issue #8.

        Migration example::

            # Before
            from gaius.inference import get_client, Message
            client = get_client()
            result = await client.complete([Message(role="user", content="...")])

            # After
            from gaius.client import get_grpc_client
            client = await get_grpc_client()
            result = await client.call(
                service="Scheduler",
                action="complete",
                params={"prompt": "...", "agent": "instruct"},
            )
    """
    import warnings
    warnings.warn(
        "get_client() is deprecated. Use gaius.client.get_grpc_client() instead. "
        "See Issue #8 for migration guide.",
        DeprecationWarning,
        stacklevel=2,
    )
    global _client
    if _client is None:
        _client = InferenceClient(config or InferenceConfig.from_env())
    return _client


def get_search():
    """Get or create the search client singleton."""
    global _search
    if _search is None:
        from .search.brave import BraveSearch

        config = InferenceConfig.from_env()
        if config.brave_api_key:
            _search = BraveSearch(config.brave_api_key)
        else:
            raise RuntimeError("BRAVE_API_KEY not set")
    return _search


async def ask_local(
    question: str,
    technique: str = "",
    max_tokens: int = 2048,
) -> str:
    """Query local LLM via the gRPC engine.

    Uses the engine-centric architecture for all inference.

    Args:
        question: The question or prompt
        technique: optillm technique (cot_reflection, bon, moa, etc.) - empty for passthrough
        max_tokens: Maximum tokens to generate

    Returns:
        LLM response text
    """
    from gaius.client import get_grpc_client

    client = await get_grpc_client()
    result = await client.call(
        service="scheduler",
        action="complete",
        params={
            "agent": "instruct",  # Use instruct agent for quick queries
            "prompt": question,
            "max_tokens": max_tokens,
        },
    )
    return result.get("content", "")
