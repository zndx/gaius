"""Gaius Engine - Centralized inference and evolution daemon.

The gaius-engine daemon provides:
- GPU orchestration and vLLM process management
- Inference job scheduling with optillm/vLLM backend routing
- Agent evolution daemon
- Grid projection and TDA computation
- Health monitoring and metrics broadcast

Communication with clients (TUI, CLI, MCP) is via Aeron IPC.

LAZY PACKAGE (PEP 562). Importing `gaius.engine` must NOT eagerly pull `.server`
(and thereby the whole engine — ~5.8s CPU, ~885 MB RSS). It is imported as a
*parent package* every time anything under `gaius.engine.generated.*` (the
protobuf stubs) is imported — the readiness probe (`scripts/zndx_status_ok.py`,
every 10s), `scripts/engine_serving_probe.py`, and the workload watchdog all pay
that. So attributes resolve on first access instead: `from gaius.engine import
GaiusEngine` and `import gaius.engine; gaius.engine.services` still work, but
`import gaius.engine.generated.zndx...` stays light.
"""
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

_SUBMODULES = {"backends", "compute", "resources", "services", "transport"}
_ATTR_SOURCE = {
    "EngineConfig": ".config",
    "AgentConfig": ".config",
    "load_config": ".config",
    "GaiusEngine": ".server",
    "main": ".server",
}

__all__ = [
    "EngineConfig",
    "AgentConfig",
    "load_config",
    "GaiusEngine",
    "main",
    "backends",
    "compute",
    "resources",
    "services",
    "transport",
]


def __getattr__(name: str):
    """PEP 562 lazy attribute resolution — imports the backing module on demand."""
    if name in _SUBMODULES:
        return importlib.import_module(f".{name}", __name__)
    source = _ATTR_SOURCE.get(name)
    if source is not None:
        module = importlib.import_module(source, __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)


if TYPE_CHECKING:  # static analysers still see the real symbols; not run at import
    from . import backends, compute, resources, services, transport
    from .config import AgentConfig, EngineConfig, load_config
    from .server import GaiusEngine, main
