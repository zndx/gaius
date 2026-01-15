"""Search flow package with Metaflow-based multi-phase execution.

Provides SearchFlow for robust, production-ready search with:
- Orchestrator-managed endpoint changeovers
- Parallel local + Grok synthesis via branch/join
- Progress streaming via stdout for TUI integration
- Lineage tracking via Apache AGE graph

Usage:
    # Via TUI (preferred)
    /search flatbuffers
    /search --local flatbuffers  # Skip Grok synthesis

    # Direct Metaflow
    uv run python src/gaius/flows/search/flow.py run --query "flatbuffers"
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .flow import SearchFlow

# Lazy imports to avoid circular dependencies
def __getattr__(name: str):
    if name == "SearchFlow":
        from .flow import SearchFlow
        return SearchFlow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["SearchFlow"]
