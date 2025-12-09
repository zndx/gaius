"""Gaius Engine server - main daemon loop.

The engine server:
1. Loads configuration from HOCON
2. Starts gRPC server (PRIMARY transport)
3. Starts Aeron IPC bridge (optional/legacy)
4. Routes requests to services
5. Broadcasts events and health metrics
6. Provides Unix socket fallback for debugging
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import EngineConfig, load_config
from .transport.aeron_bridge import AeronBridge, AeronMessage, create_bridge
from .transport.protocol import (
    Request,
    Response,
    Event,
    EventType,
    HealthMetrics,
    Service,
    deserialize_request,
    serialize_response,
    serialize_event,
    serialize_health_metrics,
    start_span_from_request,
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
        self._bridge: Optional[AeronBridge] = None
        self._running = False
        self._health_task: Optional[asyncio.Task] = None
        self._request_task: Optional[asyncio.Task] = None
        self._start_time: Optional[datetime] = None

        # gRPC server (PRIMARY transport)
        self._grpc_server = None

        # Unix socket server (fallback for debugging/CLI)
        self._socket_server: Optional[asyncio.Server] = None
        self._socket_path = os.environ.get(
            "GAIUS_ENGINE_SOCKET", "/tmp/gaius-engine.sock"
        )

        # Backend router for inference (manages optillm and vLLM)
        self._backend_router = None

        # Orchestrator service for endpoint management
        self._orchestrator_service = None

        # Evolution daemon
        self._evolution_daemon = None

        # Service handlers (to be implemented in later phases)
        self._handlers: dict[Service, callable] = {
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

    async def start(self) -> None:
        """Start the engine daemon."""
        logger.info("Starting Gaius Engine...")
        self._start_time = datetime.now()

        # Initialize telemetry if enabled
        if self.config.telemetry.enabled:
            await self._init_telemetry()

        # Initialize backend router (manages optillm and vLLM)
        await self._init_backends()

        # Initialize orchestrator service for endpoint management
        await self._init_orchestrator()

        # Autonomous startup: clean start if configured
        if self.config.startup.clean_start:
            await self._autonomous_clean_start()

        # Start gRPC server (PRIMARY transport)
        await self._start_grpc_server()

        # Create and start Aeron bridge (optional/legacy)
        try:
            self._bridge = create_bridge(self.config.aeron)
            await self._bridge.start()

            # Subscribe to request stream
            await self._bridge.subscribe(
                self.config.aeron.request_stream, self._on_request
            )
            logger.info(f"Aeron bridge started on streams: requests={self.config.aeron.request_stream}")
        except Exception as e:
            logger.warning(f"Aeron bridge not started: {e}")
            self._bridge = None

        # Start Unix socket server (fallback for debugging/CLI)
        await self._start_socket_server()

        self._running = True

        # Start background tasks
        self._health_task = asyncio.create_task(self._health_broadcast_loop())
        self._request_task = asyncio.create_task(self._request_loop())

        # Autonomous startup: start evolution daemon if configured
        if self.config.startup.auto_start_evolution and self.config.evolution.enabled:
            await self._autonomous_start_evolution()

        # Autonomous startup: start cognition daemon if configured
        if self.config.startup.auto_start_cognition:
            await self._autonomous_start_cognition()

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

        self._orchestrator_service = OrchestratorService(
            config=self.config,
            resource_manager=self._resource_manager,
            backend_router=self._backend_router,
        )
        await self._orchestrator_service.start()
        logger.info("Orchestrator service initialized")

    async def _autonomous_clean_start(self) -> None:
        """Perform autonomous clean start: cleanup stale processes and preload endpoints."""
        logger.info("Performing autonomous clean start...")

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
            self._evolution_daemon = EvolutionDaemon(
                config=evo_config,
                get_gpu_utilization=self._orchestrator_service.get_gpu_utilization,
                is_gpu_idle=self._orchestrator_service.is_gpu_idle,
            )
            await self._evolution_daemon.start()
            logger.info("Evolution daemon started")

        except ImportError as e:
            logger.warning(f"Evolution daemon not available: {e}")
        except Exception as e:
            logger.error(f"Failed to start evolution daemon: {e}")

    async def _autonomous_start_cognition(self) -> None:
        """Start the cognition daemon automatically.

        The cognition daemon polls scheduled_tasks for cognition_cycle,
        engine_audit, and delta_check tasks inserted by pg_cron.
        """
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

            # Create and start service
            self._cognition_service = CognitionService(
                config,
                get_gpu_idle=lambda: True,  # TODO: wire up to health service
            )
            await self._cognition_service.start()
            logger.info("Cognition daemon started")

            # Update gRPC service registry (cognition starts after gRPC)
            if self._grpc_server:
                self._grpc_server.update_service("cognition_service", self._cognition_service)

        except ImportError as e:
            logger.warning(f"Cognition service not available: {e}")
        except Exception as e:
            logger.error(f"Failed to start cognition daemon: {e}")

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

        if self._request_task:
            self._request_task.cancel()
            try:
                await self._request_task
            except asyncio.CancelledError:
                pass

        # Stop evolution daemon
        if self._evolution_daemon:
            try:
                await self._evolution_daemon.stop()
            except Exception as e:
                logger.warning(f"Error stopping evolution daemon: {e}")

        # Stop orchestrator service
        if self._orchestrator_service:
            await self._orchestrator_service.stop()

        # Stop gRPC server (PRIMARY transport)
        if self._grpc_server:
            await self._grpc_server.stop()

        # Stop Aeron bridge
        if self._bridge:
            await self._bridge.stop()

        # Stop socket server
        await self._stop_socket_server()

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
        """Initialize OpenTelemetry if configured."""
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            resource = Resource.create(
                {
                    "service.name": self.config.telemetry.service_name,
                    "service.version": "0.2.0",
                }
            )

            tracer_provider = TracerProvider(resource=resource)
            exporter = OTLPSpanExporter(endpoint=self.config.telemetry.endpoint)
            tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(tracer_provider)

            logger.info(
                f"OpenTelemetry initialized: {self.config.telemetry.endpoint}"
            )
        except ImportError:
            logger.warning("OpenTelemetry packages not installed, tracing disabled")
        except Exception as e:
            logger.warning(f"Failed to initialize OpenTelemetry: {e}")

    async def _start_socket_server(self) -> None:
        """Start Unix socket server for CLI/debugging fallback.

        Only enabled when GAIUS_ALLOW_FALLBACKS=true environment variable is set.
        This is a debugging/development feature.
        """
        # Check feature flag - fallbacks disabled by default
        if os.environ.get("GAIUS_ALLOW_FALLBACKS", "").lower() != "true":
            logger.debug(
                "Unix socket fallback disabled (set GAIUS_ALLOW_FALLBACKS=true to enable)"
            )
            return

        # Remove stale socket file
        socket_path = Path(self._socket_path)
        if socket_path.exists():
            socket_path.unlink()

        self._socket_server = await asyncio.start_unix_server(
            self._handle_socket_client,
            path=self._socket_path,
        )
        logger.info(f"Unix socket server listening on {self._socket_path}")

    async def _stop_socket_server(self) -> None:
        """Stop Unix socket server and cleanup."""
        if self._socket_server:
            self._socket_server.close()
            await self._socket_server.wait_closed()

        # Remove socket file
        socket_path = Path(self._socket_path)
        if socket_path.exists():
            socket_path.unlink()

    async def _handle_socket_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a connected socket client."""
        peer = writer.get_extra_info("peername")
        logger.debug(f"Socket client connected: {peer}")

        try:
            while self._running:
                # Read length-prefixed message
                length_bytes = await reader.readexactly(4)
                length = int.from_bytes(length_bytes, "big")

                if length > 1024 * 1024:  # 1MB limit
                    logger.warning(f"Message too large: {length}")
                    break

                # Read message data
                data = await reader.readexactly(length)

                # Process request
                try:
                    request = deserialize_request(data)
                    logger.debug(
                        f"Socket request: {request.service.name}.{request.action}"
                    )

                    # Route to handler
                    handler = self._handlers.get(request.service)
                    if handler:
                        response = await handler(request)
                    else:
                        response = Response.failure(
                            request.id,
                            code=404,
                            message=f"Unknown service: {request.service.name}",
                        )

                    # Send response (length-prefixed)
                    response_data = serialize_response(response)
                    writer.write(len(response_data).to_bytes(4, "big"))
                    writer.write(response_data)
                    await writer.drain()

                except Exception as e:
                    logger.error(f"Socket request error: {e}")
                    # Try to send error response
                    try:
                        response = Response.failure(
                            request_id="unknown",
                            code=500,
                            message=str(e),
                        )
                        response_data = serialize_response(response)
                        writer.write(len(response_data).to_bytes(4, "big"))
                        writer.write(response_data)
                        await writer.drain()
                    except Exception:
                        pass

        except asyncio.IncompleteReadError:
            logger.debug(f"Socket client disconnected: {peer}")
        except Exception as e:
            logger.error(f"Socket client error: {e}")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    def _on_request(self, msg: AeronMessage) -> None:
        """Handle incoming request (callback from bridge)."""
        asyncio.create_task(self._process_request(msg))

    async def _process_request(self, msg: AeronMessage) -> None:
        """Process a single request and send response."""
        try:
            request = deserialize_request(msg.data)
            logger.debug(f"Received request: {request.service.name}.{request.action}")

            # Start OpenTelemetry span if available
            span = start_span_from_request(request)

            try:
                # Route to handler
                handler = self._handlers.get(request.service)
                if handler:
                    response = await handler(request)
                else:
                    response = Response.failure(
                        request.id,
                        code=404,
                        message=f"Unknown service: {request.service.name}",
                    )

            finally:
                if span:
                    span.__exit__(None, None, None)

            # Send response
            response_data = serialize_response(response)
            await self._bridge.publish(
                self.config.aeron.response_stream, response_data
            )

        except Exception as e:
            logger.exception(f"Error processing request: {e}")
            # Try to send error response
            try:
                response = Response.failure(
                    request_id=getattr(msg, "id", "unknown"),
                    code=500,
                    message=str(e),
                )
                await self._bridge.publish(
                    self.config.aeron.response_stream,
                    serialize_response(response),
                )
            except Exception:
                pass

    async def _request_loop(self) -> None:
        """Main loop for processing requests (using async iterator)."""
        # The _on_request callback handles requests via subscription
        # This loop is for any additional processing needed
        while self._running:
            await asyncio.sleep(0.1)

    async def _health_broadcast_loop(self) -> None:
        """Broadcast health metrics at configured interval."""
        interval = self.config.health_interval_ms / 1000.0

        while self._running:
            try:
                metrics = await self._collect_health_metrics()
                data = serialize_health_metrics(metrics)
                await self._bridge.publish(self.config.aeron.health_stream, data)
            except Exception as e:
                logger.debug(f"Health broadcast error: {e}")

            await asyncio.sleep(interval)

    async def _collect_health_metrics(self) -> HealthMetrics:
        """Collect current health metrics."""
        # Placeholder implementation - will be expanded in later phases
        return HealthMetrics.create(
            gpus=[],  # TODO: Collect from GPUOrchestrator
            endpoints=[],  # TODO: Collect from vLLM controller
            queue_depth=0,  # TODO: Collect from scheduler
            evolution_running=False,  # TODO: Collect from evolution daemon
            evolution_agent="",
        )

    async def broadcast_event(self, event: Event) -> None:
        """Broadcast an event to all subscribers."""
        if self._bridge:
            data = serialize_event(event)
            await self._bridge.publish(self.config.aeron.event_stream, data)

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
                endpoint = request.payload.get("endpoint", "")
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
                endpoint = request.payload.get("endpoint", "")
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
                endpoint = request.payload.get("endpoint", "")
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
                endpoint = request.payload.get("endpoint", "")
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
                endpoint = request.payload.get("endpoint", "")
                lines = request.payload.get("lines", 50)
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
                endpoints = request.payload.get("endpoints", ["reasoning"])
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
                # State reconciliation - compare desired vs actual and fix
                result = await self._orchestrator_service.reconcile_state()
                return Response.success(request.id, result)

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

            prompt = request.payload.get("prompt", "")
            agent = request.payload.get("agent", "fast")
            system_prompt = request.payload.get("system_prompt")
            temperature = request.payload.get("temperature", 0.7)
            max_tokens = request.payload.get("max_tokens", 2048)
            technique = request.payload.get("technique")

            try:
                response = await self._backend_router.complete(
                    prompt=prompt,
                    agent_alias=agent,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    technique=technique,
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
            prompt = request.payload.get("prompt", "")
            model = request.payload.get("model", "")
            return Response.success(
                request.id,
                {
                    "job_id": f"job-{request.id[:8]}",
                    "status": "queued",
                    "model": model,
                },
            )
        elif action == "get_result":
            job_id = request.payload.get("job_id", "")
            return Response.success(
                request.id,
                {
                    "job_id": job_id,
                    "status": "pending",
                    "result": None,
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
            agent_id = request.payload.get("agent_id", "")
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
            embeddings = request.payload.get("embeddings", [])
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
            embeddings = request.payload.get("embeddings", [])
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

            task_type = request.payload.get("task_type", "cognition_cycle")
            payload = request.payload.get("payload", {})

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
                config = CognitionConfig(
                    max_cycles_per_hour=self.config.cognition.max_cycles_per_hour
                    if hasattr(self.config, "cognition")
                    else 4,
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

            limit = request.payload.get("limit", 10)
            tasks = await self._cognition_service.get_pending_tasks(limit)
            return Response.success(request.id, {"tasks": tasks})

        elif action == "recent":
            if not self._cognition_service:
                return Response.success(request.id, {"tasks": []})

            limit = request.payload.get("limit", 10)
            tasks = await self._cognition_service.get_recent_completed(limit)
            return Response.success(request.id, {"tasks": tasks})

        elif action == "recent_thoughts":
            # Get recent thoughts from the cognition agent
            limit = request.payload.get("limit", 10)
            try:
                from ..agents.cognition import get_cognition_agent

                agent = get_cognition_agent()
                thoughts = await agent.get_active_thoughts(limit=limit)

                thought_list = []
                for t in thoughts:
                    thought_list.append({
                        "type": t.thought_type.value if hasattr(t.thought_type, "value") else str(t.thought_type),
                        "title": t.title,
                        "summary": t.summary or (t.content[:100] if t.content else ""),
                        "salience": t.salience,
                        "generation": t.generation,
                        "timestamp": t.created_at.isoformat() if t.created_at else None,
                        "note_path": t.note_path,
                    })

                return Response.success(request.id, {"thoughts": thought_list})

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

            if self._cognition_service:
                status = self._cognition_service.get_status()
                activity["cognition_running"] = status.get("running", False)
                activity["cycles_completed"] = status.get("cycles_completed", 0)
                activity["last_cycle_at"] = status.get("last_cycle_at")
                activity["current_task"] = (
                    status.get("current_task", {}).get("task_type")
                    if status.get("current_task")
                    else None
                )

            # Try to get thought count for today
            try:
                from ..agents.cognition import get_cognition_agent

                agent = get_cognition_agent()
                thoughts = await agent.get_active_thoughts(limit=100)
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

    # Create and run engine
    engine = GaiusEngine(config)

    try:
        asyncio.run(engine.run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
