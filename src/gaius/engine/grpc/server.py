"""gRPC server for Gaius Engine.

Provides the main gRPC server that hosts:
- KServe Open Inference Protocol (GRPCInferenceService)
- Gaius custom extensions (GaiusService)
- zndx.engine.v1.Engine (Signals lattice federation face)

This is the primary transport for gaius-engine, designed to:
- Be OIP-compliant for Cloudera/KServe compatibility
- Support streaming for health metrics and events
- Handle high-throughput inference requests
- Scale from local tinybox to HPC clusters
"""

import asyncio
import logging
from concurrent import futures
from dataclasses import dataclass
from typing import Any, Callable, Optional

import grpc
from grpc import aio

from ..generated import (
    add_GRPCInferenceServiceServicer_to_server,
    add_GaiusServiceServicer_to_server,
)
from ..generated.zndx.engine.v1 import engine_pb2_grpc as zpb_grpc
from .servicers import InferenceServicer, GaiusServicer, GaiusZndxEngineServicer

logger = logging.getLogger(__name__)


@dataclass
class GrpcConfig:
    """Configuration for the gRPC server."""

    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 50051
    max_workers: int = 10
    max_message_size: int = 100 * 1024 * 1024  # 100MB for large tensors
    reflection_enabled: bool = True  # Enable gRPC reflection for debugging

    @classmethod
    def from_dict(cls, d: dict) -> "GrpcConfig":
        """Create config from dictionary."""
        return cls(
            enabled=d.get("enabled", True),
            host=d.get("host", "0.0.0.0"),
            port=d.get("port", 50051),
            max_workers=d.get("max_workers", 10),
            max_message_size=d.get("max_message_size", 100 * 1024 * 1024),
            reflection_enabled=d.get("reflection_enabled", True),
        )


@dataclass
class ServiceRegistry:
    """Registry of backend services for gRPC handlers to use."""

    # Backend router for inference
    backend_router: Any = None

    # Engine scheduler service (priority job queue over the backend router)
    scheduler_service: Any = None

    # Orchestrator service for endpoint management
    orchestrator_service: Any = None

    # Shared asyncpg pool (set after gRPC bind; cognition starts later)
    db_pool: Any = None

    # Cognition service for thought generation
    cognition_service: Any = None

    # Dataset service for NiFi SoM/ToM generation
    dataset_service: Any = None

    # Topology service for temporal dynamics tracking
    topology_service: Any = None

    # Health service for basic metrics
    health_service: Any = None

    # Health observer service for autonomous FMEA monitoring + ACP
    health_observer_service: Any = None

    # Nautilus service — Overwatch's model-free detector (ACP+Grok judge)
    nautilus_service: Any = None
    # (2026-09-04) EngineSupervision stream: the in-process event bus and the task
    # processor (live-run knowledge the directive handler consults).
    supervision_bus: Any = None
    scheduled_task_processor: Any = None
    # (2026-09-06) Coordination Activities watcher (services.coordination): the
    # engine's view of peers' declared intent, read by ServerQuery/Activities.
    coordination: Any = None
    # (2026-09-07) Workload catalogue submitter (services.workload_sync): the
    # last Scheduler/SyncWorkloads outcome, read by /workloads.
    workload_sync: Any = None

    # Caught by #GR.00000005.UNKNOWNSVC on 2026-09-01: all four were
    # registered by server.py and silently dropped for want of a field —
    # reconciliation_service among them, meaning servicer-side access to
    # it had been None since inception.
    agenda_tracker: Any = None
    daemon_registry: Any = None
    flow_scheduler_service: Any = None
    reconciliation_service: Any = None

    # X Bookmarks service for syncing X/Twitter bookmarks to KB
    x_bookmarks_service: Any = None

    # Prospects/Stewardship service for FMP-based intelligence
    prospects_service: Any = None

    # Collections service for public landing page content
    collection_service: Any = None

    # Ambient computing workload service
    ambient_service: Any = None

    # Embedding service for semantic search
    embedding_service: Any = None

    # Vector search service (orchestrator-managed ColNomic)
    vector_search_service: Any = None

    # MetaAgent service for Metabase sync, audits, budget
    metaagent_service: Any = None

    # ThetaAgent service for situational awareness and consolidation
    theta_service: Any = None

    # Engine config
    config: Any = None

    # Service state
    start_time: Optional[float] = None

    # Callbacks for state access
    get_health_metrics: Optional[Callable] = None
    get_evolution_status: Optional[Callable] = None
    trigger_evolution: Optional[Callable] = None
    start_evolution: Optional[Callable] = None
    stop_evolution: Optional[Callable] = None

    # Init controller for bidirectional initialization streaming
    # Available immediately when gRPC starts, before other services
    init_controller: Any = None


