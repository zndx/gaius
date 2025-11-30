"""Search clients."""

from .brave import BraveSearch, SearchResult
from .bm25 import KBSearch, KBSearchResult, KBDocument, get_kb_search
from .vector import VectorSearch, VectorSearchResult, get_vector_search

__all__ = [
    # Brave web search
    "BraveSearch",
    "SearchResult",
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
