"""MetaAgent flows for populating analytics tables.

These flows sync operational data to the meta.* schema for
Metabase dashboards.
"""

from .meta_sync import MetaSyncFlow

__all__ = ["MetaSyncFlow"]