class GrpcServer:
    """gRPC server for Gaius Engine.

    Hosts both the KServe OIP inference service and custom Gaius extensions.
    Uses async gRPC (grpc.aio) for high-performance concurrent request handling.
    """

    def __init__(self, config: GrpcConfig):
        self._config = config
        self._server: Optional[aio.Server] = None
        self._services = ServiceRegistry()
        self._running = False

    def set_services(
        self,
        backend_router: Any = None,
        orchestrator_service: Any = None,
        cognition_service: Any = None,
        dataset_service: Any = None,
        topology_service: Any = None,
        config: Any = None,
        start_time: Optional[float] = None,
        get_health_metrics: Optional[Callable] = None,
        get_evolution_status: Optional[Callable] = None,
        trigger_evolution: Optional[Callable] = None,
        start_evolution: Optional[Callable] = None,
        stop_evolution: Optional[Callable] = None,
        init_controller: Any = None,
    ) -> None:
        """Set the backend services for gRPC handlers to use.

        Args:
            backend_router: BackendRouter instance for inference
            orchestrator_service: OrchestratorService for endpoint management
            cognition_service: CognitionService for thought generation
            dataset_service: DatasetService for NiFi SoM/ToM generation
            topology_service: TopologyService for temporal dynamics tracking
            config: EngineConfig instance
            start_time: Engine start timestamp
            get_health_metrics: Callback to get current health metrics
            get_evolution_status: Callback to get evolution daemon status
            trigger_evolution: Callback to trigger evolution cycle
            start_evolution: Callback to start evolution daemon
            stop_evolution: Callback to stop evolution daemon
            init_controller: InitController for bidirectional init streaming
        """
        self._services.backend_router = backend_router
        self._services.orchestrator_service = orchestrator_service
        self._services.cognition_service = cognition_service
        self._services.dataset_service = dataset_service
        self._services.topology_service = topology_service
        self._services.config = config
        self._services.start_time = start_time
        self._services.get_health_metrics = get_health_metrics
        self._services.get_evolution_status = get_evolution_status
        self._services.trigger_evolution = trigger_evolution
        self._services.start_evolution = start_evolution
        self._services.stop_evolution = stop_evolution
        self._services.init_controller = init_controller

    def update_service(self, name: str, service: Any) -> None:
        """Update a specific service after initial setup.

        Useful for services that are initialized after gRPC server starts,
        like cognition_service which starts after gRPC.

        Args:
            name: Service attribute name (e.g., 'cognition_service')
            service: Service instance
        """
        if hasattr(self._services, name):
            setattr(self._services, name, service)
            logger.debug(f"Updated service: {name}")
        else:
            # A dropped registration cost us a daemon on 2026-09-01
            # (nautilus_service missing from ServiceRegistry) — the old
            # warning here was too quiet to catch. Loud, with the fix.
            logger.error(
                f"#GR.00000005.UNKNOWNSVC update_service({name!r}) dropped: "
                f"not a ServiceRegistry field — declare it in ServiceRegistry"
            )

    async def start(self) -> None:
        """Start the gRPC server."""
        if not self._config.enabled:
            logger.info("gRPC server disabled by configuration")
            return

        # Configure server options.
        # grpc.so_reuseport=0 is mandatory: default ON lets a second gaius-engine
        # dual-bind :50051 and kernel-lottery Engine/Status (lattice accept).
        options = [
            ("grpc.max_receive_message_length", self._config.max_message_size),
            ("grpc.max_send_message_length", self._config.max_message_size),
            ("grpc.so_reuseport", 0),
        ]

        # Create async gRPC server
        self._server = aio.server(
            futures.ThreadPoolExecutor(max_workers=self._config.max_workers),
            options=options,
        )

        # Register OIP inference servicer
        inference_servicer = InferenceServicer(self._services)
        add_GRPCInferenceServiceServicer_to_server(inference_servicer, self._server)
        logger.debug("Registered GRPCInferenceService (KServe OIP)")

        # Register Gaius servicer
        gaius_servicer = GaiusServicer(self._services)
        add_GaiusServiceServicer_to_server(gaius_servicer, self._server)
        logger.debug("Registered GaiusService (custom extensions)")

        # Register Signals lattice face (same port; distinct service path)
        zndx_servicer = GaiusZndxEngineServicer(self._services)
        zpb_grpc.add_EngineServicer_to_server(zndx_servicer, self._server)
        logger.debug("Registered zndx.engine.v1.Engine (lattice federation face)")

        # (2026-09-04) The engine-hosted supervision stream the resident Nautilus
        # dials: events out, directives in. Same port, distinct service path.
        from gaius.engine.generated.zndx.supervision.v1 import supervision_pb2_grpc as sv_grpc
        from .servicers.supervision_servicer import EngineSupervisionServicer

        sv_grpc.add_EngineSupervisionServicer_to_server(
            EngineSupervisionServicer(self._services), self._server
        )
        logger.debug("Registered zndx.supervision.v1.EngineSupervision (supervision stream)")

        # Reflection is required for external spot-checks (grpcurl list) and
        # lattice-ci. Generated stubs remain the protocol SoR.
        if self._config.reflection_enabled:
            try:
                from grpc_reflection.v1alpha import reflection
            except Exception as exc:
                raise RuntimeError(
                    "#EN.00000015.NOREFLECT grpcio-reflection failed to import.\n"
                    f"  {exc}\n"
                    "  grpcio-reflection>=1.83 needs protobuf 7; this tree pins "
                    "protobuf<7 (xai-sdk).\n"
                    "  Try: uv sync --extra grpc   # lock pins grpcio-reflection<1.82\n"
                    "  Or:  /health fix engine"
                ) from exc

            service_names = (
                "inference.GRPCInferenceService",
                "gaius.engine.GaiusService",
                "zndx.engine.v1.Engine",
                "zndx.supervision.v1.EngineSupervision",
                reflection.SERVICE_NAME,
            )
            reflection.enable_server_reflection(service_names, self._server)
            logger.info("gRPC reflection enabled (grpcurl list)")

        # Bind exclusively. add_insecure_port returns 0 when the port is taken.
        listen_addr = f"{self._config.host}:{self._config.port}"
        bound = self._server.add_insecure_port(listen_addr)
        if bound == 0:
            raise RuntimeError(
                f"#EN.00000014.DUALBIND could not bind {listen_addr} "
                "(port already held; gRPC reuseport is disabled).\n"
                "  Another gaius-engine / devenv daemon is listening.\n"
                "  Try: /health fix engine\n"
                "  Or:  ss -ltnp | grep 50051   # stop the extra devenv stack, not just down"
            )

        # Start server
        await self._server.start()
        self._running = True

        logger.info(f"gRPC server listening on {listen_addr}")
        logger.info("  - GRPCInferenceService (KServe OIP v2)")
        logger.info("  - GaiusService (custom extensions)")
        logger.info("  - zndx.engine.v1.Engine (Signals lattice face)")

    async def stop(self, grace: float = 5.0) -> None:
        """Stop the gRPC server gracefully.

        Args:
            grace: Grace period in seconds for in-flight requests
        """
        if self._server:
            logger.info(f"Stopping gRPC server (grace={grace}s)...")
            await self._server.stop(grace)
            self._running = False
            logger.info("gRPC server stopped")

    async def wait_for_termination(self) -> None:
        """Wait for the server to terminate."""
        if self._server:
            await self._server.wait_for_termination()

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running

    @property
    def address(self) -> str:
        """Get the server listen address."""
        return f"{self._config.host}:{self._config.port}"
