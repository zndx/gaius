"""MCP operations module.

Provides programmatic access to MCP tool operations
for internal use by agents and other components.
"""

from .operations import ask_reasoning, run_swarm

__all__ = ["ask_reasoning", "run_swarm"]
