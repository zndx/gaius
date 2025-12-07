"""Compute services (grid projection, TDA)."""

from .tda_service import TDARequest, TDAResult, TDAService
from .grid_service import GridPoint, GridService, ProjectionRequest, ProjectionResult

__all__ = [
    # TDA
    "TDARequest",
    "TDAResult",
    "TDAService",
    # Grid
    "GridPoint",
    "GridService",
    "ProjectionRequest",
    "ProjectionResult",
]
