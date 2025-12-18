"""NiFi integration for MetaAgent.

Provides REST API client and flow projection for visualizing
Metaflow pipelines on the NiFi canvas.
"""

from .client import NiFiClient
from .projector import MetaflowToNiFiProjector

__all__ = ["NiFiClient", "MetaflowToNiFiProjector"]
