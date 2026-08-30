"""Search clients: Brave web search, BM25 lexical, multi-vector semantic.

Pure retrieval — no LLM inference lives here. (Embedding model forward
passes live in ``gaius.engine.embeddings``; inference is consumed only via
the engine gRPC.)
"""

import os

from .brave import BraveSearch, SearchResult
from .bm25 import KBSearch, KBSearchResult, KBDocument, get_kb_search
from .vector import VectorSearch, VectorSearchResult, get_vector_search

__all__ = [
    # Brave web search
    "BraveSearch",
    "SearchResult",
    "get_search",
    # BM25 lexical search
    "KBSearch",
    "KBSearchResult",
    "KBDocument",
    "get_kb_search",
    # Vector semantic search
    "VectorSearch",
    "VectorSearchResult",
    "get_vector_search",
]

# Module-level singleton (lazy initialized)
_search: BraveSearch | None = None


def get_search() -> BraveSearch:
    """Get or create the Brave web-search client singleton.

    Key resolution: BRAVE_API_KEY env, then HOCON providers.brave.api_key.
    """
    global _search
    if _search is None:
        api_key = os.getenv("BRAVE_API_KEY")
        if not api_key:
            from gaius.core.config import get_config

            api_key = get_config().providers.brave.api_key
        if not api_key:
            raise RuntimeError(
                "#SR.00000001.NOBRAVEKEY: Brave API key not configured.\n"
                "  Set BRAVE_API_KEY or providers.brave.api_key in HOCON config"
            )
        _search = BraveSearch(api_key)
    return _search
