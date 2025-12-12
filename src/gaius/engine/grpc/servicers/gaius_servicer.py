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
    # Init streaming
    InitCommand,
    InitEvent,
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
