"""Gaius Engine server - main daemon loop.

The engine server:
1. Loads configuration from HOCON
2. Starts gRPC server (the only transport)
3. Initializes backend services (vLLM, optillm, cognition, etc.)
4. Broadcasts events and health metrics
5. Runs autonomous services (evolution, health observer)
"""

# Configure parallelism BEFORE any imports
import os

# Configure joblib to use threading instead of multiprocessing
# This avoids fork() conflicts with gRPC while preserving parallelism.
# Threading works well for NumPy/sklearn/UMAP since they release the GIL.
try:
    from joblib import parallel_config
    parallel_config(backend="threading", n_jobs=-1)
except ImportError:
    pass  # joblib not available yet

import argparse
import asyncio
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .config import EngineConfig, load_config
from .daemon_registry import DaemonRegistry
from .transport.protocol import (
    Request,
    Response,
    HealthMetrics,
    Service,
)

logger = logging.getLogger(__name__)


class GaiusEngine:
    """Main engine daemon coordinating all services.

    Responsibilities:
    - Accept and route requests from clients
    - Manage service lifecycle (including optillm/vLLM backends)
    - Broadcast events and health metrics
    - Handle graceful shutdown
    """

    def __init__(self, config: EngineConfig):
        self.config = config
        self._running = False
        self._health_task: Optional[asyncio.Task] = None
        self._request_task: Optional[asyncio.Task] = None
        self._start_time: Optional[datetime] = None

        # gRPC server (only transport)
        self._grpc_server = None

        # Backend router for inference (manages optillm and vLLM)
        self._backend_router = None

        # Orchestrator service for endpoint management
        self._orchestrator_service = None
        self._coordination = None  # services.coordination.CoordinationWatcher (2026-09-06)

        # Evolution daemon
        self._evolution_daemon = None

        # Service handlers (to be implemented in later phases)
        self._handlers: dict[Service, Callable] = {
            Service.ORCHESTRATOR: self._handle_orchestrator,
            Service.SCHEDULER: self._handle_scheduler,
            Service.EVOLUTION: self._handle_evolution,
            Service.GRID: self._handle_grid,
            Service.TDA: self._handle_tda,
            Service.HEALTH: self._handle_health,
            Service.COGNITION: self._handle_cognition,
        }

        # Cognition service (manages scheduled tasks)
        self._cognition_service = None

        # Flow scheduler service (autonomous Metaflow runs)
        self._flow_scheduler_service = None

        # Dataset service (NiFi SoM/ToM generation)
        self._dataset_service = None

        # Reconciliation service (FSM-based state observation)
        self._reconciliation_service = None
        self._nautilus_service = None

        # Topology service (temporal dynamics tracking)
        self._topology_service = None

        # Health observer service (autonomous monitoring, FMEA, ACP)
        self._health_observer_service = None

        # X Bookmarks service (sync X/Twitter bookmarks to KB)
        self._x_bookmarks_service = None

        # Prospects/Stewardship service (FMP-based financial intelligence)
        self._prospects_service = None

        # Collections service (public landing page content)
        self._collection_service = None

        # Ambient computing workload service
        self._ambient_service = None

        # Vector search service (orchestrator-managed ColNomic)
        self._vector_search_service = None

        # MetaAgent service (Metabase sync, audits, budget)
        self._metaagent_service = None

        # ThetaAgent service (situational awareness, consolidation)
        self._theta_service = None

        # Scheduled task processor (LISTEN/NOTIFY for pg_cron tasks)
        self._scheduled_task_processor = None

        # Health service (basic metrics)
        self._health_service = None

        # Agenda tracker for workload-centric incident tracking
        self._agenda_tracker = None

        # Daemon registry for lifecycle management
        self._daemon_registry: Optional[DaemonRegistry] = None

        # Shared database pool for services requiring direct DB access
        self._db_pool = None

        # ACP security config (validated on startup)
        self._acp_security_config = None

    async def _validate_acp_prerequisites(self) -> None:
        """FAIL-FAST: Verify ACP configuration exists and is valid.

        ACP (Agent Client Protocol) is REQUIRED for self-healing escalation.
        If escalation is enabled but config is missing, we fail early so the
        operator knows there's no escalation path for incidents.

        This follows the FAIL-FAST principle: surface configuration issues
        at startup, not at 3am when an incident needs escalation.

        Raises:
            RuntimeError: If ACP is enabled but config is missing/invalid
        """
        from pathlib import Path

        # Check if we have acp.conf in standard locations
        config_path = None
        candidates = [
            Path.home() / ".config/gaius/acp.conf",
            Path.home() / ".gaius/acp.conf",
            Path.cwd() / "config/acp.conf",
            Path.cwd() / ".gaius/acp.conf",
        ]

        for candidate in candidates:
            if candidate.exists():
                config_path = candidate
                break

        if config_path is None:
            # ACP config not found - log warning but continue
            # (ACP is valuable but not strictly required for engine operation)
            logger.warning(
                "ACP security config not found.\n"
                "  Escalation via ACP will be unavailable.\n"
                "  Create config at: ~/.config/gaius/acp.conf\n"
                "  Guru: #ACP.00000011.NOCONFIG"
            )
            return

        # Validate ACP config
        try:
            from ..acp.security import load_security_config

            self._acp_security_config = load_security_config(config_path)

            if not self._acp_security_config.allowed_repos:
                logger.warning(
                    f"ACP config at {config_path} has no allowed_repos.\n"
                    "  No GitHub repositories are configured for issue creation.\n"
                    "  Add 'acp.github.allowed_repos = [\"owner/repo\"]' to config.\n"
                    "  Guru: #ACP.00000012.NOREPOS"
                )
            else:
                logger.info(
                    f"ACP config validated: {len(self._acp_security_config.allowed_repos)} "
                    f"allowed repos, require_private={self._acp_security_config.require_private}"
                )

        except ImportError:
            logger.warning(
                "ACP module not available (pyhocon not installed).\n"
                "  Install with: uv sync --extra acp\n"
                "  Escalation via ACP will be unavailable."
            )
        except Exception as e:
            logger.error(
                f"Failed to validate ACP config: {e}\n"
                "  Escalation via ACP may be unavailable.\n"
                "  Guru: #ACP.00000013.CONFIGFAIL"
            )

    async def start(self) -> None:
        """Start the engine daemon.

        Startup sequence reordered so gRPC is available FIRST, allowing
        TUI/MCP clients to connect immediately and receive real-time
        initialization progress during the ~240s vLLM preload phase.

        Phases:
        1. Create InitController (for bidirectional streaming)
        2. Start gRPC server EARLY (clients can connect immediately)
        3. Initialize telemetry
        4. Initialize backends (broadcasts progress)
        5. Initialize orchestrator (broadcasts progress)
        6. Preload endpoints (broadcasts progress)
        7. Start background services
        8. Mark initialization complete
        """
        from .init_controller import get_init_controller, InitPhase

        logger.info("Starting Gaius Engine...")
        self._start_time = datetime.now()

        # Stamp the commit this process is running, once, before the checkout can
        # move under us — surfaced as SourcePosture.running_sha over ServerQuery.
        try:
            from .s2s import stamp_running_sha

            stamp_running_sha()
        except Exception as e:
            logger.debug("running-sha stamp skipped: %s", e)

        # (2026-09-04) The supervision event bus exists before any daemon can
        # publish to it; the EngineSupervision stream servicer subscribes per
        # supervisor session. Fail-open: bookkeeping never gates the boot.
        try:
            from .services.supervision_bus import init_bus

            _bus = init_bus()
            try:
                if self._grpc_server is not None:
                    self._grpc_server.update_service("supervision_bus", _bus)
            except Exception as e:  # noqa: BLE001
                logger.debug("supervision bus registry update skipped: %s", e)
        except Exception as e:
            logger.debug("supervision bus init skipped: %s", e)

        # 0. Validate ACP prerequisites FIRST (FAIL-FAST)
        # This ensures escalation paths are available before any daemons start
        await self._validate_acp_prerequisites()

        # 1. Create init controller for bidirectional streaming
        self._init_controller = get_init_controller()
        await self._init_controller.start_phase(InitPhase.TELEMETRY, "Starting initialization")

        # 2. Start gRPC server EARLY so clients can connect immediately
        #    InitController is available, other services will be added as they're ready
        await self._start_grpc_server_early()

        # 2.5 Start X Bookmarks service EARLY (no GPU deps, needed for InitPanel status)
        #     This runs before the ~240s vLLM preload so XB status is available immediately
        await self._init_x_bookmarks_service()

        # 2.55 Postgres pool before vLLM preload so Discover / MV reads do not
        #      wait on thinking HEALTHY (~240s).
        await self._ensure_db_pool()

        # Warehouse writer is independent of GPU preload. Start it here so
        # engine→Postgres→Kudu ticks while vLLM is still coming up.
        try:
            from .services.warehouse_ingest import start_warehouse_ingest

            start_warehouse_ingest()
        except Exception:
            logger.error(
                "warehouse ingest did not start.\n"
                "  Guru: #EN.00000031.FDWINGEST",
                exc_info=True,
            )

        # FMP/prospects FIFO does not need GPUs; fill the buffer during vLLM preload.
        await self._init_prospects_service()

        # 2.6 Collections still wait on cognition path below
        # 2.7 Collections service moved to after db_pool is created (in _autonomous_start_cognition)

        # 3. Initialize telemetry (disabled via OTEL_SDK_DISABLED=true env var)
        await self._init_telemetry()

        # 4. Initialize backend router (manages optillm and vLLM)
        await self._init_controller.start_phase(InitPhase.BACKENDS, "Initializing backends")
        await self._init_backends()
        # Update gRPC with backend router
        if self._grpc_server:
            self._grpc_server.update_service("backend_router", self._backend_router)

        # 4.5 Engine scheduler service: priority job queue over the backend
        # router. Backs the gRPC SubmitJob/GetJobResult/SchedulerStatus surface
        # (Engine-First: the job queue lives in the engine, never client-side).
        from .services.scheduler_service import SchedulerService

        if self._backend_router is None:
            raise RuntimeError(
                "Backend router not initialized before scheduler service.\n"
                "  Guru Meditation: #ENGINE.00000001.INIT_ORDER"
            )
        self._scheduler_service = SchedulerService(self.config, self._backend_router)
        await self._scheduler_service.start()
        if self._grpc_server:
            self._grpc_server.update_service("scheduler_service", self._scheduler_service)

        # 5. Initialize orchestrator service for endpoint management
        await self._init_controller.start_phase(InitPhase.ORCHESTRATOR, "Initializing orchestrator")
        await self._init_orchestrator()
        # Update gRPC with orchestrator
        if self._grpc_server:
            self._grpc_server.update_service("orchestrator_service", self._orchestrator_service)

        # 6. Autonomous startup: clean start and preload if configured
        if self.config.startup.clean_start:
            await self._init_controller.start_phase(InitPhase.PRELOAD, "Starting endpoint preload")
            await self._autonomous_clean_start_with_progress()

        self._running = True

        # 7. Start background tasks
        self._health_task = asyncio.create_task(self._health_broadcast_loop())

        # (2026-09-06) Coordination Activities: the engine is the peer that
        # watches Signals (Scheduler/WatchActivities) for inter-project intent
        # and cedes endpoints to it; local processes read the view from THIS
        # engine. Fail-open: a dark or older Signals never gates the boot.
        try:
            if os.environ.get("GAIUS_COORDINATION_WATCH", "1").lower() in ("0", "false", "no", "off"):
                logger.info("Coordination watcher disabled (GAIUS_COORDINATION_WATCH=0)")
            else:
                from .services.coordination import init_coordination
                from .services.supervision_bus import get_bus

                # pool_getter: the shared asyncpg pool may not exist yet at this
                # point of the boot; the workload pass reads it lazily.
                self._coordination = init_coordination(
                    self._orchestrator_service, get_bus(), pool_getter=lambda: self._db_pool
                )
                self._coordination.start()
                if self._grpc_server is not None:
                    self._grpc_server.update_service("coordination", self._coordination)
                logger.info("Coordination watcher started (Signals %s)", self._coordination.target)
        except Exception as e:  # noqa: BLE001
            logger.warning("Coordination watcher not started: %s", e)
        try:
            from .services.cognition_waterfall import start_strip

            start_strip()
        except Exception:
            logger.debug("waterfall strip poller not started", exc_info=True)

        # Autonomous startup: start evolution daemon if configured
        if self.config.startup.auto_start_evolution and self.config.evolution.enabled:
            await self._init_controller.start_phase(InitPhase.EVOLUTION, "Starting evolution daemon")
            await self._autonomous_start_evolution()

        # Autonomous startup: start cognition daemon if configured
        if self.config.startup.auto_start_cognition:
            await self._init_controller.start_phase(InitPhase.COGNITION, "Starting cognition daemon")
            await self._autonomous_start_cognition()

        # Autonomous startup: start flow scheduler if configured
        if self.config.startup.auto_start_flow_scheduler and self.config.flow_scheduler.enabled:
            await self._autonomous_start_flow_scheduler()

        # Always start dataset service (lightweight, fail-fast by design)
        await self._init_dataset_service()

        # NOTE: Collections service is initialized in _autonomous_start_cognition()
        # after the db_pool is created (requires db_pool for database operations)

        # Initialize ambient computing workload service
        await self._init_ambient_service()

        # Initialize vector search service (orchestrator-managed ColNomic)
        await self._init_vector_search_service()

        # NOTE: X Bookmarks service is initialized EARLY (after gRPC starts, before PRELOAD)
        # to ensure XB status is available during the ~240s vLLM preload phase

        # 8. Initialize and start daemons via DaemonRegistry
        # This provides dependency-ordered startup with FAIL-FAST semantics
        await self._init_daemon_registry()

        # 9. Mark initialization complete
        await self._init_controller.complete_init()

        # 10. Auto-resume ambient workload if it was running before restart
        await self._maybe_start_ambient()

        logger.info(
            f"Gaius Engine started with {len(self.config.agents)} agents configured"
        )

        # Log configured agents
        for name, agent in self.config.agents.items():
            logger.info(f"  Agent '{agent.alias}': {agent.model} ({agent.backend})")

    async def _init_backends(self) -> None:
        """Initialize backend router and start optillm."""
        from .backends import BackendRouter
        from .resources import ResourceManager

        # Create resource manager for GPU allocation
        self._resource_manager = ResourceManager(self.config)

        # Create backend router
        self._backend_router = BackendRouter(self.config, self._resource_manager)

        # Start backends (this will start optillm if not already running)
        await self._backend_router.start()
        logger.info("Backend router initialized")

    async def _init_orchestrator(self) -> None:
        """Initialize orchestrator service for endpoint management."""
        from .services.orchestrator_service import OrchestratorService

        if self._backend_router is None:
            raise RuntimeError(
                "Backend router not initialized before orchestrator.\n"
                "  Guru Meditation: #ENGINE.00000001.INIT_ORDER"
            )

        self._orchestrator_service = OrchestratorService(
            config=self.config,
            resource_manager=self._resource_manager,
            backend_router=self._backend_router,
        )
        await self._orchestrator_service.start()
        self._backend_router.optillm.set_vllm_ensure(
            self._orchestrator_service.demand_vllm_for_optillm
        )
        logger.info("Orchestrator service initialized")

    async def _autonomous_clean_start(self) -> None:
        """Perform autonomous clean start: cleanup stale processes and preload endpoints."""
        logger.info("Performing autonomous clean start...")

        assert self._orchestrator_service is not None  # Guaranteed by _init_orchestrator

        # Step 1: Cleanup stale vLLM processes
        cleanup_result = await self._orchestrator_service.cleanup_stale_processes()
        if cleanup_result.processes_killed > 0:
            logger.info(
                f"Cleaned up {cleanup_result.processes_killed} stale processes: {cleanup_result.pids_killed}"
            )

        # Step 2: Preload configured endpoints
        preload = self.config.startup.preload_endpoints
        if preload:
            logger.info(f"Preloading endpoints: {preload}")
            for endpoint_alias in preload:
                if endpoint_alias in self.config.agents:
                    try:
                        status = await self._orchestrator_service.start_endpoint(endpoint_alias)
                        logger.info(
                            f"  {endpoint_alias}: {status.status} (port={status.port}, GPUs={status.gpu_ids})"
                        )
                    except Exception as e:
                        logger.warning(f"  {endpoint_alias}: failed to start - {e}")
                else:
                    logger.warning(f"  {endpoint_alias}: not found in agent config")
        await self._bind_optillm_to_provided_vllm()

    async def _bind_optillm_to_provided_vllm(self) -> None:
        """Point optillm at a healthy vLLM instead of a stale config port."""
        orch = self._orchestrator_service
        router = self._backend_router
        if orch is None or router is None:
            return
        url = orch.provided_vllm_openai_url()
        if not url:
            return
        await router.optillm.bind_provided_vllm(url)

    async def _autonomous_clean_start_with_progress(self) -> None:
        """Perform autonomous clean start with progress broadcasting.

        Similar to _autonomous_clean_start but broadcasts progress events
        via InitController for real-time TUI/MCP updates.
        """
        from .init_controller import InitPhase
        from .generated.gaius_service_pb2 import InitEvent

        logger.info("Performing autonomous clean start with progress...")

        assert self._orchestrator_service is not None  # Guaranteed by _init_orchestrator
        # Capture narrowed type for nested function
        orchestrator = self._orchestrator_service

        # Step 1: Cleanup stale vLLM processes
        cleanup_result = await orchestrator.cleanup_stale_processes()
        if cleanup_result.processes_killed > 0:
            logger.info(
                f"Cleaned up {cleanup_result.processes_killed} stale processes: {cleanup_result.pids_killed}"
            )

        # Step 2: Preload configured endpoints with progress
        preload = self.config.startup.preload_endpoints
        if not preload:
            logger.info("No endpoints configured for preload")
            return

        logger.info(f"Preloading endpoints: {preload}")

        async def start_endpoint_with_progress(endpoint_alias: str):
            """Start an endpoint and yield progress updates."""
            if endpoint_alias not in self.config.agents:
                yield ("not found", 0.0)
                raise ValueError(f"Endpoint {endpoint_alias} not found in agent config")

            # Yield starting status
            yield ("starting vLLM process", 0.1)

            try:
                # Start the endpoint
                status = await orchestrator.start_endpoint(endpoint_alias)
                logger.info(
                    f"  {endpoint_alias}: {status.status} (port={status.port}, GPUs={status.gpu_ids})"
                )

                # Yield completion
                if status.status == "healthy":
                    yield ("ready", 1.0)
                else:
                    yield (status.status, 1.0)

            except Exception as e:
                logger.warning(f"  {endpoint_alias}: failed to start - {e}")
                yield (f"failed: {e}", 1.0)
                raise

        # Use InitController's preload_with_control for cancellation support
        results = await self._init_controller.preload_with_control(
            preload,
            start_endpoint_with_progress,
        )

        # Log results
        succeeded = sum(1 for v in results.values() if v)
        failed = sum(1 for v in results.values() if not v)
        logger.info(f"Preload complete: {succeeded} succeeded, {failed} failed")
        await self._bind_optillm_to_provided_vllm()

    async def _start_grpc_server_early(self) -> None:
        """Start gRPC server EARLY with minimal services.

        This enables TUI/MCP clients to connect immediately during
        the ~240s initialization phase and receive progress updates
        via InitStream.

        Only init_controller is available. Other services (backend_router,
        orchestrator_service) will be added via update_service() as they
        become ready.
        """
        if not self.config.grpc.enabled:
            logger.info("gRPC server disabled by configuration")
            return

        try:
            from .grpc import GrpcServer, GrpcConfig

            # Convert engine config to gRPC config
            grpc_config = GrpcConfig(
                enabled=self.config.grpc.enabled,
                host=self.config.grpc.host,
                port=self.config.grpc.port,
                max_workers=self.config.grpc.max_workers,
                max_message_size=self.config.grpc.max_message_size,
            )

            # Create gRPC server
            self._grpc_server = GrpcServer(grpc_config)

            # Register ONLY init_controller initially
            # Other services will be added via update_service() as they're ready
            self._grpc_server.set_services(
                init_controller=self._init_controller,
                config=self.config,
                start_time=self._start_time.timestamp() if self._start_time else None,
                get_health_metrics=self._collect_health_metrics,
                get_evolution_status=self._get_evolution_status,
                trigger_evolution=self._trigger_evolution,
                start_evolution=self._start_evolution,
                stop_evolution=self._stop_evolution,
            )

            # Start the server
            await self._grpc_server.start()
            logger.info("gRPC server started early (InitStream available)")

        except ImportError as e:
            logger.warning(f"gRPC dependencies not installed: {e}")
            logger.warning("Install with: uv sync --extra grpc")
        except Exception as e:
            logger.error(f"Failed to start gRPC server: {e}")
            raise

    async def _autonomous_start_evolution(self) -> None:
        """Start the evolution daemon automatically."""
        try:
            from ..agents.evolution.daemon import EvolutionDaemon, EvolutionConfig as EvoDaemonConfig

            logger.info("Starting evolution daemon automatically...")

            # Create evolution daemon config
            evo_config = EvoDaemonConfig(
                idle_threshold=0.2,  # 20% GPU utilization
                poll_interval=self.config.evolution.idle_timeout_seconds / 60,  # Convert to minutes
                max_cycles_per_hour=10,
                strategy=self.config.evolution.strategy,
                agents=self.config.evolution.rotation,
            )

            # Create and start daemon
            self._evolution_daemon = EvolutionDaemon(config=evo_config)
            await self._evolution_daemon.start()
            logger.info("Evolution daemon started")

        except ImportError as e:
            logger.warning(f"Evolution daemon not available: {e}")
        except Exception as e:
            logger.error(f"Failed to start evolution daemon: {e}")

    async def _ensure_db_pool(self) -> None:
        """Shared asyncpg pool. Safe to call more than once."""
        if self._db_pool is not None:
            return
        try:
            import asyncpg

            from gaius.core.config import get_database_url

            self._db_pool = await asyncpg.create_pool(
                get_database_url(),
                min_size=2,
                max_size=10,
            )
            logger.info("Created shared database pool (min=2, max=10)")
            if self._grpc_server:
                self._grpc_server.update_service("db_pool", self._db_pool)
            try:
                from .services.efficacy_ledger import init_ledger

                init_ledger(self._db_pool)
            except Exception:
                # Ledger absence must never block engine start (its own
                # recording contract is fail-open; see efficacy_ledger).
                logger.exception("#EFF.00000001.RECFAIL ledger init failed")
            try:
                from .services.discover_landing import request_discover_landing_refresh

                await request_discover_landing_refresh(
                    self._db_pool, reason="engine-start"
                )
            except Exception:
                logger.exception("discover landing seed failed")
        except Exception as db_err:
            logger.error(
                f"Failed to create database pool: {db_err}\n"
                "  Guru Meditation: #COG.00000001.NOPOOL\n"
                "  Try: /health fix postgres"
            )

    async def _autonomous_start_cognition(self) -> None:
        """Start the cognition daemon automatically.

        The cognition daemon polls scheduled_tasks for cognition_cycle,
        engine_audit, and delta_check tasks inserted by pg_cron.

        Creates a shared database pool FIRST, then passes it to both
        CognitionService and TopologyService.
        """
        await self._ensure_db_pool()

        # Start CognitionService with db_pool
        try:
            from .services.cognition_service import CognitionService, CognitionConfig

            logger.info("Starting cognition daemon automatically...")

            # Create cognition config
            config = CognitionConfig(
                max_thoughts_per_cycle=self.config.evolution.parallel_max_concurrent
                if hasattr(self.config.evolution, "parallel_max_concurrent")
                else 4,
                poll_interval_seconds=30.0,
            )

            # Wire up GPU idle check to orchestrator if available
            def get_gpu_idle() -> bool:
                if self._orchestrator_service:
                    return self._orchestrator_service.is_gpu_idle()
                return True  # Default to idle if orchestrator not available

            # Create and start service WITH db_pool
            self._cognition_service = CognitionService(
                config,
                get_gpu_idle=get_gpu_idle,
                db_pool=self._db_pool,  # Critical: pass db_pool for pg_cron task consumption
            )
            await self._cognition_service.start()
            logger.info(
                f"Cognition daemon started "
                f"(db_pool={'connected' if self._db_pool else 'MISSING'})"
            )

            # Update gRPC service registry (cognition starts after gRPC)
            if self._grpc_server:
                self._grpc_server.update_service("cognition_service", self._cognition_service)

        except ImportError as e:
            logger.warning(f"Cognition service not available: {e}")
        except Exception as e:
            logger.error(f"Failed to start cognition daemon: {e}")

        # Create topology service (reuses the shared database pool)
        try:
            from .services.topology_service import TopologyService

            self._topology_service = TopologyService(db_pool=self._db_pool)
            logger.info("Topology service initialized (sharing db_pool)")

            if self._grpc_server:
                self._grpc_server.update_service("topology_service", self._topology_service)
        except Exception as e:
            logger.warning(f"Failed to initialize topology service: {e}")

        # Initialize Collections service (requires db_pool which is now available)
        await self._init_collection_service()

    async def _autonomous_start_flow_scheduler(self) -> None:
        """Start the flow scheduler daemon automatically.

        The flow scheduler monitors content_items for new arxiv papers
        and triggers ArxivDoclingFlow for automatic PDF conversion and
        topic extraction.
        """
        try:
            from .services.flow_scheduler_service import FlowSchedulerService, FlowConfig

            logger.info("Starting flow scheduler daemon automatically...")

            # Create flow config from engine config
            config = FlowConfig(
                enabled=self.config.flow_scheduler.enabled,
                poll_interval_seconds=self.config.flow_scheduler.poll_interval_seconds,
                max_concurrent_flows=self.config.flow_scheduler.max_concurrent_flows,
                batch_size=self.config.flow_scheduler.batch_size,
                gpu_index=self.config.flow_scheduler.gpu_index,
                enable_topics=self.config.flow_scheduler.enable_topics,
                topic_model_type=self.config.flow_scheduler.topic_model_type,
                enable_scoring=self.config.flow_scheduler.enable_scoring,
            )

            # Create and start service with orchestrator for GPU resource management
            self._flow_scheduler_service = FlowSchedulerService(
                config,
                get_gpu_idle=lambda: True,  # TODO: wire up to health service
                orchestrator=self._orchestrator_service,  # Enable transient workload coordination
            )
            await self._flow_scheduler_service.start()
            logger.info("Flow scheduler daemon started")

            # Update gRPC service registry
            if self._grpc_server:
                self._grpc_server.update_service("flow_scheduler_service", self._flow_scheduler_service)

        except ImportError as e:
            logger.warning(f"Flow scheduler service not available: {e}")
        except Exception as e:
            logger.error(f"Failed to start flow scheduler daemon: {e}")

    async def _init_dataset_service(self) -> None:
        """Initialize dataset generation service.

        The DatasetService is lightweight and fail-fast by design.
        It doesn't preload models or hold GPU resources - it delegates
        to backends when jobs are submitted.
        """
        try:
            from .services.dataset_service import DatasetService, DatasetServiceConfig

            logger.info("Initializing dataset service...")

            # Create service config with defaults
            config = DatasetServiceConfig()

            # Create and start service with dependencies
            self._dataset_service = DatasetService(
                config=config,
                backend_router=self._backend_router,
                orchestrator_service=self._orchestrator_service,
            )
            await self._dataset_service.start()
            logger.info("Dataset service initialized")

            # Update gRPC service registry
            if self._grpc_server:
                self._grpc_server.update_service("dataset_service", self._dataset_service)

        except ImportError as e:
            logger.warning(f"Dataset service not available: {e}")
        except Exception as e:
            logger.error(f"Failed to initialize dataset service: {e}")

    async def _init_x_bookmarks_service(self) -> None:
        """Initialize X Bookmarks sync service.

        The XBookmarksService manages X (Twitter) bookmark synchronization:
        - OAuth 2.0 PKCE flow for authentication
        - Rate-limited API request queue (respects X API limits)
        - Bookmark fetching with pagination
        - Sync to Iceberg HX and KB markdown
        """
        try:
            from .services.x_bookmarks_service import XBookmarksService, XBookmarksConfig
            import asyncpg

            logger.info("Initializing X Bookmarks service...")

            # Get database pool from config
            from gaius.core.config import get_database_url

            db_url = get_database_url()

            # Create database pool
            pool = await asyncpg.create_pool(db_url, min_size=2, max_size=5)

            # Create service config
            kb_root = os.environ.get("GAIUS_KB_ROOT", "build/dev")
            config = XBookmarksConfig(
                kb_root=kb_root,
                queue_poll_interval_s=60,  # Check queue every minute
            )

            # Create and start service
            self._x_bookmarks_service = XBookmarksService(
                pool=pool,
                config=config,
            )

            # Wire XBookmarksService to InitController for real-time XB event push
            # This enables the TUI's InitPanel to update immediately when auth completes
            if self._init_controller:
                def xb_event_callback(event_type: str, data: dict) -> None:
                    """Forward XB events to InitController for broadcast."""
                    import asyncio
                    logger.info(f"XB callback invoked: {event_type} with data: {data}")
                    try:
                        # Use create_task for async broadcast from sync callback
                        loop = asyncio.get_running_loop()
                        task = loop.create_task(
                            self._init_controller.broadcast_xb_event(event_type, data)
                        )
                        logger.info(f"Created broadcast task for {event_type}: {task}")
                    except RuntimeError as e:
                        # No running loop - we're called from sync context
                        logger.error(f"No running event loop for XB event: {e}")
                    except Exception as e:
                        logger.warning(f"Failed to broadcast XB event: {e}", exc_info=True)

                self._x_bookmarks_service.set_event_callback(xb_event_callback)
                logger.info("XBookmarksService wired to InitController for real-time events")

            await self._x_bookmarks_service.start()
            logger.info("X Bookmarks service started")

            # Update gRPC service registry
            if self._grpc_server:
                self._grpc_server.update_service(
                    "x_bookmarks_service", self._x_bookmarks_service
                )
                logger.info("X Bookmarks service registered with gRPC")

        except ImportError as e:
            logger.warning(f"X Bookmarks service not available: {e}")
        except Exception as e:
            logger.error(f"Failed to initialize X Bookmarks service: {e}")

    async def _init_prospects_service(self) -> None:
        """Initialize Prospects/Stewardship service.

        The ProspectsService manages FMP-based financial intelligence:
        - Daily SEC filing checks ($0 cost via pg_cron)
        - Status queries (cached data, no LLM)
        - Full billable analysis (Cerebras + Grok)
        - KB artifact generation (Obsidian .base files)

        Runs via Metaflow flows triggered by gRPC RPCs.

        MUST be called after self._db_pool is created.
        """
        if getattr(self, "_prospects_service", None) is not None:
            return
        if not getattr(self, "_db_pool", None):
            logger.error(
                "Cannot initialize Prospects service: shared db_pool not created.\n"
                "  Guru Meditation: #PS.00000006.NOPOOL\n"
                "  Prospects service requires _autonomous_start_cognition() to run first.\n"
                "  Try: /health fix postgres"
            )
            return

        try:
            from .services.prospects_service import ProspectsService, ProspectsConfig

            logger.info("Initializing Prospects/Stewardship service...")

            # Create service config - profile/domain resolved from database at runtime
            kb_root = os.environ.get("GAIUS_KB_ROOT", "build/dev")
            config = ProspectsConfig(
                kb_root=kb_root,
                # Empty strings = resolve from database at runtime
                default_profile="",
                default_domain="",
            )

            # Create and start service — reuse shared db_pool
            self._prospects_service = ProspectsService(
                pool=self._db_pool,
                config=config,
            )

            # (2026-09-04) No FMP roll loop in-engine any more: the fmp_roll
            # flow (pg_cron 7,37 * * * *) ingests and compacts the prospects
            # buffer in buffer_entries; this service reads through.
            await self._prospects_service.start()
            logger.info("Prospects/Stewardship service started (prospects buffer read-through)")

            # Update gRPC service registry
            if self._grpc_server:
                self._grpc_server.update_service(
                    "prospects_service", self._prospects_service
                )
                logger.info("Prospects/Stewardship service registered with gRPC")

        except ImportError as e:
            logger.warning(f"Prospects/Stewardship service not available: {e}")
        except Exception as e:
            logger.error(
                f"Failed to initialize Prospects/Stewardship service: {e}\n"
                "  Guru Meditation: #PS.00000007.INITFAIL\n"
                "  Try: /health fix engine"
            )

    async def _init_collection_service(self) -> None:
        """Initialize the Collections service for public landing page content.

        The CollectionService manages curated content collections:
        - Create/manage collections with sources and cards
        - Publish cards to Cloudflare KV for landing page
        - Cards link to external PUBLIC sources (arXiv, HuggingFace, etc.)
        """
        try:
            from .services.collection_service import CollectionService, CollectionConfig

            # Get database pool
            if not self._db_pool:
                logger.warning("Collections service disabled - no database pool")
                return

            # Create KB root directory if needed
            kb_root = os.environ.get("GAIUS_KB_ROOT", "build/dev")
            config = CollectionConfig(kb_root=kb_root)

            # Create service (no start() needed - all operations use pool)
            self._collection_service = CollectionService(
                pool=self._db_pool,
                config=config,
            )
            self._collection_service.start_publishing_axis()
            if getattr(self, "_ambient_service", None) is not None:
                self._ambient_service.attach_publishing_axis(
                    self._collection_service._axis
                )
            # (2026-09-04) The axis no longer rolls or compacts in-engine; the
            # ambient_synthesis flow (pg_cron) writes buffer_entries and this
            # axis is the read-through view.
            logger.info("Collections service initialized (publishing axis read-through)")

            # Update gRPC service registry
            if self._grpc_server:
                self._grpc_server.update_service(
                    "collection_service", self._collection_service
                )
                logger.info("Collections service registered with gRPC")

        except ImportError as e:
            logger.warning(f"Collections service not available: {e}")
        except Exception as e:
            logger.error(f"Failed to initialize Collections service: {e}")

    async def _init_ambient_service(self) -> None:
        """Initialize the Ambient Computing Workload service.

        The AmbientWorkloadService manages ambient computing workload cycles:
        - Maintains baseline endpoint mix (orchestrator, thinking)
        - Executes standard tasks on each endpoint
        - Evicts baseline for reasoning tasks
        - Restores baseline after reasoning completes
        """
        try:
            from .services.ambient_service import AmbientWorkloadService

            logger.info("Initializing Ambient Workload service...")

            # Requires orchestrator and backend_router
            if not self._orchestrator_service:
                logger.warning("Ambient service skipped: orchestrator not available")
                return

            if not self._backend_router:
                logger.warning("Ambient service skipped: backend_router not available")
                return

            self._ambient_service = AmbientWorkloadService(
                config=self.config,
                orchestrator=self._orchestrator_service,
                backend_router=self._backend_router,
                db_pool=self._db_pool,  # Enable state persistence for auto-resume
            )
            if getattr(self, "_prospects_service", None) is not None:
                self._ambient_service.attach_prospects(self._prospects_service)
            if getattr(self, "_collection_service", None) is not None:
                self._ambient_service.attach_publishing_axis(
                    self._collection_service._axis
                )

            # Update gRPC service registry
            if self._grpc_server:
                self._grpc_server.update_service(
                    "ambient_service", self._ambient_service
                )
                logger.info("Ambient Workload service registered with gRPC")

        except ImportError as e:
            logger.warning(f"Ambient Workload service not available: {e}")
        except Exception as e:
            logger.error(f"Failed to initialize Ambient Workload service: {e}")

    async def _init_vector_search_service(self) -> None:
        """Initialize the Vector Search service.

        VectorSearchService wraps ColNomic multi-vector embeddings with
        orchestrator GPU coordination using the workload system:
        - Uses begin_workload()/complete_workload() for GPU allocation
        - LRU-style caching: model stays loaded until idle timeout
        - Graceful queuing when GPU unavailable
        - Fail-fast: no silent degradation to CPU

        Follows Yunikorn-style dynamic scheduling where ColNomic and
        reasoning endpoints can evict each other based on demand.
        """
        try:
            from .services.vector_search_service import (
                VectorSearchService,
                VectorSearchConfig,
            )

            logger.info("Initializing Vector Search service...")

            # Requires orchestrator for GPU coordination
            if not self._orchestrator_service:
                logger.warning("Vector Search service skipped: orchestrator not available")
                return

            # Create config from environment (with HOCON fallback)
            config = VectorSearchConfig.from_env()

            self._vector_search_service = VectorSearchService(
                orchestrator=self._orchestrator_service,
                config=config,
            )

            # Update gRPC service registry
            if self._grpc_server:
                self._grpc_server.update_service(
                    "vector_search_service", self._vector_search_service
                )
                logger.info(
                    f"Vector Search service registered with gRPC "
                    f"(idle_timeout={config.idle_timeout_s}s)"
                )

        except ImportError as e:
            logger.warning(f"Vector Search service not available: {e}")
        except Exception as e:
            logger.error(f"Failed to initialize Vector Search service: {e}")

    async def _maybe_start_ambient(self) -> None:
        """Start Ambient unless the operator stopped it (default-on)."""
        if not self._ambient_service:
            logger.debug("Ambient service not initialized, skipping auto-start")
            return
        if not self.config.startup.auto_start_ambient:
            logger.info("Ambient auto-start disabled in config")
            return
        try:
            result = await self._ambient_service.ensure_started_on_boot()
            logger.info("Ambient boot: %s %s", result.get("status"), result.get("message", ""))
        except Exception as e:
            logger.warning(f"Failed to auto-start ambient: {e}")

    async def _init_daemon_registry(self) -> None:
        """Initialize daemon registry and start all daemons with FAIL-FAST semantics.

        The DaemonRegistry provides:
        - Dependency-ordered startup (topological sort)
        - FAIL-FAST on CRITICAL daemon failures (engine enters DEGRADED mode)
        - Continuous health monitoring via HealthObserver integration

        Daemon dependency order:
            health_observer (CRITICAL, no deps) - must start first
            cognition (CRITICAL, after health_observer)
            reconciliation (REQUIRED, after health_observer)

        CRITICAL failures put engine in DEGRADED mode (doesn't exit) so the ACP agent
        can investigate accumulated error states.
        """
        from .services.base_daemon import EngineState

        logger.info("Initializing daemon registry...")

        # Create daemon registry with 30s timeout per daemon
        self._daemon_registry = DaemonRegistry(startup_timeout=30.0)

        # Initialize daemons (creates instances but doesn't start them)
        # Each daemon's start() will be called by the registry in dependency order

        # 1. Initialize HealthObserver (CRITICAL, no dependencies)
        await self._create_health_observer_daemon()

        # 2. Initialize Cognition (CRITICAL, depends on health_observer)
        await self._create_cognition_daemon()

        # 3. Initialize Reconciliation (REQUIRED, depends on health_observer)
        await self._create_reconciliation_daemon()

        # 4. Initialize MetaAgent (OPTIONAL, depends on health_observer for db_pool)
        await self._create_metaagent_daemon()

        await self._create_nautilus_daemon()

        # 5. Initialize ThetaAgent (NORMAL, no background loop - passive service)
        await self._create_theta_service()

        # 6. Initialize ScheduledTaskProcessor (OPTIONAL, landing page tasks)
        await self._create_scheduled_task_processor()
        # (2026-09-04) The EngineSupervision directive handler consults the
        # processor for live-run knowledge (never reclaim a task whose child is
        # alive); register it so the servicer can find it.
        try:
            if self._grpc_server is not None and self._scheduled_task_processor is not None:
                self._grpc_server.update_service("scheduled_task_processor", self._scheduled_task_processor)
        except Exception as e:  # noqa: BLE001
            logger.debug("scheduled_task_processor registry update skipped: %s", e)

        # Register daemons with dependency ordering
        if self._health_observer_service:
            self._daemon_registry.register(self._health_observer_service, after=[])

        if self._cognition_service:
            self._daemon_registry.register(
                self._cognition_service, after=["health_observer"]
            )

        if self._reconciliation_service:
            self._daemon_registry.register(
                self._reconciliation_service, after=["health_observer"]
            )

        if self._metaagent_service:
            self._daemon_registry.register(
                self._metaagent_service, after=["health_observer"]
            )

        if self._nautilus_service:
            self._daemon_registry.register(
                self._nautilus_service, after=["health_observer"]
            )

        if self._scheduled_task_processor:
            self._daemon_registry.register(
                self._scheduled_task_processor, after=[]
            )

        # Wire cross-references between daemons BEFORE starting
        # This enables escalation from Reconciliation → HealthObserver → ACP
        if self._reconciliation_service and self._health_observer_service:
            self._reconciliation_service.set_health_observer(self._health_observer_service)
            logger.info("Wired Reconciliation → HealthObserver escalation path")

        # Create and wire AgendaTracker for workload-centric incident tracking
        await self._create_agenda_tracker()

        # Start all daemons in topological order
        results = await self._daemon_registry.start_all()

        # LISTEN must execute cognition pipeline types (feed_check, triage,
        # …). Binding after start() so STP default handlers already own
        # article_curate; bind fills the rest. Unknown types stay pending.
        if self._scheduled_task_processor and self._cognition_service:
            self._scheduled_task_processor.bind_cognition(self._cognition_service)
        elif self._scheduled_task_processor and not self._cognition_service:
            logger.error(
                "ScheduledTaskProcessor has no CognitionService to bind.\n"
                "  Guru: #STP.00000003.NOHANDLER\n"
                "  feed_check / triage stay pending until cognition starts."
            )

        # Log startup results
        for result in results:
            if result.success:
                logger.info(f"  {result.daemon_name}: started in {result.duration_ms}ms")
            else:
                logger.error(
                    f"  {result.daemon_name}: FAILED - {result.error} "
                    f"(Guru: {result.guru_code})"
                )

        # Check final engine state
        status = self._daemon_registry.get_status()
        if status.engine_state == EngineState.DEGRADED:
            logger.error(
                f"Engine in DEGRADED mode - CRITICAL daemons failed: "
                f"{status.critical_failures}\n"
                "  The ACP agent should investigate. Error states preserved for analysis."
            )

        # Wire daemon registry to HealthObserver for continuous monitoring
        if self._health_observer_service:
            self._health_observer_service.set_daemon_registry(self._daemon_registry)

        # Update gRPC with daemon registry for status reporting
        if self._grpc_server:
            self._grpc_server.update_service("daemon_registry", self._daemon_registry)

    async def _create_health_observer_daemon(self) -> None:
        """Create HealthObserver daemon instance (doesn't start it)."""
        try:
            from .services.health_observer_service import (
                HealthObserverService,
                ObserverConfig,
            )
            from .services.health_service import HealthService

            logger.info("Creating HealthObserver daemon...")

            # Create health service for basic metrics first
            self._health_service = HealthService()
            self._health_service.set_services(
                orchestrator=self._orchestrator_service,
            )
            await self._health_service.start()

            # Create observer config from engine config
            observer_config = ObserverConfig(
                enabled=True,
                poll_interval=30.0,
                escalate_to_acp=True,
                kb_root=os.environ.get("GAIUS_KB_ROOT", "build/dev"),
            )

            # Create observer service (NOT started yet - registry will start it)
            self._health_observer_service = HealthObserverService(
                config=observer_config,
                orchestrator_service=self._orchestrator_service,
                health_service=self._health_service,
            )

            # Pass db_pool for internal pipeline health checks
            if self._db_pool:
                self._health_observer_service.set_services(db_pool=self._db_pool)
                logger.info("HealthObserver connected to shared db_pool for pipeline monitoring")

            # Update gRPC service registry
            if self._grpc_server:
                self._grpc_server.update_service(
                    "health_observer_service", self._health_observer_service
                )
                self._grpc_server.update_service("health_service", self._health_service)

        except ImportError as e:
            logger.warning(f"HealthObserver not available: {e}")
        except Exception as e:
            logger.error(f"Failed to create HealthObserver: {e}")

    async def _create_cognition_daemon(self) -> None:
        """Create Cognition daemon instance (doesn't start it).

        Called during _init_daemon_registry. The cognition service
        was already initialized in _autonomous_start_cognition if
        auto_start_cognition was enabled - we just need to ensure
        it's available for registration.
        """
        # Cognition service may already be initialized from _autonomous_start_cognition
        # If so, we just use it. If not, it won't be registered.
        if self._cognition_service:
            logger.info("Cognition daemon already initialized, registering with registry")
        else:
            logger.info("Cognition daemon not initialized (auto_start_cognition disabled)")

    async def _create_reconciliation_daemon(self) -> None:
        """Create Reconciliation daemon instance (doesn't start it)."""
        try:
            from .resources import ReconciliationService

            logger.info("Creating Reconciliation daemon...")

            # Create service with resource manager and config
            # Remediation ENABLED by default - self-healing is the point
            self._reconciliation_service = ReconciliationService(
                resource_manager=self._resource_manager,
                config=self.config,
                observe_interval_seconds=10.0,  # Check every 10 seconds
                remediate=True,  # Auto-remediate drift (orphans, unhealthy)
                orchestrator_service=self._orchestrator_service,  # For restarts
            )

            # Update gRPC service registry
            if self._grpc_server:
                self._grpc_server.update_service(
                    "reconciliation_service", self._reconciliation_service
                )

        except ImportError as e:
            logger.warning(f"Reconciliation service not available: {e}")
        except Exception as e:
            logger.error(f"Failed to create Reconciliation daemon: {e}")

    async def _create_nautilus_daemon(self) -> None:
        """Create the Nautilus watcher (Overwatch's model-free detector)."""
        try:
            from .services.nautilus_service import NautilusService

            await self._ensure_db_pool()
            if self._db_pool is None:
                logger.warning("Nautilus skipped: no DB pool")
                return
            logger.info("Creating Nautilus daemon (Overwatch detector)...")
            self._nautilus_service = NautilusService(self._db_pool)
            if self._grpc_server:
                self._grpc_server.update_service(
                    "nautilus_service", self._nautilus_service
                )
        except ImportError as e:
            logger.warning(f"Nautilus service not available: {e}")
        except Exception as e:
            logger.error(f"Failed to create Nautilus daemon: {e}")

    async def _create_metaagent_daemon(self) -> None:
        """Create MetaAgent daemon instance (doesn't start it).

        MetaAgent provides:
        - Metabase model sync (hourly via pg_cron)
        - Weekly LLM audits with pooled budget
        - Quality assessments for synthetic data
        - Audit recommendations tracking
        """
        try:
            from .services.metaagent_service import MetaAgentService

            logger.info("Creating MetaAgent daemon...")

            # Create service with db_pool for direct DB access
            self._metaagent_service = MetaAgentService(db_pool=self._db_pool)

            # Update gRPC service registry
            if self._grpc_server:
                self._grpc_server.update_service(
                    "metaagent_service", self._metaagent_service
                )

            logger.info("MetaAgent daemon created (Metabase sync, audits, budget)")

        except ImportError as e:
            logger.warning(f"MetaAgent service not available: {e}")
        except Exception as e:
            logger.error(f"Failed to create MetaAgent daemon: {e}")

    async def _create_theta_service(self) -> None:
        """Create ThetaService for situational awareness and consolidation.

        ThetaService wraps ThetaAgent with Engine-First gRPC integration.
        It's a passive service (NORMAL criticality) that responds to requests,
        not a background daemon that polls for work.

        Provides:
        - /sitrep: Situational awareness reports
        - /consolidate: NVAR-mediated temporal consolidation
        - Consolidation statistics
        """
        try:
            import os
            from .services.theta_service import ThetaService, ThetaConfig

            logger.info("Creating ThetaService...")

            # Get KB root from environment or use default
            kb_root = os.getenv("GAIUS_KB_ROOT", "build/dev")

            # Create service with config
            self._theta_service = ThetaService(
                config=ThetaConfig(kb_root=kb_root),
                db_pool=self._db_pool,
            )

            # Start the service (marks it as running)
            await self._theta_service.start()

            # Update gRPC service registry
            if self._grpc_server:
                self._grpc_server.update_service(
                    "theta_service", self._theta_service
                )

            logger.info("ThetaService created (sitrep, consolidation)")

        except ImportError as e:
            logger.warning(f"ThetaService not available: {e}")
        except Exception as e:
            logger.error(f"Failed to create ThetaService: {e}")

    async def _create_scheduled_task_processor(self) -> None:
        """Create ScheduledTaskProcessor for pg_cron task execution.

        Listens on 'scheduled_task_ready' channel for tasks inserted by pg_cron.
        Handles:
        - publish_cards: Publish pending cards to Cloudflare KV
        - article_curate: Trigger ArticleCurationFlow

        OPTIONAL criticality - landing page tasks aren't critical to engine.
        Prospects check/update catch up on start (daily Data Product clock).
        """
        try:
            from .services.scheduled_task_processor import ScheduledTaskProcessor

            logger.info("Creating ScheduledTaskProcessor...")

            self._scheduled_task_processor = ScheduledTaskProcessor()

            # Note: Don't start here - daemon registry will start it
            # This allows proper dependency ordering

            logger.info("ScheduledTaskProcessor created (publish_cards, article_curate, prospects_check, prospects_update)")

        except ImportError as e:
            logger.warning(f"ScheduledTaskProcessor not available: {e}")
        except Exception as e:
            logger.error(f"Failed to create ScheduledTaskProcessor: {e}")

    async def _create_agenda_tracker(self) -> None:
        """Create and wire AgendaTracker for workload-centric incident tracking.

        The AgendaTracker bridges:
        - OrchestratorService (workload begin/complete lifecycle)
        - ReconciliationService (endpoint state transitions)
        - HealthObserverService (incident escalation)

        It tracks Agenda incidents where:
        - Agenda (scheduled capability phases) is the unit of health
        - Makespan fulfillment is the success metric
        - Positive control is required for resolution
        """
        try:
            from .services.agenda_tracker import AgendaTracker

            logger.info("Creating AgendaTracker...")

            # Create tracker with database pool for persistence
            self._agenda_tracker = AgendaTracker(
                db_pool=self._db_pool,
                baseline_endpoints=["orchestrator", "thinking"],
            )

            # Wire to OrchestratorService
            if self._orchestrator_service:
                self._orchestrator_service.set_agenda_tracker(self._agenda_tracker)
                logger.info("Wired AgendaTracker → OrchestratorService")

            # Wire to ReconciliationService for endpoint transition callbacks
            if self._reconciliation_service:
                self._reconciliation_service.set_agenda_tracker(self._agenda_tracker)
                logger.info("Wired AgendaTracker ← ReconciliationService")

            # Wire to AmbientWorkloadService for phase event tracking
            if self._ambient_service:
                self._ambient_service.set_agenda_tracker(self._agenda_tracker)
                logger.info("Wired AgendaTracker → AmbientWorkloadService")

            # Start the tracker (restores from DB, starts persistence loop)
            await self._agenda_tracker.start()

            # Wire to HealthObserverService for incident escalation
            if self._health_observer_service:
                # AgendaTracker notifies HealthObserver when control degrades
                self._agenda_tracker.on_control_degraded(self._on_agenda_control_degraded)
                logger.info("Wired AgendaTracker → HealthObserverService callbacks")

            # Update gRPC service registry
            if self._grpc_server:
                self._grpc_server.update_service("agenda_tracker", self._agenda_tracker)

            logger.info(
                f"AgendaTracker started with "
                f"{len(self._agenda_tracker.get_active_operations())} active operations"
            )

        except ImportError as e:
            logger.warning(f"AgendaTracker not available: {e}")
        except Exception as e:
            logger.error(f"Failed to create AgendaTracker: {e}")

    async def _on_agenda_control_degraded(self, operation) -> None:
        """Callback when an operation's control mode degrades from POSITIVE.

        This indicates that an endpoint transition was not orchestrated (e.g.,
        failure recovery or restart recovery), which may require investigation.

        Args:
            operation: AgendaOperation with degraded control mode
        """
        from .incidents import ControlMode

        logger.warning(
            f"Operation {operation.workload_id} control degraded to {operation.control_mode.value}"
        )

        # Escalate to HealthObserver if control mode is particularly bad
        if self._health_observer_service and operation.control_mode == ControlMode.RESTART_RECOVERY:
            await self._escalate_operation_to_health_observer(operation)

    async def _escalate_operation_to_health_observer(self, operation) -> None:
        """Escalate an operation with degraded control to HealthObserver.

        Creates a synthetic health incident so ACP can investigate why
        the operation required restart/failure recovery instead of
        positive orchestrated control.

        Args:
            operation: AgendaOperation with degraded control mode
        """
        if not self._health_observer_service:
            return

        try:
            from .services.health_observer_service import HealthIncident
            from uuid import uuid4

            # Create a synthetic health incident for the degraded operation
            fingerprint = f"CONTROL_DEGRADED:{operation.workload_id}"

            health_incident = HealthIncident(
                incident_id=uuid4(),
                fingerprint=fingerprint,
                endpoint=operation.phases[0].name if operation.phases else "unknown",
                failure_mode_id="CONTROL_DEGRADED",
                rpn_score=200,  # Moderate severity
                rpn_severity=6,
                rpn_occurrence=5,
                rpn_detection=5,
                current_tier=1,  # Start at Tier 1 (local remediation)
                attempts=0,
            )

            # Add operation context to the incident
            health_incident.context = {
                "workload_id": operation.workload_id,
                "workload_type": operation.workload_type.value if hasattr(operation.workload_type, 'value') else str(operation.workload_type),
                "control_mode": operation.control_mode.value,
                "endpoint_transitions": len(operation.endpoint_transitions),
            }

            # Register with HealthObserver
            self._health_observer_service._active_incidents[fingerprint] = health_incident
            self._health_observer_service._incidents_created += 1

            logger.info(
                f"Escalated degraded operation {operation.workload_id} to HealthObserver "
                f"(control={operation.control_mode.value})"
            )

        except Exception as e:
            logger.error(f"Failed to escalate operation to HealthObserver: {e}")

    async def _start_grpc_server(self) -> None:
        """Start the gRPC server (PRIMARY transport).

        Initializes and starts the gRPC server with both:
        - KServe Open Inference Protocol (GRPCInferenceService)
        - Gaius custom extensions (GaiusService)
        """
        if not self.config.grpc.enabled:
            logger.info("gRPC server disabled by configuration")
            return

        try:
            from .grpc import GrpcServer, GrpcConfig

            # Convert engine config to gRPC config
            grpc_config = GrpcConfig(
                enabled=self.config.grpc.enabled,
                host=self.config.grpc.host,
                port=self.config.grpc.port,
                max_workers=self.config.grpc.max_workers,
                max_message_size=self.config.grpc.max_message_size,
            )

            # Create gRPC server
            self._grpc_server = GrpcServer(grpc_config)

            # Register backend services
            self._grpc_server.set_services(
                backend_router=self._backend_router,
                orchestrator_service=self._orchestrator_service,
                cognition_service=self._cognition_service,
                topology_service=self._topology_service,
                config=self.config,
                start_time=self._start_time.timestamp() if self._start_time else None,
                get_health_metrics=self._collect_health_metrics,
                get_evolution_status=self._get_evolution_status,
                trigger_evolution=self._trigger_evolution,
                start_evolution=self._start_evolution,
                stop_evolution=self._stop_evolution,
            )

            # Start the server
            await self._grpc_server.start()

        except ImportError as e:
            logger.warning(f"gRPC dependencies not installed: {e}")
            logger.warning("Install with: uv sync --extra grpc")
        except Exception as e:
            logger.error(f"Failed to start gRPC server: {e}")
            raise

    async def _get_evolution_status(self) -> dict:
        """Get current evolution daemon status."""
        return {
            "running": False,
            "mode": self.config.evolution.strategy,
            "cycles_completed": 0,
            "current_agent": None,
            "next_agent": self.config.evolution.rotation[0]
            if self.config.evolution.rotation
            else None,
        }

    async def _trigger_evolution(self, agent_id: str = "") -> dict:
        """Trigger an evolution cycle."""
        return {"triggered": True, "agent_id": agent_id or "next_in_rotation"}

    async def _start_evolution(self) -> dict:
        """Start the evolution daemon."""
        return {"started": True}

    async def _stop_evolution(self) -> dict:
        """Stop the evolution daemon."""
        return {"stopped": True}

    async def stop(self) -> None:
        """Stop the engine daemon."""
        logger.info("Stopping Gaius Engine...")
        self._running = False

        # Cancel background tasks
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
        coord = getattr(self, "_coordination", None)
        if coord is not None:
            try:
                await coord.stop()
            except Exception:  # noqa: BLE001
                logger.debug("coordination watcher stop skipped", exc_info=True)

        # Stop all daemons via registry (in reverse dependency order)
        if self._daemon_registry:
            logger.info("Stopping all daemons via registry...")
            await self._daemon_registry.stop_all()

        # Stop evolution daemon (not yet in registry)
        if self._evolution_daemon:
            try:
                await self._evolution_daemon.stop()
            except Exception as e:
                logger.warning(f"Error stopping evolution daemon: {e}")

        # Stop flow scheduler service (not yet in registry)
        if self._flow_scheduler_service:
            try:
                await self._flow_scheduler_service.stop()
            except Exception as e:
                logger.warning(f"Error stopping flow scheduler: {e}")

        # Stop dataset service (not yet in registry)
        if self._dataset_service:
            try:
                await self._dataset_service.stop()
            except Exception as e:
                logger.warning(f"Error stopping dataset service: {e}")

        # Stop engine scheduler service
        scheduler_service = getattr(self, "_scheduler_service", None)
        if scheduler_service:
            try:
                await scheduler_service.stop()
            except Exception as e:
                logger.warning(f"Error stopping scheduler service: {e}")

        # Stop orchestrator service
        if self._orchestrator_service:
            await self._orchestrator_service.stop()

        # Stop gRPC server
        if self._grpc_server:
            await self._grpc_server.stop()

        # Stop backend router (stops optillm and vLLM)
        if self._backend_router:
            await self._backend_router.stop()

        logger.info("Gaius Engine stopped")

    async def run(self) -> None:
        """Run the engine until interrupted."""
        await self.start()

        # Wait for shutdown signal
        stop_event = asyncio.Event()

        def signal_handler():
            stop_event.set()

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)

        await stop_event.wait()
        await self.stop()

    async def _init_telemetry(self) -> None:
        """Initialize OpenTelemetry if configured.

        Uses the core telemetry module with engine entry point for proper
        service.name distinction in observability platforms.
        """
        try:
            from ..core.telemetry import init_from_config

            # Create a minimal config wrapper if needed
            class ConfigWrapper:
                def __init__(self, telemetry_config):
                    self.telemetry = telemetry_config

            init_from_config(ConfigWrapper(self.config.telemetry), entry_point="engine")
            logger.info(
                f"OpenTelemetry initialized with entry_point=engine: {self.config.telemetry.endpoint}"
            )
        except ImportError:
            logger.warning("OpenTelemetry packages not installed, tracing disabled")
        except Exception as e:
            logger.warning(f"Failed to initialize OpenTelemetry: {e}")

    async def _health_broadcast_loop(self) -> None:
        """Internal health metrics collection loop.

        Note: Health metrics are now exposed via gRPC HealthObserver service.
        This loop maintains internal state for gRPC queries.
        """
        interval = self.config.health_interval_ms / 1000.0

        while self._running:
            try:
                await self._collect_health_metrics()
            except Exception as e:
                logger.debug(f"Health collection error: {e}")

            await asyncio.sleep(interval)

    async def _collect_health_metrics(self) -> HealthMetrics:
        """Collect current health metrics from HealthService."""
        gpus = []
        endpoints = []
        queue_depth = 0
        evolution_running = False
        evolution_agent = ""

        # Collect GPU metrics from HealthService
        if self._health_service:
            try:
                gpu_health = self._health_service.get_gpu_health()
                for gpu_id, gpu_data in gpu_health.items():
                    gpus.append({
                        "id": gpu_id,
                        "utilization": gpu_data.get("utilization_pct", 0.0) / 100.0,
                        "memory_used_gb": gpu_data.get("memory_used_mb", 0) / 1024.0,
                        "memory_total_gb": gpu_data.get("memory_total_mb", 0) / 1024.0,
                        "temperature_c": gpu_data.get("temperature_c", 0),
                        "power_watts": gpu_data.get("power_watts", 0),
                    })
            except Exception as e:
                logger.debug(f"Failed to collect GPU metrics: {e}")

        # Collect optillm health from BackendRouter
        if self._backend_router:
            try:
                optillm_status = self._backend_router.optillm.get_status()
                endpoints.append({
                    "name": "optillm",
                    "model": "optillm-proxy",
                    "healthy": optillm_status.get("healthy", False),
                    "requests_served": 0,
                    "avg_latency_ms": 0.0,
                })
            except Exception as e:
                logger.debug(f"Failed to collect optillm metrics: {e}")

        # Collect endpoint metrics from OrchestratorService
        if self._orchestrator_service:
            try:
                status = self._orchestrator_service.get_status()
                for name, ep_data in status.get("endpoints", {}).items():
                    endpoints.append({
                        "name": name,
                        "model": ep_data.get("model", ""),
                        "healthy": ep_data.get("status") in ("healthy", "PROCESS_STATUS_HEALTHY"),
                        "requests_served": ep_data.get("requests_served", 0),
                        "avg_latency_ms": ep_data.get("avg_latency_ms", 0.0),
                    })
            except Exception as e:
                logger.debug(f"Failed to collect endpoint metrics: {e}")

        # Collect evolution daemon status
        if self._evolution_daemon:
            try:
                evo_status = self._evolution_daemon.get_status()
                evolution_running = evo_status.get("running", False)
                evolution_agent = evo_status.get("current_agent", "")
            except Exception as e:
                logger.debug(f"Failed to collect evolution status: {e}")

        return HealthMetrics.create(
            gpus=gpus,
            endpoints=endpoints,
            queue_depth=queue_depth,
            evolution_running=evolution_running,
            evolution_agent=evolution_agent,
        )

    # =========================================================================
    # Service Handlers - delegate to service implementations
    # =========================================================================

    async def _handle_orchestrator(self, request: Request) -> Response:
        """Handle orchestrator service requests.

        Delegates to the actual OrchestratorService for authentic operations.
        """
        action = request.action

        # Ensure orchestrator service is initialized
        if not self._orchestrator_service:
            return Response.failure(
                request.id,
                code=503,
                message="OrchestratorService not initialized",
            )

        try:
            if action == "status":
                # Delegate to OrchestratorService.get_status()
                status = self._orchestrator_service.get_status()
                # Add config info not in service status
                status["total_gpus"] = self.config.gpus.total
                status["available_gpus"] = (
                    self.config.gpus.total - len(self.config.gpus.reserved)
                )
                status["evolution_enabled"] = self.config.evolution.enabled
                return Response.success(request.id, status)

            elif action == "list_agents":
                agents = [
                    {
                        "name": a.name,
                        "alias": a.alias,
                        "model": a.model,
                        "backend": a.backend,
                    }
                    for a in self.config.agents.values()
                ]
                return Response.success(request.id, {"agents": agents})

            elif action == "ensure":
                # Agent-first: ensure endpoint is available, starting if needed
                endpoint = request.params.get("endpoint", "")
                if not endpoint:
                    return Response.failure(
                        request.id,
                        code=400,
                        message="endpoint parameter required",
                    )
                status = await self._orchestrator_service.ensure_endpoint(endpoint)
                is_healthy = status.status in ("healthy", "optillm")
                return Response.success(
                    request.id,
                    {
                        "endpoint": endpoint,
                        "healthy": is_healthy,
                        "status": status.status,
                        "port": status.port,
                        "gpu_ids": status.gpu_ids,
                        "pid": status.pid,
                        "model": status.model,
                        "message": status.startup_message if not is_healthy else "",
                    },
                )

            elif action == "start":
                endpoint = request.params.get("endpoint", "")
                if not endpoint:
                    return Response.failure(
                        request.id,
                        code=400,
                        message="endpoint parameter required",
                    )
                status = await self._orchestrator_service.start_endpoint(endpoint)
                return Response.success(
                    request.id,
                    {
                        "started": endpoint,
                        "status": status.status,
                        "port": status.port,
                        "gpu_ids": status.gpu_ids,
                        "pid": status.pid,
                    },
                )

            elif action == "stop":
                endpoint = request.params.get("endpoint", "")
                if not endpoint:
                    return Response.failure(
                        request.id,
                        code=400,
                        message="endpoint parameter required",
                    )
                success = await self._orchestrator_service.stop_endpoint(endpoint)
                return Response.success(
                    request.id,
                    {"stopped": endpoint, "success": success},
                )

            elif action == "restart":
                endpoint = request.params.get("endpoint", "")
                if not endpoint:
                    return Response.failure(
                        request.id,
                        code=400,
                        message="endpoint parameter required",
                    )
                status = await self._orchestrator_service.restart_endpoint(endpoint)
                return Response.success(
                    request.id,
                    {
                        "restarted": endpoint,
                        "status": status.status,
                        "port": status.port,
                        "gpu_ids": status.gpu_ids,
                        "pid": status.pid,
                    },
                )

            elif action == "logs":
                endpoint = request.params.get("endpoint", "")
                lines = request.params.get("lines", 50)
                if not endpoint:
                    return Response.failure(
                        request.id,
                        code=400,
                        message="endpoint parameter required",
                    )
                logs = self._orchestrator_service.get_endpoint_logs(endpoint, lines)
                return Response.success(
                    request.id,
                    {"endpoint": endpoint, "lines": logs},
                )

            elif action == "clean_start":
                endpoints = request.params.get("endpoints", ["reasoning"])
                result = await self._orchestrator_service.clean_start(endpoints)
                return Response.success(request.id, result)

            elif action == "health_check":
                # Force a health check cycle
                await self._orchestrator_service._check_endpoint_health()
                return Response.success(
                    request.id,
                    {"checked": True, "status": self._orchestrator_service.get_status()},
                )

            elif action == "reconcile":
                # State reconciliation using FSM-based service
                if self._reconciliation_service:
                    results = await self._reconciliation_service.observe_once()
                    # Convert results to dict format
                    result = {
                        "endpoints": {
                            name: {
                                "expected": r.expected_state.value,
                                "actual": r.actual_state.value,
                                "drifted": r.is_drifted,
                            }
                            for name, r in results.items()
                        },
                        "drift_detected": any(r.is_drifted for r in results.values()),
                    }
                    return Response.success(request.id, result)
                else:
                    # Fallback to legacy reconciliation
                    result = await self._orchestrator_service.reconcile_state()
                    return Response.success(request.id, result)

            elif action == "reconcile_status":
                # Get reconciliation service status
                if self._reconciliation_service:
                    status = self._reconciliation_service.get_status()
                    return Response.success(request.id, status)
                else:
                    return Response.failure(
                        request.id,
                        code=503,
                        message="Reconciliation service not initialized",
                    )

            elif action == "enable_remediation":
                # Enable or disable automatic remediation
                if self._reconciliation_service:
                    enable = request.params.get("enable", True)
                    self._reconciliation_service.enable_remediation(enable)
                    # Also set the orchestrator service for UNHEALTHY remediation
                    if enable and self._orchestrator_service:
                        self._reconciliation_service.set_orchestrator_service(
                            self._orchestrator_service
                        )
                    return Response.success(
                        request.id,
                        {
                            "remediation_enabled": enable,
                            "message": f"Remediation {'enabled' if enable else 'disabled'}",
                        },
                    )
                else:
                    return Response.failure(
                        request.id,
                        code=503,
                        message="Reconciliation service not initialized",
                    )

            elif action == "discover":
                # Discover what's actually running (diagnostic)
                actual = await self._orchestrator_service.discover_actual_state()
                return Response.success(request.id, {"actual_state": actual})

            else:
                return Response.failure(
                    request.id, code=400, message=f"Unknown action: {action}"
                )

        except ValueError as e:
            return Response.failure(request.id, code=400, message=str(e))
        except Exception as e:
            logger.error(f"Orchestrator handler error: {e}")
            return Response.failure(request.id, code=500, message=str(e))

    async def _handle_scheduler(self, request: Request) -> Response:
        """Handle scheduler service requests."""
        action = request.action

        if action == "status":
            # Get backend status
            backend_status = {}
            if self._backend_router:
                backend_status = self._backend_router.get_status()

            return Response.success(
                request.id,
                {
                    "queue_depth": 0,
                    "active_requests": 0,
                    "backends": backend_status,
                },
            )
        elif action == "complete":
            # Synchronous completion via backend router
            if not self._backend_router:
                return Response.failure(
                    request.id, code=503, message="Backend router not initialized"
                )

            prompt = request.params.get("prompt", "")
            agent = request.params.get("agent", "thinking")
            system_prompt = request.params.get("system_prompt")
            temperature = request.params.get("temperature", 0.7)
            max_tokens = request.params.get("max_tokens", 2048)
            technique = request.params.get("technique")

            try:
                response = await self._backend_router.complete(
                    prompt=prompt,
                    agent_alias=agent,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    technique=technique,
                    task_type="engine_inference",
                )

                return Response.success(
                    request.id,
                    {
                        "content": response.content,
                        "model": response.model,
                        "backend": response.backend,
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                        "latency_ms": response.latency_ms,
                        "technique": response.technique,
                        "error": response.error,
                    },
                )
            except Exception as e:
                return Response.failure(
                    request.id, code=500, message=str(e)
                )
        elif action == "submit":
            # Async job submission (queued)
            prompt = request.params.get("prompt", "")
            model = request.params.get("model", "")
            return Response.success(
                request.id,
                {
                    "job_id": f"job-{request.id[:8]}",
                    "status": "queued",
                    "model": model,
                },
            )
        elif action == "get_result":
            job_id = request.params.get("job_id", "")
            return Response.success(
                request.id,
                {
                    "job_id": job_id,
                    "status": "pending",
                    "result": None,
                },
            )
        elif action == "budget":
            # XAI budget status
            return Response.success(
                request.id,
                {
                    "daily_used": 0,
                    "daily_limit": 50,
                    "weekly_used": 0,
                    "weekly_limit": 200,
                },
            )
        else:
            return Response.failure(
                request.id, code=400, message=f"Unknown action: {action}"
            )

    async def _handle_evolution(self, request: Request) -> Response:
        """Handle evolution service requests."""
        from .services.evolution_service import EvolutionService

        action = request.action

        if action == "status":
            return Response.success(
                request.id,
                {
                    "running": False,
                    "cycles_completed": 0,
                    "total_improvement_pct": 0.0,
                    "current_agent": None,
                    "next_agent": self.config.evolution.rotation[0]
                    if self.config.evolution.rotation
                    else None,
                    "min_idle_gpus": self.config.evolution.min_idle_gpus,
                    "strategy": self.config.evolution.strategy,
                },
            )
        elif action == "trigger":
            agent_id = request.params.get("agent_id", "")
            return Response.success(
                request.id,
                {
                    "triggered": True,
                    "agent_id": agent_id or "next_in_rotation",
                },
            )
        elif action == "start":
            return Response.success(request.id, {"started": True})
        elif action == "stop":
            return Response.success(request.id, {"stopped": True})
        else:
            return Response.failure(
                request.id, code=400, message=f"Unknown action: {action}"
            )

    async def _handle_grid(self, request: Request) -> Response:
        """Handle grid service requests."""
        from .compute.grid_service import GridService

        action = request.action

        if action == "status":
            return Response.success(
                request.id,
                {
                    "cached_projections": 0,
                    "method": "umap",
                    "grid_size": 19,
                },
            )
        elif action == "project":
            # Project embeddings to grid
            embeddings = request.params.get("embeddings", [])
            return Response.success(
                request.id,
                {
                    "points": [],
                    "coverage": 0.0,
                    "n_documents": len(embeddings),
                },
            )
        else:
            return Response.failure(
                request.id, code=400, message=f"Unknown action: {action}"
            )

    async def _handle_tda(self, request: Request) -> Response:
        """Handle TDA service requests."""
        from .compute.tda_service import TDAService

        action = request.action

        if action == "status":
            return Response.success(
                request.id,
                {
                    "cached_results": 0,
                    "max_dimension": 2,
                },
            )
        elif action == "compute":
            embeddings = request.params.get("embeddings", [])
            return Response.success(
                request.id,
                {
                    "h0_count": 0,
                    "h1_count": 0,
                    "h2_count": 0,
                    "entropy": 0.0,
                },
            )
        else:
            return Response.failure(
                request.id, code=400, message=f"Unknown action: {action}"
            )

    async def _handle_health(self, request: Request) -> Response:
        """Handle health service requests."""
        from .services.health_service import HealthService

        action = request.action

        if action == "status":
            uptime = (
                (datetime.now() - self._start_time).total_seconds()
                if self._start_time
                else 0
            )
            return Response.success(
                request.id,
                {
                    "healthy": True,
                    "uptime_seconds": uptime,
                    "version": "0.2.0",
                    "agents_configured": len(self.config.agents),
                    "services": {
                        "orchestrator": True,
                        "scheduler": True,
                        "evolution": self.config.evolution.enabled,
                        "grid": True,
                        "tda": True,
                    },
                },
            )
        elif action == "metrics":
            return Response.success(
                request.id,
                {
                    "gpus": [],
                    "endpoints": [],
                    "queue_depth": 0,
                },
            )
        else:
            return Response.failure(
                request.id, code=400, message=f"Unknown action: {action}"
            )

    async def _handle_cognition(self, request: Request) -> Response:
        """Handle cognition service requests.

        Actions:
        - status: Get cognition daemon status
        - trigger: Manually trigger a cognition cycle
        - start: Start the cognition daemon
        - stop: Stop the cognition daemon
        - pending: Get pending scheduled tasks
        - recent: Get recently completed tasks
        """
        from .services.cognition_service import CognitionService, CognitionConfig

        action = request.action

        if action == "status":
            if self._cognition_service:
                status = self._cognition_service.get_status()
            else:
                status = {
                    "running": False,
                    "status": "NOT_INITIALIZED",
                    "cycles_completed": 0,
                    "tasks_processed": 0,
                }
            return Response.success(request.id, status)

        elif action == "trigger":
            if not self._cognition_service:
                return Response.failure(
                    request.id, code=503, message="Cognition service not initialized"
                )

            task_type = request.params.get("task_type", "cognition_cycle")
            payload = request.params.get("payload", {})

            try:
                result = await self._cognition_service.trigger(task_type, payload)
                return Response.success(request.id, result)
            except Exception as e:
                return Response.failure(request.id, code=500, message=str(e))

        elif action == "start":
            if self._cognition_service and self._cognition_service.is_running:
                return Response.success(
                    request.id, {"started": False, "reason": "already_running"}
                )

            # Initialize cognition service if needed
            if not self._cognition_service:
                # Get max_cycles_per_hour from config if available
                cognition_cfg = getattr(self.config, "cognition", None)
                max_cycles = getattr(cognition_cfg, "max_cycles_per_hour", 4) if cognition_cfg else 4
                config = CognitionConfig(
                    max_cycles_per_hour=max_cycles,
                    poll_interval_seconds=30.0,
                )
                self._cognition_service = CognitionService(
                    config,
                    get_gpu_idle=lambda: True,  # TODO: wire up to health service
                )

            await self._cognition_service.start()
            return Response.success(request.id, {"started": True})

        elif action == "stop":
            if self._cognition_service:
                await self._cognition_service.stop()
                return Response.success(request.id, {"stopped": True})
            return Response.success(
                request.id, {"stopped": False, "reason": "not_running"}
            )

        elif action == "pending":
            if not self._cognition_service:
                return Response.success(request.id, {"tasks": []})

            limit = request.params.get("limit", 10)
            tasks = await self._cognition_service.get_pending_tasks(limit)
            return Response.success(request.id, {"tasks": tasks})

        elif action == "recent":
            if not self._cognition_service:
                return Response.success(request.id, {"tasks": []})

            limit = request.params.get("limit", 10)
            tasks = await self._cognition_service.get_recent_completed(limit)
            return Response.success(request.id, {"tasks": tasks})

        elif action == "recent_thoughts":
            # Get recent thoughts from the cognition service (engine-native)
            cognition = self._cognition_service
            if not cognition:
                return Response.success(request.id, {"thoughts": []})

            limit = request.params.get("limit", 10)
            try:
                thoughts = await cognition.get_recent_thoughts(limit=limit)
                return Response.success(request.id, {"thoughts": thoughts})

            except Exception as e:
                logger.debug(f"Failed to get recent thoughts: {e}")
                return Response.success(request.id, {"thoughts": []})

        elif action == "activity":
            # Get comprehensive activity summary (signs of life)
            activity = {
                "cognition_running": False,
                "cycles_completed": 0,
                "last_cycle_at": None,
                "current_task": None,
                "thoughts_today": 0,
            }

            cognition_svc = self._cognition_service
            if cognition_svc:
                status = cognition_svc.get_status()
                activity["cognition_running"] = status.get("running", False)
                activity["cycles_completed"] = status.get("cycles_completed", 0)
                activity["last_cycle_at"] = status.get("last_cycle_at")
                activity["current_task"] = (
                    status.get("current_task", {}).get("task_type")
                    if status.get("current_task")
                    else None
                )

                # Try to get thought count for today (engine-native)
                try:
                    thoughts = await cognition_svc.get_recent_thoughts(limit=100)
                    activity["thoughts_today"] = len(thoughts)
                except Exception:
                    pass

            return Response.success(request.id, activity)

        else:
            return Response.failure(
                request.id, code=400, message=f"Unknown action: {action}"
            )


