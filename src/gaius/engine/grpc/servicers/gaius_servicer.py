"""Gaius custom service extensions servicer.

This module implements the GaiusService, which provides Gaius-specific
functionality beyond the standard KServe OIP:

- Orchestrator: GPU allocation, endpoint management
- Scheduler: Job submission, completion
- Evolution: Agent optimization daemon
- Grid: Embedding projection to 19x19 grid
- TDA: Topological data analysis
- Streaming: Health metrics and event streams
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, AsyncIterator, Optional

import grpc
from grpc import aio
from google.protobuf import empty_pb2

from ...generated import (
    # Orchestrator
    OrchestratorStatusResponse,
    GPUAllocation,
    EndpointInfo,
    StartEndpointRequest,
    StopEndpointRequest,
    RestartEndpointRequest,
    EndpointResponse,
    # Scheduler
    CompleteRequest,
    CompleteResponse,
    SubmitJobRequest,
    SubmitJobResponse,
    GetJobResultRequest,
    GetJobResultResponse,
    SchedulerStatusResponse,
    # Evolution
    EvolutionStatusResponse,
    TriggerEvolutionRequest,
    EvolutionCycleResponse,
    # Health
    HealthStreamRequest,
    HealthMetrics,
    GPUMetrics,
    EndpointHealth,
    # Events
    EventStreamRequest,
    Event,
    # Grid
    ProjectEmbeddingsRequest,
    GridPosition,
    ProjectEmbeddingsResponse,
    ProjectQueryRequest,
    ProjectQueryResponse,
    # TDA
    ComputeTDARequest,
    PersistenceInterval,
    TDAResponse,
    # Servicer base
    GaiusServiceServicer,
)

if TYPE_CHECKING:
    from ..server import ServiceRegistry

logger = logging.getLogger(__name__)


class GaiusServicer(GaiusServiceServicer):
    """Gaius custom extensions servicer.

    Implements the GaiusService gRPC interface for Gaius-specific operations
    like orchestrator management, evolution control, and streaming.
    """

    def __init__(self, services: "ServiceRegistry"):
        self._services = services
        self._event_subscribers: list[asyncio.Queue] = []

    # =========================================================================
    # Orchestrator
    # =========================================================================

    async def OrchestratorStatus(
        self,
        request: empty_pb2.Empty,
        context: aio.ServicerContext,
    ) -> OrchestratorStatusResponse:
        """Get orchestrator status including GPU allocations."""
        config = self._services.config
        router = self._services.backend_router

        response = OrchestratorStatusResponse(
            total_gpus=0,
            available_gpus=0,
        )

        if config:
            response.total_gpus = config.gpus.total
            response.available_gpus = config.gpus.total - len(config.gpus.reserved)

        if router:
            status = router.get_status()
            for name, backend in status.get("backends", {}).items():
                if backend.get("healthy", False):
                    endpoint = EndpointInfo(
                        name=name,
                        model=backend.get("model", ""),
                        status="running" if backend.get("healthy") else "stopped",
                        port=backend.get("port", 0),
                    )
                    response.endpoints.append(endpoint)

        return response

    async def StartEndpoint(
        self,
        request: StartEndpointRequest,
        context: aio.ServicerContext,
    ) -> EndpointResponse:
        """Start an inference endpoint."""
        endpoint_name = request.endpoint_name

        if not self._services.backend_router:
            return EndpointResponse(
                success=False,
                message="Backend router not initialized",
            )

        try:
            # TODO: Implement endpoint start via backend router
            return EndpointResponse(
                success=True,
                message=f"Endpoint '{endpoint_name}' start requested",
            )
        except Exception as e:
            return EndpointResponse(success=False, message=str(e))

    async def StopEndpoint(
        self,
        request: StopEndpointRequest,
        context: aio.ServicerContext,
    ) -> EndpointResponse:
        """Stop an inference endpoint."""
        endpoint_name = request.endpoint_name

        if not self._services.backend_router:
            return EndpointResponse(
                success=False,
                message="Backend router not initialized",
            )

        try:
            # TODO: Implement endpoint stop via backend router
            return EndpointResponse(
                success=True,
                message=f"Endpoint '{endpoint_name}' stop requested",
            )
        except Exception as e:
            return EndpointResponse(success=False, message=str(e))

    async def RestartEndpoint(
        self,
        request: RestartEndpointRequest,
        context: aio.ServicerContext,
    ) -> EndpointResponse:
        """Restart an inference endpoint."""
        endpoint_name = request.endpoint_name

        if not self._services.backend_router:
            return EndpointResponse(
                success=False,
                message="Backend router not initialized",
            )

        try:
            # TODO: Implement endpoint restart via backend router
            return EndpointResponse(
                success=True,
                message=f"Endpoint '{endpoint_name}' restart requested",
            )
        except Exception as e:
            return EndpointResponse(success=False, message=str(e))

    # =========================================================================
    # Scheduler
    # =========================================================================

    async def SchedulerStatus(
        self,
        request: empty_pb2.Empty,
        context: aio.ServicerContext,
    ) -> SchedulerStatusResponse:
        """Get scheduler status."""
        response = SchedulerStatusResponse(
            queue_depth=0,
            active_jobs=0,
            avg_latency_ms=0.0,
        )

        if self._services.backend_router:
            status = self._services.backend_router.get_status()
            response.queue_depth = status.get("queue_depth", 0)
            response.active_jobs = status.get("active_jobs", 0)
            response.avg_latency_ms = status.get("avg_latency_ms", 0.0)

        return response

    async def Complete(
        self,
        request: CompleteRequest,
        context: aio.ServicerContext,
    ) -> CompleteResponse:
        """Synchronous completion request."""
        if not self._services.backend_router:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Backend router not initialized")
            return CompleteResponse()

        start_time = time.time()

        try:
            result = await self._services.backend_router.complete(
                prompt=request.prompt,
                agent_alias=request.agent_alias or "fast",
                system_prompt=request.system_prompt,
                temperature=request.temperature or 0.7,
                max_tokens=request.max_tokens or 2048,
            )

            latency_ms = (time.time() - start_time) * 1000

            return CompleteResponse(
                text=result.content,
                tokens_used=result.output_tokens,
                latency_ms=latency_ms,
                model=result.model,
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return CompleteResponse()

    async def SubmitJob(
        self,
        request: SubmitJobRequest,
        context: aio.ServicerContext,
    ) -> SubmitJobResponse:
        """Submit an async job for processing."""
        import uuid

        job_id = f"job-{uuid.uuid4().hex[:8]}"

        # TODO: Implement job queue
        return SubmitJobResponse(
            job_id=job_id,
            status="queued",
        )

    async def GetJobResult(
        self,
        request: GetJobResultRequest,
        context: aio.ServicerContext,
    ) -> GetJobResultResponse:
        """Get the result of a submitted job."""
        job_id = request.job_id

        # TODO: Implement job result lookup
        return GetJobResultResponse(
            job_id=job_id,
            status="pending",
        )

    # =========================================================================
    # Evolution
    # =========================================================================

    async def EvolutionStatus(
        self,
        request: empty_pb2.Empty,
        context: aio.ServicerContext,
    ) -> EvolutionStatusResponse:
        """Get evolution daemon status."""
        if self._services.get_evolution_status:
            try:
                status = await self._services.get_evolution_status()
                return EvolutionStatusResponse(
                    running=status.get("running", False),
                    cycles_completed=status.get("cycles_completed", 0),
                    total_improvement_pct=status.get("total_improvement_pct", 0.0),
                    current_agent=status.get("current_agent", ""),
                    next_agent=status.get("next_agent", ""),
                    mode=status.get("mode", "idle"),
                )
            except Exception as e:
                logger.warning(f"Failed to get evolution status: {e}")

        # Default response when evolution not available
        return EvolutionStatusResponse(
            running=False,
            mode="unavailable",
        )

    async def TriggerEvolution(
        self,
        request: TriggerEvolutionRequest,
        context: aio.ServicerContext,
    ) -> EvolutionCycleResponse:
        """Trigger an evolution cycle for an agent."""
        agent_id = request.agent_id

        if self._services.trigger_evolution:
            try:
                result = await self._services.trigger_evolution(agent_id)
                return EvolutionCycleResponse(
                    success=result.get("success", False),
                    improvement_pct=result.get("improvement_pct", 0.0),
                    duration_ms=result.get("duration_ms", 0),
                    agent_id=result.get("agent_id", agent_id),
                    version_id=result.get("version_id", ""),
                )
            except Exception as e:
                return EvolutionCycleResponse(
                    success=False,
                    agent_id=agent_id,
                )

        context.set_code(grpc.StatusCode.UNAVAILABLE)
        context.set_details("Evolution service not available")
        return EvolutionCycleResponse(success=False)

    async def StartEvolution(
        self,
        request: empty_pb2.Empty,
        context: aio.ServicerContext,
    ) -> EvolutionStatusResponse:
        """Start the evolution daemon."""
        if self._services.start_evolution:
            try:
                status = await self._services.start_evolution()
                return EvolutionStatusResponse(
                    running=True,
                    mode="running",
                    next_agent=status.get("next_agent", ""),
                )
            except Exception as e:
                logger.warning(f"Failed to start evolution: {e}")

        context.set_code(grpc.StatusCode.UNAVAILABLE)
        context.set_details("Evolution service not available")
        return EvolutionStatusResponse(running=False)

    async def StopEvolution(
        self,
        request: empty_pb2.Empty,
        context: aio.ServicerContext,
    ) -> EvolutionStatusResponse:
        """Stop the evolution daemon."""
        if self._services.stop_evolution:
            try:
                await self._services.stop_evolution()
                return EvolutionStatusResponse(
                    running=False,
                    mode="stopped",
                )
            except Exception as e:
                logger.warning(f"Failed to stop evolution: {e}")

        return EvolutionStatusResponse(running=False, mode="stopped")

    # =========================================================================
    # Grid (Embedding Projection)
    # =========================================================================

    async def ProjectEmbeddings(
        self,
        request: ProjectEmbeddingsRequest,
        context: aio.ServicerContext,
    ) -> ProjectEmbeddingsResponse:
        """Project embeddings to a 19x19 grid."""
        # TODO: Implement via grid service
        return ProjectEmbeddingsResponse(
            num_clusters=0,
            grid_size=request.grid_size or 19,
        )

    async def ProjectQuery(
        self,
        request: ProjectQueryRequest,
        context: aio.ServicerContext,
    ) -> ProjectQueryResponse:
        """Project a query embedding to grid position."""
        # TODO: Implement via grid service
        return ProjectQueryResponse(x=9, y=9)

    # =========================================================================
    # TDA (Topological Data Analysis)
    # =========================================================================

    async def ComputeTDA(
        self,
        request: ComputeTDARequest,
        context: aio.ServicerContext,
    ) -> TDAResponse:
        """Compute topological features of embeddings."""
        # TODO: Implement via TDA service
        return TDAResponse(betti_numbers=[0, 0, 0])

    # =========================================================================
    # Streaming
    # =========================================================================

    async def HealthStream(
        self,
        request: HealthStreamRequest,
        context: aio.ServicerContext,
    ) -> AsyncIterator[HealthMetrics]:
        """Stream health metrics at regular intervals.

        Args:
            request: Contains interval_ms for update frequency

        Yields:
            HealthMetrics messages at the specified interval
        """
        interval_ms = request.interval_ms or 1000
        interval_sec = interval_ms / 1000.0

        logger.debug(f"Starting health stream with interval {interval_ms}ms")

        try:
            while not context.cancelled():
                metrics = await self._collect_health_metrics()
                yield metrics
                await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            logger.debug("Health stream cancelled")
        except Exception as e:
            logger.error(f"Health stream error: {e}")

    async def EventStream(
        self,
        request: EventStreamRequest,
        context: aio.ServicerContext,
    ) -> AsyncIterator[Event]:
        """Stream events to subscribers.

        Args:
            request: Contains optional event_types filter

        Yields:
            Event messages as they occur
        """
        event_types = set(request.event_types) if request.event_types else None

        # Create queue for this subscriber
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._event_subscribers.append(queue)

        logger.debug(f"Event stream started (filter: {event_types})")

        try:
            while not context.cancelled():
                try:
                    # Wait for events with timeout to check cancellation
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)

                    # Apply filter if specified
                    if event_types is None or event.event_type in event_types:
                        yield event
                except asyncio.TimeoutError:
                    # Check if still active
                    continue
        except asyncio.CancelledError:
            logger.debug("Event stream cancelled")
        finally:
            # Remove subscriber
            if queue in self._event_subscribers:
                self._event_subscribers.remove(queue)

    async def broadcast_event(self, event: Event) -> None:
        """Broadcast an event to all subscribers.

        Args:
            event: Event to broadcast
        """
        for queue in self._event_subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Event queue full, dropping event")

    async def _collect_health_metrics(self) -> HealthMetrics:
        """Collect current health metrics."""
        timestamp_ms = int(time.time() * 1000)

        metrics = HealthMetrics(
            timestamp_ms=timestamp_ms,
            queue_depth=0,
            evolution_running=False,
        )

        # Try to get metrics from callback
        if self._services.get_health_metrics:
            try:
                raw_metrics = await self._services.get_health_metrics()

                # GPU metrics
                for gpu in raw_metrics.get("gpus", []):
                    gpu_metric = GPUMetrics(
                        gpu_id=gpu.get("id", 0),
                        utilization=gpu.get("utilization", 0.0),
                        memory_used_gb=gpu.get("memory_used_gb", 0.0),
                        memory_total_gb=gpu.get("memory_total_gb", 0.0),
                        temperature_c=gpu.get("temperature_c", 0),
                        power_watts=gpu.get("power_watts", 0),
                    )
                    metrics.gpus.append(gpu_metric)

                # Endpoint health
                for ep in raw_metrics.get("endpoints", []):
                    endpoint = EndpointHealth(
                        name=ep.get("name", ""),
                        model=ep.get("model", ""),
                        healthy=ep.get("healthy", False),
                        requests_served=ep.get("requests_served", 0),
                        avg_latency_ms=ep.get("avg_latency_ms", 0.0),
                    )
                    metrics.endpoints.append(endpoint)

                metrics.queue_depth = raw_metrics.get("queue_depth", 0)
                metrics.evolution_running = raw_metrics.get("evolution_running", False)

            except Exception as e:
                logger.debug(f"Failed to collect health metrics: {e}")

        return metrics
