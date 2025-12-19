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
    CleanStartRequest,
    CleanStartResponse,
    EndpointResponse,
    # Scheduler
    CompleteRequest,
    CompleteResponse,
    SubmitJobRequest,
    SubmitJobResponse,
    GetJobResultRequest,
    GetJobResultResponse,
    SchedulerStatusResponse,
    # Swarm streaming
    SwarmStreamRequest,
    SwarmEvent,
    SwarmResult,
    # Workload Management
    BeginWorkloadRequest,
    BeginWorkloadResponse,
    CompleteWorkloadRequest,
    EndpointAllocationInfo,
    ActiveWorkloadInfo,
    GetActiveWorkloadsResponse,
    WorkloadType as ProtoWorkloadType,
    # Embeddings
    EmbedTextsRequest,
    EmbedTextsResponse,
    EmbeddingVector,
    # Evolution
    EvolutionStatusResponse,
    TriggerEvolutionRequest,
    EvolutionCycleResponse,
    # Cognition
    CognitionStatusResponse,
    ThoughtMessage,
    GetRecentThoughtsRequest,
    GetRecentThoughtsResponse,
    TriggerCognitionRequest,
    TriggerCognitionResponse,
    CognitionActivityResponse,
    # State Service (Thin Client Architecture)
    GetStateRequest,
    GridState,
    TDAFeatures as ProtoTDAFeatures,
    BoundingBox as ProtoBoundingBox,
    GeometryFeatures,
    GradientVector,
    SubscribeStateRequest,
    StateUpdate,
    GetPreferencesRequest,
    UIPreferences,
    SavePreferencesRequest,
    PruneSnapshotsRequest,
    PruneSnapshotsResponse,
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
    # Explain (Grid Position Interpretation)
    ExplainRequest,
    ExplainResponse,
    # Init streaming
    InitCommand,
    InitEvent,
    # Command Service (Unified Entry Point)
    ExecuteCommandRequest,
    ExecuteCommandResponse,
    # Init/Reindex (Heavy Compute)
    InitRequest,
    InitResponse,
    InitProgress,
    ReindexRequest,
    ReindexResponse,
    ReindexProgress,
    # Dataset Generation
    DatasetGenerationRequest,
    DatasetJobStatus,
    DatasetProgressEvent,
    GetDatasetJobRequest,
    CancelDatasetJobRequest,
    DatasetLineageRequest,
    DatasetLineageResponse,
    LineageNode,
    LineageEdge,
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
        orchestrator = self._services.orchestrator_service

        response = OrchestratorStatusResponse(
            total_gpus=0,
            available_gpus=0,
        )

        if config:
            response.total_gpus = config.gpus.total
            response.available_gpus = config.gpus.total - len(config.gpus.reserved)

        # Use OrchestratorService if available (preferred)
        if orchestrator:
            status = orchestrator.get_status()
            for alias, ep in status.get("endpoints", {}).items():
                endpoint = EndpointInfo(
                    name=alias,
                    model=ep.get("model", ""),
                    status=ep.get("status", "stopped"),
                    port=ep.get("port", 0),
                )
                response.endpoints.append(endpoint)
            return response

        # Fallback to backend router
        router = self._services.backend_router
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

    async def EnsureEndpoint(
        self,
        request: StartEndpointRequest,
        context: aio.ServicerContext,
    ):
        """Ensure endpoint is running (agent-first architecture).

        This is the primary method for agents to request endpoints.
        It checks resource availability and starts the endpoint if needed.
        """
        from ...generated import EnsureEndpointResponse

        endpoint_name = request.endpoint_name
        orchestrator = self._services.orchestrator_service

        if not orchestrator:
            return EnsureEndpointResponse(
                healthy=False,
                status="error",
                message="OrchestratorService not initialized",
            )

        try:
            status = await orchestrator.ensure_endpoint(endpoint_name)
            return EnsureEndpointResponse(
                healthy=status.status in ("healthy", "optillm"),
                status=status.status,
                port=status.port or 0,
                gpu_ids=list(status.gpu_ids) if status.gpu_ids else [],
                message=status.startup_message or "",
            )
        except ValueError as e:
            return EnsureEndpointResponse(
                healthy=False,
                status="error",
                message=str(e),
            )
        except Exception as e:
            logger.error(f"Failed to ensure endpoint {endpoint_name}: {e}")
            return EnsureEndpointResponse(
                healthy=False,
                status="error",
                message=str(e),
            )

    async def StartEndpoint(
        self,
        request: StartEndpointRequest,
        context: aio.ServicerContext,
    ) -> EndpointResponse:
        """Start an inference endpoint."""
        endpoint_name = request.endpoint_name
        orchestrator = self._services.orchestrator_service

        if not orchestrator:
            return EndpointResponse(
                success=False,
                message="OrchestratorService not initialized",
            )

        try:
            status = await orchestrator.start_endpoint(endpoint_name)
            return EndpointResponse(
                success=status.status in ("healthy", "starting", "optillm"),
                message=f"Endpoint '{endpoint_name}' started (status: {status.status})",
                endpoint_name=endpoint_name,
                port=status.port or 0,
            )
        except ValueError as e:
            return EndpointResponse(success=False, message=str(e))
        except Exception as e:
            logger.error(f"Failed to start endpoint {endpoint_name}: {e}")
            return EndpointResponse(success=False, message=str(e))

    async def StopEndpoint(
        self,
        request: StopEndpointRequest,
        context: aio.ServicerContext,
    ) -> EndpointResponse:
        """Stop an inference endpoint."""
        endpoint_name = request.endpoint_name
        orchestrator = self._services.orchestrator_service

        if not orchestrator:
            return EndpointResponse(
                success=False,
                message="OrchestratorService not initialized",
            )

        try:
            success = await orchestrator.stop_endpoint(endpoint_name)
            return EndpointResponse(
                success=success,
                message=f"Endpoint '{endpoint_name}' stopped" if success else f"Failed to stop '{endpoint_name}'",
                endpoint_name=endpoint_name,
            )
        except Exception as e:
            logger.error(f"Failed to stop endpoint {endpoint_name}: {e}")
            return EndpointResponse(success=False, message=str(e))

    async def RestartEndpoint(
        self,
        request: RestartEndpointRequest,
        context: aio.ServicerContext,
    ) -> EndpointResponse:
        """Restart an inference endpoint."""
        endpoint_name = request.endpoint_name
        orchestrator = self._services.orchestrator_service

        if not orchestrator:
            return EndpointResponse(
                success=False,
                message="OrchestratorService not initialized",
            )

        try:
            status = await orchestrator.restart_endpoint(endpoint_name)
            return EndpointResponse(
                success=status.status in ("healthy", "starting"),
                message=f"Endpoint '{endpoint_name}' restarted (status: {status.status})",
                endpoint_name=endpoint_name,
                port=status.port or 0,
            )
        except Exception as e:
            logger.error(f"Failed to restart endpoint {endpoint_name}: {e}")
            return EndpointResponse(success=False, message=str(e))

    async def CleanStart(
        self,
        request: CleanStartRequest,
        context: aio.ServicerContext,
    ) -> CleanStartResponse:
        """Kill stale processes and optionally start endpoints."""
        orchestrator = self._services.orchestrator_service

        if not orchestrator:
            return CleanStartResponse(
                success=False,
                message="OrchestratorService not initialized",
            )

        try:
            endpoints = list(request.endpoints) if request.endpoints else []
            result = await orchestrator.clean_start(endpoints)

            # Extract counts from result
            processes_killed = 0
            endpoints_started = 0
            if isinstance(result, dict):
                cleanup = result.get("cleanup", {})
                processes_killed = cleanup.get("processes_killed", 0)
                endpoints_started = len(result.get("started", []))

            return CleanStartResponse(
                success=True,
                message=f"Clean start completed: killed {processes_killed} processes, started {endpoints_started} endpoints",
                processes_killed=processes_killed,
                endpoints_started=endpoints_started,
            )
        except Exception as e:
            logger.error(f"Failed to clean start: {e}")
            return CleanStartResponse(success=False, message=str(e))

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
    # Workload Management (Yunikorn-Style)
    # =========================================================================

    async def BeginWorkload(
        self,
        request: BeginWorkloadRequest,
        context: aio.ServicerContext,
    ) -> BeginWorkloadResponse:
        """Begin a workload and allocate resources.

        Yunikorn-style workload management: the request declares what
        capabilities are needed and the orchestrator allocates endpoints,
        potentially evicting idle ones.
        """
        from ...workloads import WorkloadRequest, WorkloadType
        from ...services.scheduler_service import JobPriority
        from gaius.models.registry import TaskType

        orchestrator = self._services.orchestrator_service

        if not orchestrator:
            return BeginWorkloadResponse(
                success=False,
                workload_id=request.workload_id,
                error="OrchestratorService not initialized",
            )

        try:
            # Map proto workload type to Python enum
            workload_type_map = {
                ProtoWorkloadType.WORKLOAD_INIT: WorkloadType.INIT,
                ProtoWorkloadType.WORKLOAD_SWARM: WorkloadType.SWARM,
                ProtoWorkloadType.WORKLOAD_INFERENCE: WorkloadType.INFERENCE,
                ProtoWorkloadType.WORKLOAD_EMBEDDING: WorkloadType.EMBEDDING,
                ProtoWorkloadType.WORKLOAD_EVOLUTION: WorkloadType.EVOLUTION,
            }
            workload_type = workload_type_map.get(
                request.workload_type, WorkloadType.INFERENCE
            )

            # Map priority string to enum
            priority_map = {
                "critical": JobPriority.CRITICAL,
                "high": JobPriority.HIGH,
                "normal": JobPriority.NORMAL,
                "low": JobPriority.LOW,
            }
            priority = priority_map.get(
                request.priority.lower(), JobPriority.NORMAL
            )

            # Parse capabilities
            capabilities = []
            for cap_str in request.required_capabilities:
                try:
                    capabilities.append(TaskType(cap_str))
                except ValueError:
                    logger.warning(f"Unknown capability: {cap_str}")

            # Create workload request
            workload_req = WorkloadRequest(
                workload_id=request.workload_id,
                workload_type=workload_type,
                required_capabilities=capabilities,
                priority=priority,
                estimated_duration_s=request.estimated_duration_s or 300,
                estimated_memory_mb=request.estimated_memory_mb or 0,
                preemptible=request.preemptible,
            )

            # Begin workload
            result = await orchestrator.begin_workload(workload_req)

            # Build response
            response = BeginWorkloadResponse(
                success=result.success,
                workload_id=result.workload_id,
                error=result.error or "",
                wait_time_ms=result.wait_time_ms,
            )

            # Add allocated endpoints
            for task_type, alloc in result.allocated_endpoints.items():
                response.allocated_endpoints.append(
                    EndpointAllocationInfo(
                        endpoint_name=alloc.endpoint_name,
                        capability=task_type.value,
                        port=alloc.port,
                        healthy=alloc.healthy,
                        model_id=alloc.model_id,
                    )
                )

            # Add evicted and restore lists
            response.evicted_endpoints.extend(result.evicted_endpoints)
            response.restore_plan.extend(result.restore_plan)

            return response

        except Exception as e:
            logger.error(f"BeginWorkload failed: {e}")
            return BeginWorkloadResponse(
                success=False,
                workload_id=request.workload_id,
                error=str(e),
            )

    async def CompleteWorkload(
        self,
        request: CompleteWorkloadRequest,
        context: aio.ServicerContext,
    ) -> empty_pb2.Empty:
        """Mark a workload as complete and restore evicted endpoints."""
        orchestrator = self._services.orchestrator_service

        if orchestrator:
            try:
                await orchestrator.complete_workload(request.workload_id)
            except Exception as e:
                logger.error(f"CompleteWorkload failed: {e}")

        return empty_pb2.Empty()

    async def GetActiveWorkloads(
        self,
        request: empty_pb2.Empty,
        context: aio.ServicerContext,
    ) -> GetActiveWorkloadsResponse:
        """Get information about all active workloads."""
        orchestrator = self._services.orchestrator_service

        response = GetActiveWorkloadsResponse()

        if orchestrator:
            try:
                workloads = orchestrator.get_active_workloads()
                for wid, info in workloads.items():
                    response.workloads.append(
                        ActiveWorkloadInfo(
                            workload_id=wid,
                            workload_type=info.get("type", ""),
                            priority=info.get("priority", ""),
                            capabilities=info.get("capabilities", []),
                            elapsed_s=info.get("elapsed_s", 0.0),
                            estimated_duration_s=info.get("estimated_duration_s", 0),
                            is_overdue=info.get("is_overdue", False),
                            endpoints=info.get("endpoints", []),
                        )
                    )
            except Exception as e:
                logger.error(f"GetActiveWorkloads failed: {e}")

        return response

    # =========================================================================
    # Embeddings (Engine-Managed)
    # =========================================================================

    async def EmbedTexts(
        self,
        request: EmbedTextsRequest,
        context: aio.ServicerContext,
    ) -> EmbedTextsResponse:
        """Generate embeddings for texts using vLLM embedding endpoint.

        Routes embedding requests through the vLLM endpoint running with
        --task embed, using the OpenAI-compatible embeddings API.
        """
        import time
        import httpx

        texts = list(request.texts)
        start_time = time.time()

        try:
            # Get embedding endpoint from vLLM controller
            orchestrator = self._services.orchestrator_service
            if not orchestrator:
                context.set_code(grpc.StatusCode.UNAVAILABLE)
                context.set_details("OrchestratorService not initialized")
                return EmbedTextsResponse()

            proc = orchestrator._vllm.get_process("embedding")

            if not proc:
                context.set_code(grpc.StatusCode.UNAVAILABLE)
                context.set_details("Embedding endpoint not running. Start it with: /gpu start embedding")
                return EmbedTextsResponse()

            if proc.status.value != "healthy":
                context.set_code(grpc.StatusCode.UNAVAILABLE)
                context.set_details(f"Embedding endpoint not healthy: {proc.status.value}")
                return EmbedTextsResponse()

            # Call vLLM OpenAI-compatible embedding API
            base_url = f"http://localhost:{proc.port}/v1"
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{base_url}/embeddings",
                    json={
                        "input": texts,
                        "model": proc.model,
                    },
                )
                response.raise_for_status()
                data = response.json()

            # Extract embeddings from OpenAI format
            embeddings = []
            for item in data.get("data", []):
                embeddings.append(item.get("embedding", []))

            latency_ms = int((time.time() - start_time) * 1000)

            grpc_response = EmbedTextsResponse(
                model_used=proc.model,
                latency_ms=latency_ms,
            )

            for embedding in embeddings:
                grpc_response.embeddings.append(
                    EmbeddingVector(values=embedding)
                )

            return grpc_response

        except httpx.HTTPStatusError as e:
            logger.error(f"EmbedTexts HTTP error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Embedding API error: {e.response.text}")
            return EmbedTextsResponse()
        except Exception as e:
            logger.error(f"EmbedTexts failed: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return EmbedTextsResponse()

    # =========================================================================
    # Swarm Streaming
    # =========================================================================

    async def SwarmStream(
        self,
        request: SwarmStreamRequest,
        context: aio.ServicerContext,
    ) -> AsyncIterator[SwarmEvent]:
        """Streaming swarm analysis with real-time progress updates.

        Handles backend wait internally, streaming QUEUED/WAITING_FOR_BACKENDS
        status while endpoints initialize. This prevents client timeouts during
        the ~240s engine startup phase.

        Yields:
            SwarmEvent messages in order:
            1. QUEUED - Request received, waiting for backends
            2. WAITING_FOR_BACKENDS - Actively waiting (periodic updates)
            3. STARTED - Backends ready, swarm analysis beginning
            4. AGENT_STARTED/COMPLETED/FAILED - Per-agent progress
            5. COMPLETED - All agents done, includes final results
        """
        start_time = time.time()
        domain = request.domain or "general"
        context_str = request.context or ""
        roles = list(request.roles) if request.roles else None

        # Default swarm roles
        if roles is None:
            roles = ["Leader", "Risk", "Optimizer", "Planner", "Critic", "Executor", "Adversary"]

        total_agents = len(roles)

        def make_event(
            event_type: SwarmEvent.Type,
            agent: str = "",
            progress: float = 0.0,
            message: str = "",
            data: bytes = b"",
        ) -> SwarmEvent:
            return SwarmEvent(
                type=event_type,
                timestamp_ms=int(time.time() * 1000),
                agent=agent,
                progress=progress,
                message=message,
                data=data,
            )

        # Phase 1: QUEUED
        yield make_event(
            SwarmEvent.Type.QUEUED,
            message=f"Swarm request queued for domain: {domain}",
            progress=0.0,
        )

        # Phase 2: Wait for backends with streaming updates
        backends_ready = False
        wait_start = time.time()
        wait_interval = 2.0  # Update every 2 seconds

        while not backends_ready:
            # Check if any backends are available
            if self._services.backend_router:
                try:
                    status = self._services.backend_router.get_status()
                    vllm_status = status.get("vllm", {})
                    vllm_running = vllm_status.get("total_running", 0)
                    optillm_status = status.get("optillm", {})
                    optillm_healthy = optillm_status.get("healthy", False)
                    backends_ready = vllm_running > 0 or optillm_healthy
                except Exception:
                    pass

            if not backends_ready:
                elapsed = int(time.time() - wait_start)
                yield make_event(
                    SwarmEvent.Type.WAITING_FOR_BACKENDS,
                    message=f"Waiting for inference endpoints ({elapsed}s)...",
                    progress=0.05,  # Small progress to show activity
                )
                await asyncio.sleep(wait_interval)

                # Timeout after 5 minutes
                if elapsed > 300:
                    yield make_event(
                        SwarmEvent.Type.FAILED,
                        message="Timeout waiting for backends",
                        progress=0.0,
                    )
                    return

        # Phase 3: STARTED
        yield make_event(
            SwarmEvent.Type.STARTED,
            message=f"Swarm analysis starting with {total_agents} agents",
            progress=0.1,
        )

        # Phase 4: Run each agent
        results: dict[str, dict] = {}
        completed = 0
        failed = 0

        try:
            from ....agents.roles import AgentRole, get_role
        except ImportError:
            yield make_event(
                SwarmEvent.Type.FAILED,
                message="Agent roles not available",
            )
            return

        # Map role capabilities to endpoints
        ROLE_TO_ENDPOINT = {
            "Leader": "orchestrator",
            "Risk": "fast",
            "Optimizer": "fast",
            "Planner": "orchestrator",
            "Critic": "fast",
            "Executor": "fast",
            "Adversary": "fast",
        }

        for i, role_name in enumerate(roles):
            base_progress = 0.1 + (0.8 * i / total_agents)

            # AGENT_STARTED
            yield make_event(
                SwarmEvent.Type.AGENT_STARTED,
                agent=role_name,
                message=f"Running {role_name}...",
                progress=base_progress,
            )

            try:
                role_enum = AgentRole(role_name)
                role_def = get_role(role_enum)
                prompt = role_def.get_prompt(domain, context_str)
                endpoint = ROLE_TO_ENDPOINT.get(role_name, "fast")

                # Run the agent
                if self._services.backend_router:
                    result = await self._services.backend_router.complete(
                        prompt=prompt,
                        agent_alias=endpoint,
                        system_prompt=role_def.system_prompt or "",
                        temperature=role_def.temperature,
                        max_tokens=role_def.max_tokens,
                    )

                    agent_result = {
                        "status": "completed" if not result.error else "failed",
                        "content": result.content,
                        "model": result.model,
                        "endpoint": endpoint,
                        "latency_ms": result.latency_ms,
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                        "error": result.error,
                    }
                else:
                    agent_result = {
                        "status": "failed",
                        "error": "Backend router not available",
                    }

                results[role_name] = agent_result

                if agent_result["status"] == "completed":
                    completed += 1
                    yield make_event(
                        SwarmEvent.Type.AGENT_COMPLETED,
                        agent=role_name,
                        message=f"{role_name} completed",
                        progress=base_progress + (0.8 / total_agents),
                        data=json.dumps(agent_result).encode(),
                    )
                else:
                    failed += 1
                    yield make_event(
                        SwarmEvent.Type.AGENT_FAILED,
                        agent=role_name,
                        message=f"{role_name} failed: {agent_result.get('error', 'unknown')}",
                        progress=base_progress + (0.8 / total_agents),
                    )

            except Exception as e:
                failed += 1
                results[role_name] = {"status": "failed", "error": str(e)}
                yield make_event(
                    SwarmEvent.Type.AGENT_FAILED,
                    agent=role_name,
                    message=f"{role_name} failed: {e}",
                    progress=base_progress + (0.8 / total_agents),
                )

        # Phase 5: Save results and send COMPLETED
        total_duration_ms = int((time.time() - start_time) * 1000)

        # Save results to KB
        saved_path = ""
        try:
            from ....storage.kb_ops import save_swarm_results
            saved_path = save_swarm_results(results, domain)
        except Exception as e:
            logger.warning(f"Failed to save swarm results: {e}")

        # Send final COMPLETED event with all results
        final_data = {
            "results": results,
            "saved_path": saved_path,
            "total_agents": total_agents,
            "completed_agents": completed,
            "failed_agents": failed,
            "total_duration_ms": total_duration_ms,
        }

        yield make_event(
            SwarmEvent.Type.COMPLETED,
            message=f"Swarm completed: {completed}/{total_agents} agents succeeded",
            progress=1.0,
            data=json.dumps(final_data).encode(),
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
    # Cognition
    # =========================================================================

    async def CognitionStatus(
        self,
        request: empty_pb2.Empty,
        context: aio.ServicerContext,
    ) -> CognitionStatusResponse:
        """Get cognition daemon status."""
        # Try to get daemon status from service if available
        cognition = getattr(self._services, "cognition_service", None)

        if cognition:
            try:
                status = cognition.get_status()
                last_cycle_ms = 0
                if status.get("last_cycle_at"):
                    last_cycle_ms = int(status["last_cycle_at"].timestamp() * 1000)
                return CognitionStatusResponse(
                    running=status.get("running", False),
                    cycles_completed=status.get("cycles_completed", 0),
                    last_cycle_timestamp_ms=last_cycle_ms,
                    current_task=status.get("current_task") or "",
                )
            except Exception as e:
                logger.warning(f"Failed to get cognition status: {e}")

        # Fallback: check if we have thoughts (indicates cognition is working)
        return CognitionStatusResponse(running=False)

    async def GetRecentThoughts(
        self,
        request: GetRecentThoughtsRequest,
        context: aio.ServicerContext,
    ) -> GetRecentThoughtsResponse:
        """Get recent thoughts from the cognition agent."""
        from ....agents.cognition import get_cognition_agent

        limit = request.limit or 10
        response = GetRecentThoughtsResponse()

        try:
            agent = get_cognition_agent()
            thoughts = await agent.get_active_thoughts(limit=limit)

            for t in thoughts:
                timestamp_ms = 0
                if t.created_at:
                    timestamp_ms = int(t.created_at.timestamp() * 1000)

                thought = ThoughtMessage(
                    id=t.id or "",
                    thought_type=t.thought_type.value if hasattr(t.thought_type, "value") else str(t.thought_type),
                    title=t.title or "",
                    summary=t.summary or (t.content[:100] if t.content else ""),
                    salience=t.salience or 0.0,
                    generation=t.generation or 0,
                    timestamp_ms=timestamp_ms,
                    note_path=t.note_path or "",
                )
                response.thoughts.append(thought)

        except Exception as e:
            logger.debug(f"Failed to get recent thoughts: {e}")

        return response

    async def TriggerCognition(
        self,
        request: TriggerCognitionRequest,
        context: aio.ServicerContext,
    ) -> TriggerCognitionResponse:
        """Trigger a cognition cycle."""
        from ....agents.cognition import get_cognition_agent

        max_thoughts = request.max_thoughts or 5
        trigger_reason = request.trigger_reason or "manual"

        try:
            agent = get_cognition_agent()
            result = await agent.think(
                max_thoughts=max_thoughts,
                trigger_reason=trigger_reason,
            )

            return TriggerCognitionResponse(
                success=True,
                thoughts_generated=len(result.thoughts),
                patterns_detected=result.patterns_detected,
                connections_found=result.connections_found,
                curiosities_generated=result.curiosities_generated,
                duration_ms=result.duration_ms,
            )
        except Exception as e:
            logger.error(f"Cognition trigger failed: {e}")
            return TriggerCognitionResponse(
                success=False,
                error=str(e),
            )

    async def CognitionActivity(
        self,
        request: empty_pb2.Empty,
        context: aio.ServicerContext,
    ) -> CognitionActivityResponse:
        """Get comprehensive cognition activity summary."""
        from ....agents.cognition import get_cognition_agent

        response = CognitionActivityResponse(
            cognition_running=False,
            cycles_completed=0,
        )

        # Get daemon status if available (may be None during startup)
        cognition = getattr(self._services, "cognition_service", None)
        if cognition:
            try:
                status = cognition.get_status()
                response.cognition_running = status.get("running", False)
                response.cycles_completed = status.get("cycles_completed", 0)
                if status.get("last_cycle_at"):
                    response.last_cycle_timestamp_ms = int(status["last_cycle_at"].timestamp() * 1000)
                response.current_task = status.get("current_task") or ""
            except Exception as e:
                logger.debug(f"Failed to get cognition status: {e}")

        # Get active thoughts count from agent
        try:
            agent = get_cognition_agent()
            thoughts = await agent.get_active_thoughts(limit=100)
            response.active_thoughts = len(thoughts)
        except Exception as e:
            logger.debug(f"Failed to get active thoughts: {e}")

        return response

    # =========================================================================
    # State Service (Thin Client Architecture)
    # =========================================================================

    async def GetCurrentState(
        self,
        request: GetStateRequest,
        context: aio.ServicerContext,
    ) -> GridState:
        """Get current grid state for instant TUI startup.

        Loads state from Postgres current_state table, which is denormalized
        for fast reads. If since_generation > 0 and matches current generation,
        returns empty state (client is up to date).
        """
        kb_root = request.kb_root or "build/dev"
        since_generation = request.since_generation
        include_geometry = request.include_geometry

        try:
            from ....storage.grid_state import load_current_state_fast

            cached = await load_current_state_fast(kb_root)

            if cached is None:
                # No cached state - return empty
                return GridState(
                    snapshot_id="",
                    generation=0,
                    n_documents=0,
                )

            current_gen = cached.generation

            # If client is up to date, return minimal response
            if since_generation > 0 and since_generation >= current_gen:
                updated_ms = int(cached.updated_at.timestamp() * 1000) if cached.updated_at else 0
                return GridState(
                    snapshot_id=str(cached.snapshot_id) if cached.snapshot_id else "",
                    generation=current_gen,
                    updated_at_ms=updated_ms,
                    n_documents=0,  # Indicates "no new data"
                )

            # Build full response
            updated_ms = int(cached.updated_at.timestamp() * 1000) if cached.updated_at else 0
            response = GridState(
                snapshot_id=str(cached.snapshot_id) if cached.snapshot_id else "",
                generation=int(current_gen),
                updated_at_ms=int(updated_ms),
                n_documents=int(cached.n_documents),
                projection_method=cached.projection_method or "",
                embedding_model=cached.embedding_model or "",
            )

            # Add document positions (documents is list of dicts with x, y, path, title)
            for doc in cached.documents:
                response.documents.append(GridPosition(
                    id=doc.get("path", ""),
                    x=int(doc.get("x", 0)),
                    y=int(doc.get("y", 0)),
                    cluster=int(doc.get("cluster_id", -1)),
                ))

            # Add cluster centers (clusters is list of (x, y) tuples)
            for cluster in cached.clusters:
                if isinstance(cluster, (list, tuple)) and len(cluster) >= 2:
                    response.clusters.append(GridPosition(
                        x=int(float(cluster[0])),
                        y=int(float(cluster[1])),
                    ))

            # Add allocations (flattened 19x19)
            allocations = cached.allocations
            if allocations:
                # Flatten if nested, ensuring int type
                if allocations and isinstance(allocations[0], list):
                    flat = [int(v) for row in allocations for v in row]
                    response.allocations.extend(flat)
                else:
                    response.allocations.extend([int(v) for v in allocations])

            # Add TDA features directly from cached dataclass
            tda_features = ProtoTDAFeatures(
                entropy=float(cached.entropy),
                h0_count=int(cached.h0_count),
                h1_count=int(cached.h1_count),
                h2_count=int(cached.h2_count),
            )
            for cycle in cached.h1_cycles:
                tda_features.h1_cycles.append(ProtoBoundingBox(
                    x_min=int(cycle.get("x_min", 0)),
                    y_min=int(cycle.get("y_min", 0)),
                    x_max=int(cycle.get("x_max", 0)),
                    y_max=int(cycle.get("y_max", 0)),
                    persistence=float(cycle.get("persistence", 0.0)),
                ))
            for void in cached.h2_voids:
                tda_features.h2_voids.append(ProtoBoundingBox(
                    x_min=int(void.get("x_min", 0)),
                    y_min=int(void.get("y_min", 0)),
                    x_max=int(void.get("x_max", 0)),
                    y_max=int(void.get("y_max", 0)),
                    persistence=float(void.get("persistence", 0.0)),
                ))
            tda_features.risk_scores.extend([int(r) for r in cached.risk_scores])
            response.tda.CopyFrom(tda_features)

            # Add geometry if requested
            if include_geometry and (cached.curvature_map or cached.gradient_field):
                geo_features = GeometryFeatures()
                # curvature_map is already 361-element flat list
                if cached.curvature_map:
                    geo_features.curvature_map.extend(cached.curvature_map)
                # divergence_map is also 361-element flat list
                if cached.divergence_map:
                    geo_features.divergence_map.extend(cached.divergence_map)
                # gradient_field is list of [x, y, gx, gy] lists
                for gv in cached.gradient_field:
                    if isinstance(gv, (list, tuple)) and len(gv) >= 4:
                        # gv is [x, y, gx, gy] - x/y are grid positions (ints), gx/gy are gradient components (floats)
                        geo_features.gradient_field.append(GradientVector(
                            x=int(float(gv[0])),  # Convert float->int safely
                            y=int(float(gv[1])),
                            gx=float(gv[2]),
                            gy=float(gv[3]),
                        ))
                    elif isinstance(gv, dict):
                        # Legacy format support
                        geo_features.gradient_field.append(GradientVector(
                            x=gv.get("x", 0),
                            y=gv.get("y", 0),
                            gx=gv.get("gx", 0.0),
                            gy=gv.get("gy", 0.0),
                        ))
                response.geometry.CopyFrom(geo_features)

            return response

        except Exception as e:
            logger.error(f"GetCurrentState failed: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return GridState()

    async def SubscribeState(
        self,
        request: SubscribeStateRequest,
        context: aio.ServicerContext,
    ) -> AsyncIterator[StateUpdate]:
        """Subscribe to state updates (generation-based).

        Only pushes updates when generation increments (meaningful changes).
        Clients receive FULL_REFRESH on connect, then GENERATION_CHANGED
        when state updates.
        """
        kb_root = request.kb_root or "build/dev"
        client_id = request.client_id or context.peer() or "unknown"

        logger.debug(f"StateSubscription started: {client_id} -> {kb_root}")

        # Track current generation
        current_gen = 0

        try:
            from ....storage.grid_state import load_current_state_fast

            # Initial state
            cached = await load_current_state_fast(kb_root)
            if cached:
                current_gen = cached.generation

                # Send FULL_REFRESH on connect
                yield StateUpdate(
                    type=StateUpdate.Type.FULL_REFRESH,
                    generation=current_gen,
                    timestamp_ms=int(time.time() * 1000),
                    message="Connected, initial state loaded",
                )

            # Poll for changes (generation-based)
            poll_interval = 2.0  # Check every 2 seconds

            while not context.cancelled():
                await asyncio.sleep(poll_interval)

                # Check for new generation
                cached = await load_current_state_fast(kb_root)
                if cached:
                    new_gen = cached.generation
                    if new_gen > current_gen:
                        current_gen = new_gen
                        yield StateUpdate(
                            type=StateUpdate.Type.GENERATION_CHANGED,
                            generation=new_gen,
                            timestamp_ms=int(time.time() * 1000),
                            message=f"State updated to generation {new_gen}",
                        )

        except asyncio.CancelledError:
            logger.debug(f"StateSubscription cancelled: {client_id}")
        except Exception as e:
            logger.error(f"StateSubscription error: {e}")
            yield StateUpdate(
                type=StateUpdate.Type.ERROR,
                timestamp_ms=int(time.time() * 1000),
                message=str(e),
            )

    async def GetPreferences(
        self,
        request: GetPreferencesRequest,
        context: aio.ServicerContext,
    ) -> UIPreferences:
        """Get UI preferences for a client."""
        client_id = request.client_id

        try:
            from ....storage.grid_state import load_ui_preferences

            prefs = await load_ui_preferences(client_id)

            if prefs is None:
                # Return defaults
                return UIPreferences(
                    client_id=client_id,
                    cursor_x=9,
                    cursor_y=9,
                    view_mode="go",
                    overlay_mode="none",
                    iso_mode="curvature",
                    center_panel_mode="graph",
                    left_panel_visible=True,
                    right_panel_visible=True,
                )

            return UIPreferences(
                client_id=client_id,
                cursor_x=prefs.get("cursor_x", 9),
                cursor_y=prefs.get("cursor_y", 9),
                view_mode=prefs.get("view_mode", "go"),
                overlay_mode=prefs.get("overlay_mode", "none"),
                iso_mode=prefs.get("iso_mode", "curvature"),
                center_panel_mode=prefs.get("center_panel_mode", "graph"),
                left_panel_visible=prefs.get("left_panel_visible", True),
                right_panel_visible=prefs.get("right_panel_visible", True),
                domain=prefs.get("domain", ""),
                preferences_json=json.dumps(prefs.get("preferences_json", {})).encode(),
            )

        except Exception as e:
            logger.error(f"GetPreferences failed: {e}")
            return UIPreferences(client_id=client_id)

    async def SavePreferences(
        self,
        request: SavePreferencesRequest,
        context: aio.ServicerContext,
    ) -> empty_pb2.Empty:
        """Save UI preferences for a client."""
        prefs = request.preferences

        try:
            from ....storage.grid_state import save_ui_preferences

            await save_ui_preferences(
                client_id=prefs.client_id,
                cursor_x=prefs.cursor_x,
                cursor_y=prefs.cursor_y,
                view_mode=prefs.view_mode,
                overlay_mode=prefs.overlay_mode,
                iso_mode=prefs.iso_mode,
                center_panel_mode=prefs.center_panel_mode,
                left_panel_visible=prefs.left_panel_visible,
                right_panel_visible=prefs.right_panel_visible,
                domain=prefs.domain,
                preferences_json=json.loads(prefs.preferences_json) if prefs.preferences_json else {},
            )

        except Exception as e:
            logger.error(f"SavePreferences failed: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))

        return empty_pb2.Empty()

    async def PruneSnapshots(
        self,
        request: PruneSnapshotsRequest,
        context: aio.ServicerContext,
    ) -> PruneSnapshotsResponse:
        """Prune old grid snapshots."""
        kb_root = request.kb_root or "build/dev"
        keep_count = request.keep_count
        older_than_days = request.older_than_days
        dry_run = request.dry_run

        try:
            from ....storage.grid_state import prune_snapshots

            result = await prune_snapshots(
                kb_root=kb_root,
                keep_count=keep_count if keep_count > 0 else None,
                older_than_days=older_than_days if older_than_days > 0 else None,
                dry_run=dry_run,
            )

            return PruneSnapshotsResponse(
                deleted_count=result.get("deleted_count", 0),
                remaining_count=result.get("remaining_count", 0),
                dry_run=dry_run,
            )

        except Exception as e:
            logger.error(f"PruneSnapshots failed: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return PruneSnapshotsResponse(dry_run=dry_run)

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
    # Explain (Grid Position Interpretation)
    # =========================================================================

    async def Explain(
        self,
        request: ExplainRequest,
        context: aio.ServicerContext,
    ) -> ExplainResponse:
        """Explain a grid position using differential geometry and LLM.

        All heavy computation (TDA, geometry, minigrid) happens on the Engine.
        No fallbacks - Engine must be functional.

        Args:
            request: ExplainRequest with position and options

        Returns:
            ExplainResponse with geometry context and LLM interpretation
        """
        import numpy as np
        start_time = time.time()
        kb_root = request.kb_root or "build/dev"
        cx, cy = request.x, request.y
        max_tokens = request.max_tokens or 800

        # Convert to Go notation
        col = chr(ord("A") + cx + (1 if cx >= 8 else 0))  # Skip 'I'
        position = f"{col}{19 - cy}"

        logger.info(f"Explain: position={position} ({cx},{cy}) kb_root={kb_root}")

        try:
            from ....core.projection import get_grid_manager
            from ....core.tda import get_tda_manager
            from ....core.geometry import GeometryComputer
            from ....core.minigrids import get_embed_view, get_iso_view
            from ....inference.llm import explain_position, ExplanationContext
            from ....inference.client import InferenceClient
            from ....storage.grid_state import load_full_grid_data_for_minigrids

            # Get grid manager to check cache first
            grid_manager = get_grid_manager(kb_root=kb_root)

            # Check if cache is already populated
            grid_data = None
            if grid_manager._cached_data is not None and grid_manager._cached_data.n_documents > 0:
                grid_data = grid_manager._cached_data
                logger.info(f"Using cached grid data: {grid_data.n_documents} documents")
            else:
                # Try loading from Postgres (fast) before triggering slow UMAP
                logger.info("Grid cache empty, trying Postgres...")
                pg_grid_data = await load_full_grid_data_for_minigrids(kb_root)
                if pg_grid_data is not None and pg_grid_data.n_documents > 0:
                    grid_manager.set_cached_data(pg_grid_data)
                    grid_data = pg_grid_data
                    logger.info(f"Loaded {grid_data.n_documents} documents from Postgres")
                else:
                    # Last resort: compute fresh (slow UMAP projection)
                    logger.info("No Postgres cache, computing fresh projection...")
                    grid_data = grid_manager.get_grid_data()

            if grid_data is None or grid_data.n_documents == 0:
                return ExplainResponse(
                    success=False,
                    error="No documents indexed. Run /init first.",
                    position=position,
                    x=cx, y=cy,
                )

            # Get document at position
            document_title = ""
            document_path = ""
            point_idx = grid_data.grid_to_embedding.get((cx, cy))
            if point_idx is not None and point_idx < len(grid_data.points):
                point = grid_data.points[point_idx]
                document_title = point.title
                document_path = point.path

            # Get nearby documents
            nearby_documents = []
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < 19 and 0 <= ny < 19:
                        neighbor_idx = grid_data.grid_to_embedding.get((nx, ny))
                        if neighbor_idx is not None and neighbor_idx < len(grid_data.points):
                            nearby_documents.append(grid_data.points[neighbor_idx].title)

            # Compute geometry features (Ricci curvatures, gradients)
            curvature = 0.0
            gradient_x, gradient_y = 0.0, 0.0
            curvatures_list = None

            if grid_data.raw_embeddings is not None and len(grid_data.raw_embeddings) >= 15:
                gc = GeometryComputer(k_neighbors=min(15, len(grid_data.raw_embeddings) - 1))
                grid_coords = np.array([(p.x, p.y) for p in grid_data.points])
                geom_features = await gc.compute_features(grid_data.raw_embeddings, grid_coords)

                if geom_features is not None:
                    curvatures_list = [float(k) for k in geom_features.curvatures]
                    # Build curvature map
                    curvature_map = {}
                    for i, (px, py) in enumerate(grid_coords):
                        if i < len(curvatures_list):
                            curvature_map[(int(px), int(py))] = curvatures_list[i]
                    curvature = curvature_map.get((cx, cy), 0.0)

                    # Build gradient field
                    if hasattr(geom_features, 'gradient_field') and geom_features.gradient_field is not None:
                        for i, (px, py) in enumerate(grid_coords):
                            if i < len(geom_features.gradient_field):
                                if (int(px), int(py)) == (cx, cy):
                                    gradient_x, gradient_y = geom_features.gradient_field[i]
                                    break

            # Get TDA features
            tda_entropy = 0.0
            h0_count, h1_count, h2_count = 0, 0, 0
            risk_score = 0.0

            tda_manager = get_tda_manager()
            if grid_data.raw_embeddings is not None and len(grid_data.raw_embeddings) >= 3:
                grid_coords = np.array([(p.x, p.y) for p in grid_data.points])
                tda_features = tda_manager.compute_features(
                    grid_data.raw_embeddings, grid_coords
                )
                if tda_features:
                    tda_entropy = tda_features.entropy
                    # Use pre-computed counts from persistence intervals, not bounding box lists
                    h0_count = tda_features.h0_count
                    h1_count = tda_features.h1_count
                    h2_count = tda_features.h2_count
                    # risk_scores is a list indexed by point index, not grid coordinates
                    if hasattr(tda_features, 'risk_scores') and tda_features.risk_scores:
                        point_idx = grid_data.grid_to_embedding.get((cx, cy))
                        if point_idx is not None and point_idx < len(tda_features.risk_scores):
                            risk_score = tda_features.risk_scores[point_idx]

            # Compute mini-grid data
            embed_grid_flat = []
            iso_grid_flat = []

            embed_data = get_embed_view(grid_data, cx, cy)
            if embed_data and embed_data.grid:
                embed_grid_flat = [v for row in embed_data.grid for v in row]

            iso_data = get_iso_view(
                grid_data, curvatures_list, cx, cy,
                iso_features=grid_data.iso_features
            )
            if iso_data and iso_data.grid:
                iso_grid_flat = [v for row in iso_data.grid for v in row]

            # Build explanation context
            ctx = ExplanationContext(
                cursor_x=cx,
                cursor_y=cy,
                document_title=document_title,
                document_path=document_path,
                curvature=curvature,
                gradient_x=gradient_x,
                gradient_y=gradient_y,
                divergence=None,
                tda_entropy=tda_entropy,
                h0_count=h0_count,
                h1_count=h1_count,
                h2_count=h2_count,
                risk_score=risk_score,
                grid_coverage=len(grid_data.points) / 361,
                total_documents=len(grid_data.points),
                nearby_documents=nearby_documents[:5],
                embed_grid=embed_data.grid if embed_data else None,
                iso_grid=iso_data.grid if iso_data else None,
            )

            # Generate LLM explanation
            client = InferenceClient()
            await client._discover_vllm_model()
            explanation = await explain_position(ctx, client=client, max_tokens=max_tokens)

            # Strip thinking tags if present
            if '<think>' in explanation and '</think>' in explanation:
                explanation = explanation.split('</think>')[-1].strip()

            model_name = getattr(client, '_vllm_model', 'unknown')

            # Save to KB if requested
            saved_path = ""
            if request.save_to_kb:
                from ....core.kb_capture import ExplainCapture
                from pathlib import Path

                capture = ExplainCapture(
                    position=position,
                    x=cx,
                    y=cy,
                    document_title=document_title,
                    curvature=curvature,
                    gradient=(gradient_x, gradient_y),
                    tda_entropy=tda_entropy,
                    h0_count=h0_count,
                    h1_count=h1_count,
                    h2_count=h2_count,
                    risk_score=risk_score,
                    nearby_documents=nearby_documents[:5],
                    explanation=explanation,
                    model=model_name,
                )
                try:
                    saved_path = capture.save(Path(kb_root) / "scratch")
                except Exception as e:
                    logger.warning(f"Failed to save explanation: {e}")

            duration_ms = int((time.time() - start_time) * 1000)

            return ExplainResponse(
                success=True,
                position=position,
                x=cx,
                y=cy,
                document_title=document_title,
                document_path=document_path,
                curvature=curvature,
                gradient_x=gradient_x,
                gradient_y=gradient_y,
                divergence=0.0,
                tda_entropy=tda_entropy,
                h0_count=h0_count,
                h1_count=h1_count,
                h2_count=h2_count,
                risk_score=risk_score,
                grid_coverage=len(grid_data.points) / 361,
                total_documents=len(grid_data.points),
                nearby_documents=nearby_documents[:5],
                embed_grid=embed_grid_flat,
                iso_grid=iso_grid_flat,
                explanation=explanation,
                model=model_name,
                duration_ms=duration_ms,
                saved_path=saved_path,
            )

        except Exception as e:
            logger.error(f"Explain failed: {e}", exc_info=True)
            return ExplainResponse(
                success=False,
                error=str(e),
                position=position,
                x=cx, y=cy,
                duration_ms=int((time.time() - start_time) * 1000),
            )

    # =========================================================================
    # Dataset Generation
    # =========================================================================

    async def SubmitDatasetJob(
        self,
        request: DatasetGenerationRequest,
        context: aio.ServicerContext,
    ) -> DatasetJobStatus:
        """Submit a dataset generation job.

        Performs fail-fast checks before queueing. Errors include
        actionable /health fix suggestions.
        """
        dataset_service = self._services.dataset_service

        if not dataset_service:
            error_msg = (
                "DatasetService not initialized.\n"
                "  Try: /health fix dataset\n"
                "  Or:  process-compose process restart gaius-engine"
            )
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details(error_msg)
            return DatasetJobStatus(status="failed", error=error_msg)

        try:
            from ...services.dataset_service import DatasetJobConfig

            config = DatasetJobConfig(
                flow_name=request.flow_name or "TestFlow",
                steps=list(request.steps) if request.steps else ["start", "process", "end"],
                mode=request.mode or "som",
                dataset_id=request.dataset_id or "nifi-som-v1",
                variants_per_action=request.variants_per_action or 5,
                min_quality_score=request.min_quality_score or 0.6,
                enable_calibration=request.enable_calibration,  # Default False
                calibration_sample_rate=request.calibration_sample_rate or 0.1,
                export_calibration=request.export_calibration,
                storage_backend=request.storage_backend or "minio",
            )

            job = await dataset_service.submit_job(config)
            return self._job_to_status(job)

        except Exception as e:
            # Fail-fast: no fallbacks - include error message with hints
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details(str(e))
            return DatasetJobStatus(status="failed", error=str(e))

    async def GetDatasetJobStatus(
        self,
        request: GetDatasetJobRequest,
        context: aio.ServicerContext,
    ) -> DatasetJobStatus:
        """Get status of a dataset generation job."""
        dataset_service = self._services.dataset_service

        if not dataset_service:
            error_msg = (
                "DatasetService not initialized.\n"
                "  Try: /health fix dataset\n"
                "  Or:  process-compose process restart gaius-engine"
            )
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details(error_msg)
            return DatasetJobStatus()

        job = await dataset_service.get_job_status(request.job_id)
        if job is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Job not found: {request.job_id}")
            return DatasetJobStatus()

        return self._job_to_status(job)

    async def CancelDatasetJob(
        self,
        request: CancelDatasetJobRequest,
        context: aio.ServicerContext,
    ) -> DatasetJobStatus:
        """Cancel a dataset generation job."""
        dataset_service = self._services.dataset_service

        if not dataset_service:
            error_msg = (
                "DatasetService not initialized.\n"
                "  Try: /health fix dataset\n"
                "  Or:  process-compose process restart gaius-engine"
            )
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details(error_msg)
            return DatasetJobStatus()

        job = await dataset_service.cancel_job(request.job_id)
        if job is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Job not found: {request.job_id}")
            return DatasetJobStatus()

        return self._job_to_status(job)

    async def DatasetProgressStream(
        self,
        request: GetDatasetJobRequest,
        context: aio.ServicerContext,
    ) -> AsyncIterator[DatasetProgressEvent]:
        """Stream dataset generation progress."""
        dataset_service = self._services.dataset_service

        if not dataset_service:
            return

        try:
            async for event in dataset_service.subscribe_progress(request.job_id):
                yield DatasetProgressEvent(
                    type=event.type.value,
                    timestamp_ms=event.timestamp_ms,
                    job_id=event.job_id,
                    progress=event.progress,
                    message=event.message,
                    phase=event.phase,
                    example_id=event.example_id,
                    data=event.data,
                )
        except asyncio.CancelledError:
            logger.debug(f"Dataset progress stream cancelled for {request.job_id}")

    async def GetDatasetLineage(
        self,
        request: DatasetLineageRequest,
        context: aio.ServicerContext,
    ) -> DatasetLineageResponse:
        """Get lineage information for a dataset."""
        dataset_service = self._services.dataset_service

        if not dataset_service:
            error_msg = (
                "DatasetService not initialized.\n"
                "  Try: /health fix dataset\n"
                "  Or:  process-compose process restart gaius-engine"
            )
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details(error_msg)
            return DatasetLineageResponse()

        lineage = await dataset_service.get_lineage(request.dataset_id)

        return DatasetLineageResponse(
            dataset_id=lineage["dataset_id"],
            total_examples=lineage["total_examples"],
            nodes=[
                LineageNode(
                    id=n["id"],
                    type=n["type"],
                    namespace=n["namespace"],
                    name=n["name"],
                    properties=n.get("properties", b"{}"),
                )
                for n in lineage.get("nodes", [])
            ],
            edges=[
                LineageEdge(
                    type=e["type"],
                    from_id=e["from_id"],
                    to_id=e["to_id"],
                )
                for e in lineage.get("edges", [])
            ],
        )

    def _job_to_status(self, job) -> DatasetJobStatus:
        """Convert DatasetJob to proto DatasetJobStatus."""
        return DatasetJobStatus(
            job_id=job.id,
            status=job.status.value,
            total_examples=job.examples_total,
            completed_examples=job.examples_completed,
            accepted_examples=job.examples_accepted,
            rejected_examples=job.examples_rejected,
            progress=job.progress,
            current_phase=job.current_phase.value,
            error=job.error or "",
        )

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

    # ─────────────────────────────────────────────────────────────────────────
    # Init Stream (Bidirectional)
    # ─────────────────────────────────────────────────────────────────────────

    async def InitStream(
        self,
        request_iterator: AsyncIterator[InitCommand],
        context: aio.ServicerContext,
    ) -> AsyncIterator[InitEvent]:
        """Bidirectional initialization stream.

        Allows TUI/MCP clients to connect immediately during engine startup
        and receive real-time progress updates while also sending control
        commands (pause, cancel, health checks).

        This method is available as soon as gRPC starts, BEFORE backends
        and orchestrator are initialized, enabling progress monitoring
        during the ~240s vLLM preload phase.

        Args:
            request_iterator: Stream of InitCommand messages from client
            context: gRPC context

        Yields:
            InitEvent messages (progress, status, command responses)
        """
        # Get init controller from services
        init_controller = self._services.init_controller

        if not init_controller:
            # If init_controller is not set, return an error event and close
            yield InitEvent(
                type=InitEvent.Type.ERROR,
                timestamp_ms=int(time.time() * 1000),
                message="InitController not available",
            )
            return

        # Subscribe to init events
        event_queue = init_controller.subscribe()
        client_id = context.peer() or "unknown"

        logger.debug(f"InitStream started for client: {client_id}")

        # Create task to process incoming commands
        async def handle_commands():
            """Process incoming commands from client."""
            try:
                async for cmd in request_iterator:
                    logger.debug(f"InitStream command: {cmd.type} from {client_id}")
                    response = await init_controller.handle_command(cmd)
                    # Put response in queue so it gets yielded
                    try:
                        event_queue.put_nowait(response)
                    except asyncio.QueueFull:
                        logger.warning("Init event queue full, dropping command response")
            except asyncio.CancelledError:
                logger.debug(f"InitStream command handler cancelled for {client_id}")
            except Exception as e:
                logger.debug(f"InitStream command handler error: {e}")

        # Start command handler task
        command_task = asyncio.create_task(handle_commands())

        try:
            # Send initial status
            yield InitEvent(
                type=InitEvent.Type.PROGRESS,
                timestamp_ms=int(time.time() * 1000),
                phase=init_controller.state.phase.name.lower(),
                progress=init_controller.state.overall_progress,
                message=f"Connected. Phase: {init_controller.state.phase.name}",
            )

            # Stream events to client
            while not context.cancelled():
                try:
                    # Wait for events with timeout to check cancellation
                    event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                    yield event

                    # If we received READY event, client can decide to close
                    if event.type == InitEvent.Type.READY:
                        logger.debug(f"InitStream: READY event sent to {client_id}")

                except asyncio.TimeoutError:
                    # No events, check if still connected
                    continue

        except asyncio.CancelledError:
            logger.debug(f"InitStream cancelled for {client_id}")
        except Exception as e:
            logger.error(f"InitStream error for {client_id}: {e}")
            yield InitEvent(
                type=InitEvent.Type.ERROR,
                timestamp_ms=int(time.time() * 1000),
                message=str(e),
            )
        finally:
            # Cleanup
            command_task.cancel()
            try:
                await command_task
            except asyncio.CancelledError:
                pass
            init_controller.unsubscribe(event_queue)
            logger.debug(f"InitStream closed for {client_id}")

    # =========================================================================
    # Command Service (Unified Entry Point)
    # =========================================================================

    async def ExecuteCommand(
        self, request: ExecuteCommandRequest, context: grpc.aio.ServicerContext
    ) -> ExecuteCommandResponse:
        """Execute a command and return the result.

        Routes commands to appropriate handlers. For heavy compute commands,
        runs them through the Engine. For state-only commands, accesses Postgres.
        """
        start_time = time.time()
        command = request.command
        args = request.args
        kb_root = request.kb_root or "build/dev"
        client_id = request.client_id or "grpc"

        logger.info(f"ExecuteCommand: {command} args={args} from {client_id}")

        try:
            result = {}
            message = ""
            generation = 0

            # Route to appropriate handler
            if command == "reindex":
                # Delegate to Reindex RPC
                reindex_req = ReindexRequest(
                    kb_root=kb_root,
                    client_id=client_id,
                    force="force" in args.lower() if args else False,
                )
                reindex_resp = await self.Reindex(reindex_req, context)
                result = {
                    "documents_indexed": reindex_resp.documents_indexed,
                    "documents_skipped": reindex_resp.documents_skipped,
                    "duration_ms": reindex_resp.duration_ms,
                }
                message = reindex_resp.message
                generation = reindex_resp.generation

            elif command == "state":
                # Get current state
                from ....storage.grid_state import load_current_state_fast, get_current_generation
                state = await load_current_state_fast(kb_root)
                generation = await get_current_generation(kb_root)
                if state:
                    result = {
                        "snapshot_id": state.snapshot_id,
                        "n_documents": state.n_documents,
                        "h0_count": state.h0_count,
                        "h1_count": state.h1_count,
                        "entropy": state.entropy,
                    }
                    message = f"State loaded (gen {generation})"
                else:
                    message = "No state available"

            elif command == "generation":
                # Get current generation
                from ....storage.grid_state import get_current_generation
                generation = await get_current_generation(kb_root)
                result = {"generation": generation}
                message = f"Generation: {generation}"

            elif command == "prefs":
                # Get/save preferences
                from ....storage.grid_state import load_ui_preferences, save_ui_preferences, UIPreferences
                if "save" in args.lower() if args else False:
                    # Parse context for preferences
                    ctx = dict(request.context)
                    prefs = UIPreferences(
                        client_id=client_id,
                        cursor_x=int(ctx.get("cursor_x", 9)),
                        cursor_y=int(ctx.get("cursor_y", 9)),
                        view_mode=ctx.get("view_mode", "go"),
                        overlay_mode=ctx.get("overlay_mode", "none"),
                    )
                    await save_ui_preferences(prefs)
                    result = {"action": "saved"}
                    message = "Preferences saved"
                else:
                    prefs = await load_ui_preferences(client_id)
                    if prefs:
                        result = {
                            "cursor_x": prefs.cursor_x,
                            "cursor_y": prefs.cursor_y,
                            "view_mode": prefs.view_mode,
                            "overlay_mode": prefs.overlay_mode,
                        }
                        message = "Preferences loaded"
                    else:
                        message = "No preferences found"

            else:
                # Unknown command
                return ExecuteCommandResponse(
                    success=False,
                    command=command,
                    message=f"Unknown command: {command}",
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            duration_ms = int((time.time() - start_time) * 1000)
            return ExecuteCommandResponse(
                success=True,
                command=command,
                message=message,
                result_json=json.dumps(result).encode("utf-8"),
                generation=generation,
                duration_ms=duration_ms,
            )

        except Exception as e:
            logger.exception(f"ExecuteCommand failed: {e}")
            return ExecuteCommandResponse(
                success=False,
                command=command,
                message=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
            )

    async def Reindex(
        self, request: ReindexRequest, context: grpc.aio.ServicerContext
    ) -> ReindexResponse:
        """Reindex KB documents to Qdrant and compute grid projection.

        This is the main heavy compute operation - runs embedding, projection,
        and TDA computation on the Engine.
        """
        start_time = time.time()
        kb_root = request.kb_root or "build/dev"
        client_id = request.client_id or "grpc"

        logger.info(f"Reindex: kb_root={kb_root} force={request.force} from {client_id}")

        try:
            from ....core.projection import get_grid_manager
            from ....core.tda import get_tda_manager, TDAFeatures as CoreTDAFeatures
            from ....core.geometry import GeometryComputer
            from ....storage.grid_state import save_grid_state, get_current_generation
            import numpy as np

            # Get managers (lazily initialized, kb_root passed at first call)
            grid_manager = get_grid_manager(kb_root=kb_root)
            tda_manager = get_tda_manager()

            # Run the reindex pipeline
            # 1. Reindex KB to Qdrant and project to grid
            grid_data = await asyncio.get_event_loop().run_in_executor(
                None,
                grid_manager.reindex_and_project
            )

            if not grid_data or grid_data.n_documents == 0:
                return ReindexResponse(
                    success=False,
                    message="Reindex failed: no documents found",
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            # 2. Compute TDA features from raw embeddings
            tda_features = CoreTDAFeatures()
            geometry_features = None
            grid_coords = None

            if grid_data.raw_embeddings is not None and len(grid_data.raw_embeddings) > 0:
                # Build grid_coords array from embedding_to_grid mapping
                grid_coords = np.array([
                    grid_data.embedding_to_grid.get(i, (9, 9))
                    for i in range(len(grid_data.raw_embeddings))
                ])
                tda_features = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: tda_manager.compute_features(
                        grid_data.raw_embeddings,
                        grid_coords,
                        force_refresh=True
                    )
                )

                # 3. Compute geometry features (curvature, gradients, divergence)
                try:
                    k_neighbors = min(15, len(grid_data.raw_embeddings) - 1)
                    if k_neighbors >= 2:  # Need at least 2 neighbors
                        gc = GeometryComputer(k_neighbors=k_neighbors)
                        geometry_features = await gc.compute_features(
                            grid_data.raw_embeddings, grid_coords
                        )
                        logger.info(f"Computed geometry features for {len(grid_data.raw_embeddings)} points")
                except Exception as geom_err:
                    logger.warning(f"Geometry computation failed (non-fatal): {geom_err}")
                    geometry_features = None

            # 4. Save to Postgres (updates current_state table)
            embedding_model = request.embedding_model or "nomic-ai/colnomic-embed-multimodal-7b"
            snapshot_id = await save_grid_state(
                kb_root=kb_root,
                grid_data=grid_data,
                tda_features=tda_features,
                embedding_model=embedding_model,
                projection_method=grid_data.method,
                embedding_type="multi",  # ColNomic multi-vector
                geometry_features=geometry_features,
            )

            # Get new generation
            generation = await get_current_generation(kb_root)

            duration_ms = int((time.time() - start_time) * 1000)
            return ReindexResponse(
                success=True,
                message=f"Indexed {grid_data.n_documents} documents",
                documents_indexed=grid_data.n_documents,
                documents_skipped=0,
                generation=generation,
                duration_ms=duration_ms,
            )

        except Exception as e:
            logger.exception(f"Reindex failed: {e}")
            return ReindexResponse(
                success=False,
                message=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
            )

    async def ReindexStream(
        self, request: ReindexRequest, context: grpc.aio.ServicerContext
    ) -> AsyncIterator[ReindexProgress]:
        """Streaming reindex with progress updates.

        Yields progress events during the reindex pipeline.
        """
        kb_root = request.kb_root or "build/dev"
        client_id = request.client_id or "grpc"

        logger.info(f"ReindexStream: kb_root={kb_root} from {client_id}")

        try:
            # Started
            yield ReindexProgress(
                phase=ReindexProgress.Phase.STARTED,
                progress=0.0,
                message="Starting reindex...",
            )

            # Scanning
            yield ReindexProgress(
                phase=ReindexProgress.Phase.SCANNING,
                progress=0.1,
                message="Scanning documents...",
            )

            from ....core.projection import get_grid_manager
            from ....core.tda import get_tda_manager, TDAFeatures as CoreTDAFeatures
            from ....core.geometry import GeometryComputer
            from ....storage.grid_state import save_grid_state, get_current_generation
            import numpy as np

            grid_manager = get_grid_manager(kb_root=kb_root)
            tda_manager = get_tda_manager()

            # Embedding phase
            yield ReindexProgress(
                phase=ReindexProgress.Phase.EMBEDDING,
                progress=0.2,
                message="Computing embeddings...",
            )

            # Run reindex (this does embedding + projection)
            grid_data = await asyncio.get_event_loop().run_in_executor(
                None,
                grid_manager.reindex_and_project
            )

            if not grid_data or grid_data.n_documents == 0:
                yield ReindexProgress(
                    phase=ReindexProgress.Phase.ERROR,
                    progress=0.0,
                    message="No documents found",
                )
                return

            # Projecting
            yield ReindexProgress(
                phase=ReindexProgress.Phase.PROJECTING,
                progress=0.6,
                message=f"Projected {grid_data.n_documents} documents to grid",
                documents_processed=grid_data.n_documents,
                documents_total=grid_data.n_documents,
            )

            # TDA
            yield ReindexProgress(
                phase=ReindexProgress.Phase.TDA,
                progress=0.8,
                message="Computing TDA features...",
            )

            tda_features = CoreTDAFeatures()
            geometry_features = None
            grid_coords = None

            if grid_data.raw_embeddings is not None and len(grid_data.raw_embeddings) > 0:
                grid_coords = np.array([
                    grid_data.embedding_to_grid.get(i, (9, 9))
                    for i in range(len(grid_data.raw_embeddings))
                ])
                tda_features = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: tda_manager.compute_features(
                        grid_data.raw_embeddings,
                        grid_coords,
                        force_refresh=True
                    )
                )

                # Compute geometry features
                try:
                    k_neighbors = min(15, len(grid_data.raw_embeddings) - 1)
                    if k_neighbors >= 2:
                        gc = GeometryComputer(k_neighbors=k_neighbors)
                        geometry_features = await gc.compute_features(
                            grid_data.raw_embeddings, grid_coords
                        )
                        logger.info(f"Computed geometry features for {len(grid_data.raw_embeddings)} points")
                except Exception as geom_err:
                    logger.warning(f"Geometry computation failed (non-fatal): {geom_err}")
                    geometry_features = None

            # Saving
            yield ReindexProgress(
                phase=ReindexProgress.Phase.SAVING,
                progress=0.9,
                message="Saving state...",
            )

            embedding_model = request.embedding_model or "nomic-ai/colnomic-embed-multimodal-7b"
            await save_grid_state(
                kb_root=kb_root,
                grid_data=grid_data,
                tda_features=tda_features,
                embedding_model=embedding_model,
                projection_method=grid_data.method,
                embedding_type="multi",
                geometry_features=geometry_features,
            )

            generation = await get_current_generation(kb_root)

            # Complete
            yield ReindexProgress(
                phase=ReindexProgress.Phase.COMPLETE,
                progress=1.0,
                message=f"Indexed {grid_data.n_documents} documents (gen {generation})",
                documents_processed=grid_data.n_documents,
                documents_total=grid_data.n_documents,
            )

        except Exception as e:
            logger.exception(f"ReindexStream failed: {e}")
            yield ReindexProgress(
                phase=ReindexProgress.Phase.ERROR,
                progress=0.0,
                message=str(e),
            )

    # =========================================================================
    # Init (Full Initialization Pipeline)
    # =========================================================================

    async def Init(
        self, request: InitRequest, context: grpc.aio.ServicerContext
    ) -> InitResponse:
        """Full initialization pipeline: index KB, project to grid, compute TDA.

        This is the primary entry point for initializing a fresh Gaius instance
        or forcing a complete rebuild of the KB index and grid projection.

        Pipeline:
        1. Scan KB for documents
        2. Compute ColNomic embeddings
        3. Project to 19x19 grid via UMAP
        4. Compute TDA features (H0/H1/H2)
        5. Save to Postgres (grid_snapshots + current_state)
        """
        start_time = time.time()
        kb_root = request.kb_root or "build/dev"
        client_id = request.client_id or "grpc"
        force = request.force
        embedding_model = request.embedding_model or "nomic-ai/colnomic-embed-multimodal-7b"
        projection_method = request.projection_method or "umap"

        logger.info(f"Init: kb_root={kb_root} force={force} from {client_id}")

        try:
            from ....core.projection import get_grid_manager
            from ....core.tda import get_tda_manager, TDAFeatures as CoreTDAFeatures
            from ....core.geometry import GeometryComputer
            from ....storage.grid_state import (
                save_grid_state,
                get_current_generation,
                check_state_exists,
            )
            import numpy as np

            # Check if state already exists (skip if not forcing)
            if not force:
                state_exists = await check_state_exists(
                    kb_root, embedding_model, projection_method
                )
                if state_exists:
                    generation = await get_current_generation(kb_root)
                    return InitResponse(
                        success=True,
                        message="State already exists (use force=true to rebuild)",
                        generation=generation,
                        duration_ms=int((time.time() - start_time) * 1000),
                    )

            # Get managers
            grid_manager = get_grid_manager(method=projection_method, kb_root=kb_root)
            tda_manager = get_tda_manager()

            # Run the full pipeline
            # 1. Reindex KB to Qdrant and project to grid
            grid_data = await asyncio.get_event_loop().run_in_executor(
                None,
                grid_manager.reindex_and_project
            )

            if not grid_data or grid_data.n_documents == 0:
                return InitResponse(
                    success=False,
                    message="No documents found in KB",
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            # 2. Compute TDA features from raw embeddings
            tda_features = CoreTDAFeatures()
            geometry_features = None
            grid_coords = None

            if grid_data.raw_embeddings is not None and len(grid_data.raw_embeddings) > 0:
                grid_coords = np.array([
                    grid_data.embedding_to_grid.get(i, (9, 9))
                    for i in range(len(grid_data.raw_embeddings))
                ])
                tda_features = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: tda_manager.compute_features(
                        grid_data.raw_embeddings,
                        grid_coords,
                        force_refresh=True
                    )
                )

                # 3. Compute geometry features (curvature, gradients, divergence)
                try:
                    k_neighbors = min(15, len(grid_data.raw_embeddings) - 1)
                    if k_neighbors >= 2:
                        gc = GeometryComputer(k_neighbors=k_neighbors)
                        geometry_features = await gc.compute_features(
                            grid_data.raw_embeddings, grid_coords
                        )
                        logger.info(f"Computed geometry features for {len(grid_data.raw_embeddings)} points")
                except Exception as geom_err:
                    logger.warning(f"Geometry computation failed (non-fatal): {geom_err}")
                    geometry_features = None

            # 4. Save to Postgres
            snapshot_id = await save_grid_state(
                kb_root=kb_root,
                grid_data=grid_data,
                tda_features=tda_features,
                embedding_model=embedding_model,
                projection_method=projection_method,
                embedding_type="multi",
                geometry_features=geometry_features,
            )

            # Get new generation
            generation = await get_current_generation(kb_root)

            duration_ms = int((time.time() - start_time) * 1000)
            return InitResponse(
                success=True,
                message=f"Initialized {grid_data.n_documents} documents",
                documents_indexed=grid_data.n_documents,
                h0_count=tda_features.h0_count,
                h1_count=tda_features.h1_count,
                h2_count=tda_features.h2_count,
                entropy=tda_features.entropy,
                generation=generation,
                duration_ms=duration_ms,
            )

        except Exception as e:
            logger.exception(f"Init failed: {e}")
            return InitResponse(
                success=False,
                message=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
            )

    async def InitProgressStream(
        self, request: InitRequest, context: grpc.aio.ServicerContext
    ) -> AsyncIterator[InitProgress]:
        """Streaming init with detailed progress updates.

        Yields progress events for each phase of the init pipeline,
        allowing TUI/CLI to show real-time progress during long operations.
        """
        kb_root = request.kb_root or "build/dev"
        client_id = request.client_id or "grpc"
        force = request.force
        embedding_model = request.embedding_model or "nomic-ai/colnomic-embed-multimodal-7b"
        projection_method = request.projection_method or "umap"

        logger.info(f"InitProgressStream: kb_root={kb_root} from {client_id}")

        try:
            # STARTED
            yield InitProgress(
                phase=InitProgress.Phase.STARTED,
                progress=0.0,
                message="Starting initialization...",
            )

            from ....core.projection import get_grid_manager
            from ....core.tda import get_tda_manager, TDAFeatures as CoreTDAFeatures
            from ....core.geometry import GeometryComputer
            from ....storage.grid_state import (
                save_grid_state,
                get_current_generation,
                check_state_exists,
            )
            import numpy as np

            # Check if state already exists (skip if not forcing)
            if not force:
                state_exists = await check_state_exists(
                    kb_root, embedding_model, projection_method
                )
                if state_exists:
                    generation = await get_current_generation(kb_root)
                    yield InitProgress(
                        phase=InitProgress.Phase.COMPLETE,
                        progress=1.0,
                        message=f"State already exists (gen {generation})",
                    )
                    return

            # SCANNING
            yield InitProgress(
                phase=InitProgress.Phase.SCANNING,
                progress=0.1,
                message="Scanning KB for documents...",
            )

            grid_manager = get_grid_manager(method=projection_method, kb_root=kb_root)
            tda_manager = get_tda_manager()

            # EMBEDDING
            yield InitProgress(
                phase=InitProgress.Phase.EMBEDDING,
                progress=0.2,
                message="Computing ColNomic embeddings...",
            )

            # Run reindex (embedding + projection in one call)
            grid_data = await asyncio.get_event_loop().run_in_executor(
                None,
                grid_manager.reindex_and_project
            )

            if not grid_data or grid_data.n_documents == 0:
                yield InitProgress(
                    phase=InitProgress.Phase.ERROR,
                    progress=0.0,
                    message="No documents found in KB",
                )
                return

            # PROJECTING
            yield InitProgress(
                phase=InitProgress.Phase.PROJECTING,
                progress=0.5,
                message=f"Projected {grid_data.n_documents} documents to grid",
                documents_processed=grid_data.n_documents,
                documents_total=grid_data.n_documents,
            )

            # TDA
            yield InitProgress(
                phase=InitProgress.Phase.TDA,
                progress=0.7,
                message="Computing TDA features (H0/H1/H2)...",
            )

            tda_features = CoreTDAFeatures()
            geometry_features = None
            grid_coords = None

            if grid_data.raw_embeddings is not None and len(grid_data.raw_embeddings) > 0:
                grid_coords = np.array([
                    grid_data.embedding_to_grid.get(i, (9, 9))
                    for i in range(len(grid_data.raw_embeddings))
                ])
                tda_features = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: tda_manager.compute_features(
                        grid_data.raw_embeddings,
                        grid_coords,
                        force_refresh=True
                    )
                )

            # GEOMETRY (compute curvature, gradients, divergence)
            yield InitProgress(
                phase=InitProgress.Phase.GEOMETRY,
                progress=0.85,
                message="Computing geometry features (curvature, gradients)...",
            )

            logger.info(f"Geometry check: raw_embeddings={grid_data.raw_embeddings is not None}, grid_coords={grid_coords is not None}")
            if grid_data.raw_embeddings is not None and grid_coords is not None:
                try:
                    k_neighbors = min(15, len(grid_data.raw_embeddings) - 1)
                    logger.info(f"Geometry: k_neighbors={k_neighbors}, len(raw_embeddings)={len(grid_data.raw_embeddings)}")
                    if k_neighbors >= 2:
                        gc = GeometryComputer(k_neighbors=k_neighbors)
                        geometry_features = await gc.compute_features(
                            grid_data.raw_embeddings, grid_coords
                        )
                        logger.info(f"Computed geometry features: curvatures={len(geometry_features.curvatures)}, gradients={len(geometry_features.gradients)}")
                except Exception as geom_err:
                    logger.warning(f"Geometry computation failed (non-fatal): {geom_err}")
                    import traceback
                    traceback.print_exc()
                    geometry_features = None
            else:
                logger.warning(f"Skipping geometry: no raw embeddings or grid coords")

            # SAVING
            yield InitProgress(
                phase=InitProgress.Phase.SAVING,
                progress=0.9,
                message="Saving to Postgres cache...",
            )

            await save_grid_state(
                kb_root=kb_root,
                grid_data=grid_data,
                tda_features=tda_features,
                embedding_model=embedding_model,
                projection_method=projection_method,
                embedding_type="multi",
                geometry_features=geometry_features,
            )

            generation = await get_current_generation(kb_root)

            # COMPLETE
            yield InitProgress(
                phase=InitProgress.Phase.COMPLETE,
                progress=1.0,
                message=f"Initialized {grid_data.n_documents} documents (gen {generation})",
                documents_processed=grid_data.n_documents,
                documents_total=grid_data.n_documents,
            )

        except Exception as e:
            logger.exception(f"InitProgressStream failed: {e}")
            yield InitProgress(
                phase=InitProgress.Phase.ERROR,
                progress=0.0,
                message=str(e),
            )
