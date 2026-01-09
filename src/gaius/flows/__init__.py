"""Gaius Flows - Metaflow-based data pipelines with lineage tracking.

This module provides Metaflow flows integrated with Gaius infrastructure:
- Devenv PostgreSQL and MinIO for storage
- Apache AGE graph for lineage tracking
- KB integration for output artifacts

Available flows:
- ArxivDoclingFlow: Fetch arXiv paper, convert PDF to markdown, save to KB
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


_register_builtin_flows()


__all__ = ["GaiusFlow", "FLOW_REGISTRY", "register_flow"]
