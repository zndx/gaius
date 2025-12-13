"""Gaius - Spatial Intelligence Interface.

A CLI-first terminal interface for navigating complex, graph-oriented data domains.
Renders high-dimensional embeddings and topological structures onto a constrained grid.
"""

__version__ = "0.2.0"

# Lazy imports to avoid slow startup
# Import these explicitly when needed:
#   from gaius.app import GaiusApp, main
#   from gaius.core.state import AppState, ViewMode, OverlayMode


def __getattr__(name: str):
    """Lazy import for backward compatibility."""
    if name in ("AppState", "ViewMode", "OverlayMode"):
        from .core.state import AppState, ViewMode, OverlayMode
        return {"AppState": AppState, "ViewMode": ViewMode, "OverlayMode": OverlayMode}[name]
    elif name == "GaiusApp":
        from .app import GaiusApp
        return GaiusApp
    elif name == "main":
        from .app import main
        return main
    raise AttributeError(f"module 'gaius' has no attribute {name!r}")


__all__ = [
    "AppState",
    "ViewMode",
    "OverlayMode",
    "GaiusApp",
    "main",
]
