"""Gaius Flows - Metaflow-based data pipelines with lineage tracking.

This module provides Metaflow flows integrated with Gaius infrastructure:
- Devenv PostgreSQL and MinIO for storage
- Apache AGE graph for lineage tracking
- KB integration for output artifacts

Available flows:
- ArxivDoclingFlow: Convert a PDF (arXiv or any URL) to markdown. arXiv →
  KB zettelkasten; generic URL → files in a local output_dir.
"""

from gaius.flows.base import GaiusFlow

# Flow registry for CLI discovery
FLOW_REGISTRY: dict[str, type] = {}


def register_flow(name: str):
    """Decorator to register a flow for CLI discovery."""
    def decorator(cls):
        FLOW_REGISTRY[name] = cls
        return cls
    return decorator


# Auto-register available flows
def _register_builtin_flows():
    """Import builtin flows to register them."""
    try:
        from gaius.flows.docling import ArxivDoclingFlow  # noqa: F401
    except ImportError:
        pass  # docling may not be installed

    try:
        from gaius.flows.prospects import ProspectsCheckFlow, ProspectsUpdateFlow  # noqa: F401
    except ImportError:
        pass  # prospects dependencies may not be installed

    try:
        from gaius.flows.search import SearchFlow  # noqa: F401
    except ImportError:
        pass  # search dependencies may not be installed

    try:
        from gaius.flows.research import ResearchFlow  # noqa: F401
    except ImportError:
        pass  # research dependencies may not be installed

    try:
        from gaius.flows.article_curation import ArticleCurationFlow  # noqa: F401
    except ImportError:
        pass  # article_curation dependencies may not be installed

    try:
        from gaius.flows.card_upkeep import CardUpkeepFlow  # noqa: F401
    except ImportError:
        pass  # card_upkeep dependencies may not be installed

    try:
        from gaius.flows.summary import KnowledgeSummaryFlow  # noqa: F401
    except ImportError:
        pass

    try:
        from gaius.flows.clt_skos import CltSkosEvalFlow  # noqa: F401
    except ImportError:
        pass


_register_builtin_flows()


__all__ = ["GaiusFlow", "FLOW_REGISTRY", "register_flow"]