def main():
    """Entry point for gaius-engine command."""
    # Fork-safety net (2026-08-28): force this engine process's default
    # multiprocessing start method to 'spawn'. A library that spawns a raw
    # multiprocessing.Pool — GraphRicciCurvature did, defaulting to proc=64 with
    # the FORK start method — would otherwise fork the whole engine, each worker
    # inheriting the :50051 listen socket, live thinking connections, and locked
    # threads; a deadlocked worker became a rogue duplicate engine that jammed
    # thinking for hours. spawn re-imports rather than inheriting, so no engine
    # state crosses the boundary. Safe here: engine __main__ is guarded, joblib is
    # already pinned to the threading backend, and the known forker (Ricci) also
    # carries proc=1 — this closes the class, not just the one door.
    import multiprocessing

    try:
        multiprocessing.set_start_method("spawn", force=True)
    except RuntimeError:
        pass

    parser = argparse.ArgumentParser(
        description="Gaius Engine - Centralized inference and evolution daemon"
    )
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        help="Path to config file (default: config/agents.conf)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.debug else (logging.INFO if args.verbose else logging.WARNING)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load config
    config = load_config(args.config)

    try:
        from gaius.flows.config import apply_metaflow_config

        apply_metaflow_config()
    except Exception:
        logging.getLogger("gaius.engine").debug(
            "platform Metaflow env not applied at engine boot",
            exc_info=True,
        )

    # Create and run engine
    engine = GaiusEngine(config)

    try:
        asyncio.run(engine.run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
