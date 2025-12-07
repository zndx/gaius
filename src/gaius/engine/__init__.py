"""Gaius Engine - Centralized inference and evolution daemon.

The gaius-engine daemon provides:
- GPU orchestration and vLLM process management
- Inference job scheduling with optillm/vLLM backend routing
- Agent evolution daemon
- Grid projection and TDA computation
- Health monitoring and metrics broadcast

Communication with clients (TUI, CLI, MCP) is via Aeron IPC.
"""

from .config import EngineConfig, AgentConfig, load_config
from .server import GaiusEngine, main

# Re-export submodules for convenient access
from . import backends
from . import compute
from . import resources
from . import services
from . import transport

__all__ = [
    # Config
    "EngineConfig",
    "AgentConfig",
    "load_config",
    # Server
    "GaiusEngine",
    "main",
    # Submodules
    "backends",
    "compute",
    "resources",
    "services",
    "transport",
]
