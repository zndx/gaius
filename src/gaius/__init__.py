"""Gaius - Spatial Intelligence Interface.

A CLI-first terminal interface for navigating complex, graph-oriented data domains.
Renders high-dimensional embeddings and topological structures onto a constrained grid.
"""

__version__ = "0.2.0"

from .core.state import AppState, ViewMode, OverlayMode
from .app import GaiusApp, main

__all__ = [
    "AppState",
    "ViewMode",
    "OverlayMode",
    "GaiusApp",
    "main",
]
