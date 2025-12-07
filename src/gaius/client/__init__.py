"""Engine client library for TUI/CLI/MCP.

Provides thin wrappers that communicate with gaius-engine via gRPC.

The gRPC client implements KServe OIP v2 and is the only supported transport.
"""

from .grpc_client import (
    GrpcClientConfig,
    GrpcEngineClient,
    call_grpc,
    get_grpc_client,
)
from .engine_proxy import (
    CompletionResult,
    EvolutionProxy,
    GridProxy,
    HealthProxy,
    OrchestratorProxy,
    SchedulerProxy,
    TDAProxy,
    get_evolution_proxy,
    get_grid_proxy,
    get_health_proxy,
    get_orchestrator_proxy,
    get_scheduler_proxy,
    get_tda_proxy,
    use_engine_proxy,
)


async def get_engine_client():
    """Get the gRPC engine client.

    Returns:
        GrpcEngineClient instance

    Raises:
        ConnectionError: If connection fails
    """
    client = GrpcEngineClient()
    if await client.connect():
        return client

    raise ConnectionError(
        "Failed to connect to engine via gRPC. Is gaius-engine running? "
        "Start with: devenv up"
    )


__all__ = [
    # gRPC Client
    "GrpcClientConfig",
    "GrpcEngineClient",
    "call_grpc",
    "get_grpc_client",
    "get_engine_client",
    # Proxies
    "CompletionResult",
    "EvolutionProxy",
    "GridProxy",
    "HealthProxy",
    "OrchestratorProxy",
    "SchedulerProxy",
    "TDAProxy",
    "get_evolution_proxy",
    "get_grid_proxy",
    "get_health_proxy",
    "get_orchestrator_proxy",
    "get_scheduler_proxy",
    "get_tda_proxy",
    "use_engine_proxy",
]
