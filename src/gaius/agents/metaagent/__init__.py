"""MetaAgent - Agent-driven collaborative interfaces for Gaius.

This module provides infrastructure for:
- Projecting Metaflow flows onto NiFi canvas for visualization
- Populating analytics tables for Metabase dashboards
- Integrating agent-to-UI communication patterns

Components:
- nifi/: NiFi REST API client and flow projection
- metaflow/: Metaflow flow parsing and DAG extraction
- flows/: MetaSyncFlow for populating meta.* tables
"""

from .config import MetaAgentConfig

__all__ = ["MetaAgentConfig"]
