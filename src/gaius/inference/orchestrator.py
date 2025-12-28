"""GPU Orchestrator - DEPRECATED.

This module is deprecated. Use engine gRPC for GPU orchestration.

Engine Federation Architecture:
- All GPU operations go through engine gRPC (co-located with GPUs)
- Thin clients (TUI/CLI/MCP) use engine proxy, not local orchestrator
- ProcessStatus is now defined in protobuf: gaius.engine.generated.ProcessStatus

Migration:
    # OLD (deprecated):
    from gaius.inference.orchestrator import get_orchestrator
    orch = get_orchestrator()
    await orch.start_endpoint("reasoning")

    # NEW:
    from gaius.client.engine_proxy import get_orchestrator_proxy
    proxy = await get_orchestrator_proxy()
    result = await proxy.ensure_endpoint("reasoning")

Guru Meditation: #IN.00000001.ORCHDEP
"""

import logging
import warnings

logger = logging.getLogger(__name__)

# Re-export ProcessStatus from generated protobuf for backwards compatibility
# This is the ONLY export that remains valid - now uses the shared protobuf enum
from enum import Enum

try:
    from ..engine.generated import (
        ProcessStatus as ProtoProcessStatus,
        PROCESS_STATUS_STOPPED,
        PROCESS_STATUS_STARTING,
        PROCESS_STATUS_HEALTHY,
        PROCESS_STATUS_UNHEALTHY,
        PROCESS_STATUS_STOPPING,
        PROCESS_STATUS_FAILED,
    )

    # Create a Python-friendly enum that wraps the protobuf values
    class ProcessStatus(Enum):
        """vLLM process status (backed by protobuf enum)."""
        STOPPED = PROCESS_STATUS_STOPPED
        STARTING = PROCESS_STATUS_STARTING
        HEALTHY = PROCESS_STATUS_HEALTHY
        UNHEALTHY = PROCESS_STATUS_UNHEALTHY
        STOPPING = PROCESS_STATUS_STOPPING
        FAILED = PROCESS_STATUS_FAILED

        @classmethod
        def from_proto(cls, proto_value: int) -> "ProcessStatus":
            """Convert protobuf enum value to ProcessStatus."""
            for member in cls:
                if member.value == proto_value:
                    return member
            return cls.STOPPED

        @classmethod
        def from_string(cls, s: str) -> "ProcessStatus":
            """Convert string to ProcessStatus (e.g., 'healthy' -> HEALTHY)."""
            try:
                return cls[s.upper()]
            except KeyError:
                return cls.STOPPED

except ImportError:
    # Fallback if generated protobuf not available - define minimal enum
    class ProcessStatus(Enum):
        """vLLM process status (fallback when protobuf unavailable)."""
        STOPPED = 1
        STARTING = 2
        HEALTHY = 3
        UNHEALTHY = 4
        STOPPING = 5
        FAILED = 6

        @classmethod
        def from_proto(cls, proto_value: int) -> "ProcessStatus":
            """Convert protobuf enum value to ProcessStatus."""
            for member in cls:
                if member.value == proto_value:
                    return member
            return cls.STOPPED

        @classmethod
        def from_string(cls, s: str) -> "ProcessStatus":
            """Convert string to ProcessStatus (e.g., 'healthy' -> HEALTHY)."""
            try:
                return cls[s.upper()]
            except KeyError:
                return cls.STOPPED


def get_orchestrator():
    """DEPRECATED: Use engine gRPC instead.

    Raises:
        RuntimeError: Always - this function is deprecated

    Migration:
        from gaius.client.engine_proxy import get_orchestrator_proxy
        proxy = await get_orchestrator_proxy()
    """
    raise RuntimeError(
        "get_orchestrator() is deprecated (#IN.00000001.ORCHDEP). "
        "Engine Federation Architecture requires using engine gRPC. "
        "Use: from gaius.client.engine_proxy import get_orchestrator_proxy"
    )


def get_orchestrator_status():
    """DEPRECATED: Use engine gRPC instead.

    Raises:
        RuntimeError: Always - this function is deprecated

    Migration:
        from gaius.client.engine_proxy import get_orchestrator_proxy
        proxy = await get_orchestrator_proxy()
        status = await proxy._get_status_async()
    """
    raise RuntimeError(
        "get_orchestrator_status() is deprecated (#IN.00000001.ORCHDEP). "
        "Engine Federation Architecture requires using engine gRPC. "
        "Use: from gaius.client.engine_proxy import get_orchestrator_proxy"
    )


# Legacy type stubs for import compatibility (will fail at runtime)
class EndpointConfig:
    """DEPRECATED: Use engine config instead."""
    def __init__(self, *args, **kwargs):
        raise RuntimeError(
            "EndpointConfig is deprecated (#IN.00000001.ORCHDEP). "
            "Use engine configuration via gaius.engine.config"
        )


class VLLMProcess:
    """DEPRECATED: Use engine backends instead."""
    def __init__(self, *args, **kwargs):
        raise RuntimeError(
            "VLLMProcess is deprecated (#IN.00000001.ORCHDEP). "
            "Use gaius.engine.backends.VLLMProcess"
        )


class GPUOrchestrator:
    """DEPRECATED: Use engine orchestrator service instead."""
    def __init__(self, *args, **kwargs):
        raise RuntimeError(
            "GPUOrchestrator is deprecated (#IN.00000001.ORCHDEP). "
            "Engine Federation Architecture handles GPU orchestration. "
            "Use: from gaius.client.engine_proxy import get_orchestrator_proxy"
        )


# Emit deprecation warning on module import
warnings.warn(
    "gaius.inference.orchestrator is deprecated. "
    "Use engine gRPC for GPU orchestration (#IN.00000001.ORCHDEP). "
    "Only ProcessStatus re-export remains valid.",
    DeprecationWarning,
    stacklevel=2,
)

logger.warning(
    "Deprecated module imported: gaius.inference.orchestrator (#IN.00000001.ORCHDEP). "
    "Migrate to engine gRPC. Only ProcessStatus is valid."
)
