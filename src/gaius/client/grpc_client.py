"""gRPC client for communicating with gaius-engine.

Provides a client-side interface for sending requests to the engine
daemon via gRPC, implementing the same interface as EngineClient
for easy substitution.

This is the preferred transport, replacing the non-functional Aeron IPC.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Optional

# Suppress gRPC fork warnings before importing grpc
# These messages spam stdout when gRPC is used with asyncio
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "0")

import grpc
from grpc import aio
from google.protobuf import empty_pb2
from google.protobuf.json_format import MessageToDict

from ..engine.generated import (
    # OIP stubs
    GRPCInferenceServiceStub,
    ServerLiveRequest,
    ServerReadyRequest,
    ModelReadyRequest,
    ServerMetadataRequest,
    ModelMetadataRequest,
    ModelInferRequest,
    InferTensorContents,
    InferParameter,
    # Gaius stubs
    GaiusServiceStub,
    CompleteRequest,
    SubmitJobRequest,
    GetJobResultRequest,
    TriggerEvolutionRequest,
    HealthStreamRequest,
    EventStreamRequest,
    StartEndpointRequest,
    StopEndpointRequest,
    RestartEndpointRequest,
    ProjectEmbeddingsRequest,
    ProjectQueryRequest,
    ComputeTDARequest,
    # Explain (Grid Position Interpretation)
    ExplainRequest,
    ExplainResponse,
    # Init streaming
    InitCommand,
    InitEvent,
    # Swarm streaming
    SwarmStreamRequest,
    SwarmEvent,
)

logger = logging.getLogger(__name__)


@dataclass
class GrpcClientConfig:
    """Configuration for the gRPC client.

    Attributes:
        host: Server hostname
        port: Server port
        timeout: Request timeout in seconds
        connect_timeout: Connection timeout in seconds
    """

    host: str = "localhost"
    port: int = 50051
    timeout: float = 30.0
    connect_timeout: float = 5.0

    @classmethod
    def from_env(cls) -> "GrpcClientConfig":
        """Create config from environment variables."""
        return cls(
            host=os.environ.get("GAIUS_GRPC_HOST", "localhost"),
            port=int(os.environ.get("GAIUS_GRPC_PORT", "50051")),
            timeout=float(os.environ.get("GAIUS_ENGINE_TIMEOUT", "30")),
            connect_timeout=float(os.environ.get("GAIUS_CONNECT_TIMEOUT", "5")),
        )


class GrpcEngineClient:
    """gRPC client for gaius-engine.

    Implements the same interface as EngineClient for easy substitution.
    This is the preferred transport for production use.

    Usage:
        client = GrpcEngineClient()
        await client.connect()

        # Call a service
        result = await client.call("Orchestrator", "status", {})

        # Subscribe to events
        client.subscribe_events(on_evolution_progress)

        await client.disconnect()
    """

    def __init__(self, config: Optional[GrpcClientConfig] = None):
        """Initialize client.

        Args:
            config: Client configuration
        """
        self.config = config or GrpcClientConfig.from_env()

        # gRPC channel and stubs
        self._channel: Optional[aio.Channel] = None
        self._inference_stub: Optional[GRPCInferenceServiceStub] = None
        self._gaius_stub: Optional[GaiusServiceStub] = None

        # Event subscribers
        self._event_callbacks: list[Callable] = []
        self._health_callbacks: list[Callable] = []

        # Background tasks
        self._event_task: Optional[asyncio.Task] = None
        self._health_task: Optional[asyncio.Task] = None

        # State
        self._connected = False
        self._using_socket = False  # For compatibility with EngineClient

    async def connect(self) -> bool:
        """Connect to the engine via gRPC.

        Returns:
            True if connected
        """
        if self._connected:
            return True

        target = f"{self.config.host}:{self.config.port}"

        try:
            # Create channel
            self._channel = aio.insecure_channel(
                target,
                options=[
                    ("grpc.max_receive_message_length", 100 * 1024 * 1024),
                    ("grpc.max_send_message_length", 100 * 1024 * 1024),
                ],
            )

            # Wait for channel to be ready
            await asyncio.wait_for(
                self._channel.channel_ready(),
                timeout=self.config.connect_timeout,
            )

            # Create stubs
            self._inference_stub = GRPCInferenceServiceStub(self._channel)
            self._gaius_stub = GaiusServiceStub(self._channel)

            self._connected = True
            logger.info(f"Connected to engine via gRPC at {target}")
            return True

        except asyncio.TimeoutError:
            logger.debug(f"gRPC connection timeout to {target}")
            return False
        except grpc.RpcError as e:
            logger.debug(f"gRPC connection failed: {e}")
            return False
        except Exception as e:
            logger.debug(f"gRPC connection error: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from the engine."""
        if not self._connected:
            return

        # Cancel background tasks
        if self._event_task:
            self._event_task.cancel()
            try:
                await self._event_task
            except asyncio.CancelledError:
                pass

        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        # Close channel
        if self._channel:
            await self._channel.close()

        self._connected = False
        self._channel = None
        self._inference_stub = None
        self._gaius_stub = None
        logger.info("Disconnected from engine (gRPC)")

    async def close(self) -> None:
        """Close the client connection (alias for disconnect)."""
        await self.disconnect()

    async def call(
        self,
        service: str,
        action: str,
        params: Optional[dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        """Call a service action.

        Maps service/action pairs to gRPC method calls.

        Args:
            service: Service name (Orchestrator, Scheduler, etc.)
            action: Action to perform
            params: Action parameters
            timeout: Request timeout (default from config)

        Returns:
            Response result dict

        Raises:
            TimeoutError: If request times out
            ConnectionError: If not connected after retry
            RuntimeError: If request fails
        """
        # Attempt reconnection if not connected
        if not self._connected:
            connected = await self.connect()
            if not connected:
                raise ConnectionError("Not connected to engine (reconnection failed)")

        timeout = timeout or self.config.timeout
        params = params or {}

        try:
            # Route to appropriate gRPC method
            if service == "Orchestrator":
                return await self._call_orchestrator(action, params, timeout)
            elif service == "Scheduler":
                return await self._call_scheduler(action, params, timeout)
            elif service == "Evolution":
                return await self._call_evolution(action, params, timeout)
            elif service == "Grid":
                return await self._call_grid(action, params, timeout)
            elif service == "Tda":
                return await self._call_tda(action, params, timeout)
            elif service == "Health":
                return await self._call_health(action, params, timeout)
            elif service == "Cognition":
                return await self._call_cognition(action, params, timeout)
            elif service == "Workload":
                return await self._call_workload(action, params, timeout)
            elif service == "Embedding":
                return await self._call_embedding(action, params, timeout)
            elif service == "Init":
                return await self._call_init(action, params, timeout)
            elif service == "Search":
                return await self._call_search(action, params, timeout)
            elif service == "Gaius":
                return await self._call_gaius(action, params, timeout)
            else:
                raise ValueError(f"Unknown service: {service}")

        except asyncio.TimeoutError:
            raise TimeoutError(f"Request {service}.{action} timed out")
        except grpc.RpcError as e:
            code = e.code()
            details = e.details()
            if code == grpc.StatusCode.DEADLINE_EXCEEDED:
                raise TimeoutError(f"Request {service}.{action} timed out")
            elif code == grpc.StatusCode.UNAVAILABLE:
                # Mark as disconnected so next call triggers reconnection
                self._connected = False
                raise ConnectionError(f"Service unavailable: {details}")
            else:
                raise RuntimeError(f"gRPC error ({code.name}): {details}")

    async def _call_orchestrator(
        self, action: str, params: dict, timeout: float
    ) -> dict:
        """Handle Orchestrator service calls."""
        if action == "status":
            response = await self._gaius_stub.OrchestratorStatus(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "list_agents":
            response = await self._gaius_stub.OrchestratorStatus(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            result = MessageToDict(response, preserving_proto_field_name=True)
            return {"agents": result.get("endpoints", [])}

        elif action == "ensure":
            # Agent-first: ensure endpoint is available
            endpoint = params.get("endpoint", "")
            response = await self._gaius_stub.EnsureEndpoint(
                StartEndpointRequest(endpoint_name=endpoint),  # Reuse StartEndpointRequest
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "start":
            endpoint = params.get("endpoint", "")
            response = await self._gaius_stub.StartEndpoint(
                StartEndpointRequest(endpoint_name=endpoint),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "stop":
            endpoint = params.get("endpoint", "")
            force = params.get("force", False)
            response = await self._gaius_stub.StopEndpoint(
                StopEndpointRequest(endpoint_name=endpoint, force=force),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "restart":
            endpoint = params.get("endpoint", "")
            response = await self._gaius_stub.RestartEndpoint(
                RestartEndpointRequest(endpoint_name=endpoint),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "clean_start":
            from ..engine.generated import CleanStartRequest
            endpoints = params.get("endpoints", [])
            response = await self._gaius_stub.CleanStart(
                CleanStartRequest(endpoints=endpoints),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        else:
            raise ValueError(f"Unknown Orchestrator action: {action}")

    async def _call_scheduler(self, action: str, params: dict, timeout: float) -> dict:
        """Handle Scheduler service calls."""
        if action == "status":
            response = await self._gaius_stub.SchedulerStatus(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "complete":
            request = CompleteRequest(
                agent_alias=params.get("agent", "fast"),
                prompt=params.get("prompt", ""),
                system_prompt=params.get("system_prompt", ""),
                max_tokens=params.get("max_tokens", 2048),
                temperature=params.get("temperature", 0.7),
                priority=params.get("priority", "normal"),
            )
            response = await self._gaius_stub.Complete(request, timeout=timeout)
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "submit":
            request = SubmitJobRequest(
                agent_alias=params.get("agent", "fast"),
                prompt=params.get("prompt", ""),
                system_prompt=params.get("system_prompt", ""),
                max_tokens=params.get("max_tokens", 2048),
                temperature=params.get("temperature", 0.7),
                priority=params.get("priority", "normal"),
            )
            response = await self._gaius_stub.SubmitJob(request, timeout=timeout)
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "get_result":
            job_id = params.get("job_id", "")
            response = await self._gaius_stub.GetJobResult(
                GetJobResultRequest(job_id=job_id),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "run_swarm":
            # Run swarm by calling Complete for each agent role
            return await self._run_swarm_via_grpc(params, timeout)

        else:
            raise ValueError(f"Unknown Scheduler action: {action}")

    async def _call_evolution(self, action: str, params: dict, timeout: float) -> dict:
        """Handle Evolution service calls."""
        if action == "status":
            response = await self._gaius_stub.EvolutionStatus(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "trigger":
            agent_id = params.get("agent_id", "")
            response = await self._gaius_stub.TriggerEvolution(
                TriggerEvolutionRequest(agent_id=agent_id),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "start":
            response = await self._gaius_stub.StartEvolution(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "stop":
            response = await self._gaius_stub.StopEvolution(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        else:
            raise ValueError(f"Unknown Evolution action: {action}")

    async def _call_grid(self, action: str, params: dict, timeout: float) -> dict:
        """Handle Grid service calls."""
        if action == "status":
            return {"cached_projections": 0, "method": "umap", "grid_size": 19}

        elif action == "project":
            embedding_ids = params.get("embedding_ids", [])
            method = params.get("method", "umap")
            grid_size = params.get("grid_size", 19)
            response = await self._gaius_stub.ProjectEmbeddings(
                ProjectEmbeddingsRequest(
                    embedding_ids=embedding_ids,
                    method=method,
                    grid_size=grid_size,
                ),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "project_query":
            embedding = params.get("embedding", [])
            method = params.get("method", "umap")
            response = await self._gaius_stub.ProjectQuery(
                ProjectQueryRequest(embedding=embedding, method=method),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        else:
            raise ValueError(f"Unknown Grid action: {action}")

    async def _call_tda(self, action: str, params: dict, timeout: float) -> dict:
        """Handle TDA service calls."""
        if action == "status":
            return {"cached_results": 0, "max_dimension": 2}

        elif action == "compute":
            embedding_ids = params.get("embedding_ids", [])
            method = params.get("method", "persistent_homology")
            max_dimension = params.get("max_dimension", 2)
            response = await self._gaius_stub.ComputeTDA(
                ComputeTDARequest(
                    embedding_ids=embedding_ids,
                    method=method,
                    max_dimension=max_dimension,
                ),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        else:
            raise ValueError(f"Unknown TDA action: {action}")

    async def explain(
        self,
        kb_root: str,
        x: int,
        y: int,
        save_to_kb: bool = False,
        max_tokens: int = 800,
        client_id: str = "cli",
    ) -> "ExplainResponse":
        """Explain a grid position via Engine gRPC.

        All heavy computation (TDA, geometry, minigrid, LLM) happens on Engine.
        No fallbacks - Engine must be functional.

        Args:
            kb_root: KB root directory
            x: Grid x coordinate (0-18)
            y: Grid y coordinate (0-18)
            save_to_kb: Save explanation as zettelkasten entry
            max_tokens: Max tokens for LLM explanation
            client_id: Client identifier

        Returns:
            ExplainResponse from Engine
        """
        if not self._connected:
            connected = await self.connect()
            if not connected or self._gaius_stub is None:
                raise RuntimeError(
                    f"Failed to connect to Engine at {self.config.host}:{self.config.port}. "
                    "Ensure gaius-engine is running."
                )

        response = await self._gaius_stub.Explain(
            ExplainRequest(
                kb_root=kb_root,
                x=x,
                y=y,
                save_to_kb=save_to_kb,
                client_id=client_id,
                max_tokens=max_tokens,
            ),
            timeout=120.0,  # Explain can take a while with LLM
        )
        return response

    async def _call_health(self, action: str, params: dict, timeout: float) -> dict:
        """Handle Health service calls."""
        if action == "status" or action == "live":
            # Use OIP ServerLive
            response = await self._inference_stub.ServerLive(
                ServerLiveRequest(),
                timeout=timeout,
            )
            return {"healthy": response.live, "live": response.live}

        elif action == "check":
            # Comprehensive health check - get endpoint status from orchestrator
            orch_response = await self._gaius_stub.OrchestratorStatus(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            result = MessageToDict(orch_response, preserving_proto_field_name=True)
            # Convert endpoints list to dict for easier access
            endpoints = {}
            for ep in result.get("endpoints", []):
                endpoints[ep.get("name", "")] = {
                    "status": ep.get("status", "unknown"),
                    "port": ep.get("port", 0),
                    "model": ep.get("model", ""),
                }
            return {"endpoints": endpoints, "gpus": []}

        elif action == "gpu":
            # GPU utilization - not available via gRPC currently
            return {"utilization": {}}

        elif action == "ready":
            response = await self._inference_stub.ServerReady(
                ServerReadyRequest(),
                timeout=timeout,
            )
            return {"ready": response.ready}

        elif action == "model_ready":
            model_name = params.get("model", "")
            response = await self._inference_stub.ModelReady(
                ModelReadyRequest(name=model_name),
                timeout=timeout,
            )
            return {"model": model_name, "ready": response.ready}

        elif action == "metrics":
            # Get health metrics snapshot
            return {
                "gpus": [],
                "endpoints": [],
                "queue_depth": 0,
            }

        else:
            raise ValueError(f"Unknown Health action: {action}")

    async def _call_cognition(self, action: str, params: dict, timeout: float) -> dict:
        """Handle Cognition service calls via gRPC."""
        from datetime import datetime

        if action == "status":
            response = await self._gaius_stub.CognitionStatus(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            last_cycle_at = None
            if response.last_cycle_timestamp_ms > 0:
                last_cycle_at = datetime.fromtimestamp(
                    response.last_cycle_timestamp_ms / 1000
                ).isoformat()
            return {
                "running": response.running,
                "cycles_completed": response.cycles_completed,
                "last_cycle_at": last_cycle_at,
                "current_task": response.current_task or None,
            }

        elif action == "recent_thoughts":
            from ..engine.generated import GetRecentThoughtsRequest

            limit = params.get("limit", 10)
            response = await self._gaius_stub.GetRecentThoughts(
                GetRecentThoughtsRequest(limit=limit),
                timeout=timeout,
            )
            thoughts = []
            for t in response.thoughts:
                timestamp = None
                if t.timestamp_ms > 0:
                    timestamp = datetime.fromtimestamp(
                        t.timestamp_ms / 1000
                    ).isoformat()
                thoughts.append({
                    "id": t.id,
                    "type": t.thought_type,
                    "title": t.title,
                    "summary": t.summary,
                    "salience": t.salience,
                    "generation": t.generation,
                    "timestamp": timestamp,
                    "note_path": t.note_path,
                })
            return {"thoughts": thoughts}

        elif action == "activity":
            response = await self._gaius_stub.CognitionActivity(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            return {
                "cognition_running": response.cognition_running,
                "cycles_completed": response.cycles_completed,
                "last_cycle_at": None,  # TODO: convert timestamp
                "current_task": response.current_task or None,
                "thoughts_today": response.thoughts_today,
                "active_thoughts": response.active_thoughts,
            }

        elif action == "trigger":
            from ..engine.generated import TriggerCognitionRequest

            max_thoughts = params.get("max_thoughts", 5)
            trigger_reason = params.get("trigger_reason", "manual")
            response = await self._gaius_stub.TriggerCognition(
                TriggerCognitionRequest(
                    max_thoughts=max_thoughts,
                    trigger_reason=trigger_reason,
                ),
                timeout=timeout,
            )
            return {
                "success": response.success,
                "thoughts_generated": response.thoughts_generated,
                "patterns_detected": response.patterns_detected,
                "connections_found": response.connections_found,
                "curiosities_generated": response.curiosities_generated,
                "duration_ms": response.duration_ms,
                "error": response.error or None,
            }

        else:
            raise ValueError(f"Unknown Cognition action: {action}")

    async def _call_workload(self, action: str, params: dict, timeout: float) -> dict:
        """Handle Workload service calls via gRPC."""
        from google.protobuf.json_format import MessageToDict
        from ..engine.generated import (
            BeginWorkloadRequest,
            CompleteWorkloadRequest,
            WorkloadType as ProtoWorkloadType,
        )

        if action == "begin":
            # Map string workload type to proto enum
            workload_type_str = params.get("workload_type", "INIT")
            workload_type_map = {
                "INIT": ProtoWorkloadType.WORKLOAD_INIT,
                "SWARM": ProtoWorkloadType.WORKLOAD_SWARM,
                "INFERENCE": ProtoWorkloadType.WORKLOAD_INFERENCE,
                "EMBEDDING": ProtoWorkloadType.WORKLOAD_EMBEDDING,
            }
            workload_type = workload_type_map.get(
                workload_type_str, ProtoWorkloadType.WORKLOAD_INIT
            )

            request = BeginWorkloadRequest(
                workload_id=params.get("workload_id", ""),
                workload_type=workload_type,
                required_capabilities=params.get("required_capabilities", []),
                priority=params.get("priority", "NORMAL"),
                estimated_duration_s=params.get("estimated_duration_s", 60),
                estimated_memory_mb=params.get("estimated_memory_mb", 0),
            )
            response = await self._gaius_stub.BeginWorkload(request, timeout=timeout)
            result = MessageToDict(response, preserving_proto_field_name=True)
            return result

        elif action == "complete":
            request = CompleteWorkloadRequest(
                workload_id=params.get("workload_id", ""),
            )
            await self._gaius_stub.CompleteWorkload(request, timeout=timeout)
            return {"success": True}

        elif action == "active":
            response = await self._gaius_stub.GetActiveWorkloads(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            result = MessageToDict(response, preserving_proto_field_name=True)
            return result

        else:
            raise ValueError(f"Unknown Workload action: {action}")

    async def _call_embedding(self, action: str, params: dict, timeout: float) -> dict:
        """Handle Embedding service calls via gRPC."""
        from ..engine.generated import EmbedTextsRequest

        if action == "embed_texts":
            texts = params.get("texts", [])
            model = params.get("model", "")

            request = EmbedTextsRequest(texts=texts, model=model)
            response = await self._gaius_stub.EmbedTexts(request, timeout=timeout)

            # Convert embeddings to lists
            embeddings = [list(v.values) for v in response.embeddings]
            return {
                "embeddings": embeddings,
                "model_used": response.model_used,
                "latency_ms": response.latency_ms,
            }

        elif action == "model_info":
            # Not implemented on server yet, return placeholder
            return {"model": "all-MiniLM-L6-v2", "dimension": 384}

        else:
            raise ValueError(f"Unknown Embedding action: {action}")

    async def _call_search(self, action: str, params: dict, timeout: float) -> dict:
        """Handle Search service calls via gRPC."""
        from ..engine.generated import SemanticSearchRequest

        if action == "semantic":
            request = SemanticSearchRequest(
                query=params.get("query", ""),
                collection=params.get("collection", "kb"),
                limit=params.get("limit", 10),
                min_score=params.get("min_score", 0.0),
                use_maxsim=params.get("use_maxsim", True),
                content_type=params.get("content_type", ""),
            )
            response = await self._gaius_stub.SemanticSearch(request, timeout=timeout)

            return {
                "results": [
                    {
                        "path": r.path,
                        "title": r.title,
                        "score": r.score,
                        "snippet": r.snippet,
                        "chunk_id": r.chunk_id,
                        "content_type": r.content_type,
                    }
                    for r in response.results
                ],
                "total": response.total,
                "collection": response.collection,
                "embedding_model": response.embedding_model,
                "latency_ms": response.latency_ms,
            }

        else:
            raise ValueError(f"Unknown Search action: {action}")

    async def _call_gaius(self, action: str, params: dict, timeout: float) -> dict:
        """Handle Gaius-specific service calls (MetaAgent, etc.)."""
        from ..engine.generated import MetaAgentQueryRequest

        if action == "MetaAgentQuery":
            request = MetaAgentQueryRequest(
                query=params.get("query", ""),
                domains=params.get("domains", []),
                include_dot=params.get("include_dot", True),
                include_markdown=params.get("include_markdown", True),
                max_agents=params.get("max_agents", 5),
            )
            response = await self._gaius_stub.MetaAgentQuery(request, timeout=timeout)

            # Decode agent insights bytes
            agent_insights = {}
            for role_name, insight_bytes in response.agent_insights.items():
                import json
                try:
                    agent_insights[role_name] = json.loads(insight_bytes.decode())
                except Exception:
                    agent_insights[role_name] = {}

            return {
                "success": response.success,
                "answer": response.answer,
                "dot_graph": response.dot_graph,
                "markdown_tables": list(response.markdown_tables),
                "agent_insights": agent_insights,
                "queries_executed": list(response.queries_executed),
                "agents_used": response.agents_used,
                "duration_ms": response.duration_ms,
                "error": response.error,
            }

        else:
            raise ValueError(f"Unknown Gaius action: {action}")

    async def _call_init(self, action: str, params: dict, timeout: float) -> dict:
        """Handle Init/Reindex service calls via gRPC.

        These are heavy compute operations that run on the Engine:
        - init: Full initialization (index + project + TDA + save)
        - reindex: Re-index KB documents and recompute projection

        Args:
            action: Action to perform (init, reindex)
            params: Action parameters (kb_root, force, embedding_model, projection_method)
            timeout: Request timeout (default 300s for heavy operations)

        Returns:
            Result dict with success, message, counts, generation
        """
        from ..engine.generated import InitRequest, ReindexRequest

        # Use longer timeout for heavy operations (default 5 min)
        timeout = timeout or 300.0

        if action == "init":
            kb_root = params.get("kb_root", "build/dev")
            client_id = params.get("client_id", "grpc_client")
            force = params.get("force", False)
            embedding_model = params.get("embedding_model", "")
            projection_method = params.get("projection_method", "")

            request = InitRequest(
                kb_root=kb_root,
                client_id=client_id,
                force=force,
                embedding_model=embedding_model,
                projection_method=projection_method,
            )
            response = await self._gaius_stub.Init(request, timeout=timeout)
            return {
                "success": response.success,
                "message": response.message,
                "documents_indexed": response.documents_indexed,
                "h0_count": response.h0_count,
                "h1_count": response.h1_count,
                "h2_count": response.h2_count,
                "entropy": response.entropy,
                "generation": response.generation,
                "duration_ms": response.duration_ms,
            }

        elif action == "reindex":
            kb_root = params.get("kb_root", "build/dev")
            client_id = params.get("client_id", "grpc_client")
            force = params.get("force", False)
            embedding_model = params.get("embedding_model", "")

            request = ReindexRequest(
                kb_root=kb_root,
                client_id=client_id,
                force=force,
                embedding_model=embedding_model,
            )
            response = await self._gaius_stub.Reindex(request, timeout=timeout)
            return {
                "success": response.success,
                "message": response.message,
                "documents_indexed": response.documents_indexed,
                "documents_skipped": response.documents_skipped,
                "generation": response.generation,
                "duration_ms": response.duration_ms,
            }

        else:
            raise ValueError(f"Unknown Init action: {action}")

    async def init_with_progress(
        self,
        kb_root: str = "build/dev",
        force: bool = False,
        embedding_model: str = "",
        projection_method: str = "",
    ):
        """Stream init progress updates.

        Yields progress dicts with phase, progress, message, and optional counts.
        Use this for CLI/TUI progress display.

        Usage:
            async for progress in client.init_with_progress(force=True):
                print(f"{progress['phase']}: {progress['progress']:.0%} - {progress['message']}")

        Yields:
            dict with keys: phase, progress (0.0-1.0), message, documents_processed, documents_total
        """
        from ..engine.generated import InitRequest, InitProgress

        if not self._connected:
            await self.connect()

        request = InitRequest(
            kb_root=kb_root,
            client_id="grpc_client",
            force=force,
            embedding_model=embedding_model,
            projection_method=projection_method,
        )

        # Map proto phase enum to string names
        phase_names = {
            InitProgress.Phase.STARTED: "started",
            InitProgress.Phase.SCANNING: "scanning",
            InitProgress.Phase.EMBEDDING: "embedding",
            InitProgress.Phase.PROJECTING: "projecting",
            InitProgress.Phase.TDA: "tda",
            InitProgress.Phase.GEOMETRY: "geometry",
            InitProgress.Phase.SAVING: "saving",
            InitProgress.Phase.COMPLETE: "complete",
            InitProgress.Phase.ERROR: "error",
        }

        async for progress in self._gaius_stub.InitProgressStream(request):
            yield {
                "phase": phase_names.get(progress.phase, "unknown"),
                "progress": progress.progress,
                "message": progress.message,
                "documents_processed": progress.documents_processed,
                "documents_total": progress.documents_total,
            }

    async def reindex_with_progress(
        self,
        kb_root: str = "build/dev",
        force: bool = False,
        embedding_model: str = "",
    ):
        """Stream reindex progress updates.

        Yields progress dicts with phase, progress, message, and optional counts.

        Yields:
            dict with keys: phase, progress (0.0-1.0), message, documents_processed, documents_total
        """
        from ..engine.generated import ReindexRequest, ReindexProgress

        if not self._connected:
            await self.connect()

        request = ReindexRequest(
            kb_root=kb_root,
            client_id="grpc_client",
            force=force,
            embedding_model=embedding_model,
        )

        # Map proto phase enum to string names
        phase_names = {
            ReindexProgress.Phase.STARTED: "started",
            ReindexProgress.Phase.SCANNING: "scanning",
            ReindexProgress.Phase.EMBEDDING: "embedding",
            ReindexProgress.Phase.PROJECTING: "projecting",
            ReindexProgress.Phase.TDA: "tda",
            ReindexProgress.Phase.SAVING: "saving",
            ReindexProgress.Phase.COMPLETE: "complete",
            ReindexProgress.Phase.ERROR: "error",
        }

        async for progress in self._gaius_stub.ReindexStream(request):
            yield {
                "phase": phase_names.get(progress.phase, "unknown"),
                "progress": progress.progress,
                "message": progress.message,
                "documents_processed": progress.documents_processed,
                "documents_total": progress.documents_total,
            }

    # =========================================================================
    # Swarm Operations
    # =========================================================================

    async def _run_swarm_via_grpc(
        self, params: dict, timeout: float
    ) -> dict[str, dict]:
        """Run swarm analysis by calling Complete for each agent role.

        Maps role capabilities to appropriate agent endpoints and runs
        all agents in parallel.

        Args:
            params: {domain, context, roles}
            timeout: Request timeout per agent

        Returns:
            Dict mapping role name to result dict
        """
        import time
        from google.protobuf.json_format import MessageToDict

        domain = params.get("domain", "")
        context = params.get("context", "")
        roles = params.get("roles")

        # Default swarm roles
        if roles is None:
            roles = ["Leader", "Risk", "Optimizer", "Planner", "Critic", "Executor", "Adversary"]

        # Map role capabilities to endpoints
        # Capabilities: reasoning, coding, fast, long_context, adversarial, synthesis
        ROLE_TO_ENDPOINT = {
            "Leader": "orchestrator",      # reasoning/synthesis
            "Risk": "fast",                # analysis
            "Optimizer": "fast",           # analysis
            "Planner": "orchestrator",     # reasoning
            "Critic": "fast",              # adversarial/analysis
            "Executor": "fast",            # execution
            "Adversary": "fast",           # adversarial
        }

        # Get role prompts
        try:
            from ..agents.roles import AgentRole, get_role

            async def run_agent(role_name: str) -> tuple[str, dict]:
                start = time.perf_counter()
                try:
                    role_enum = AgentRole(role_name)
                    role_def = get_role(role_enum)
                    prompt = role_def.get_prompt(domain, context)
                    endpoint = ROLE_TO_ENDPOINT.get(role_name, "fast")

                    request = CompleteRequest(
                        agent_alias=endpoint,
                        prompt=prompt,
                        system_prompt=role_def.system_prompt or "",
                        max_tokens=role_def.max_tokens,
                        temperature=role_def.temperature,
                        priority="high",
                    )
                    response = await self._gaius_stub.Complete(request, timeout=timeout)
                    result = MessageToDict(response, preserving_proto_field_name=True)

                    latency = int((time.perf_counter() - start) * 1000)
                    # Proto field is 'text', not 'content'
                    content = result.get("text", "") or result.get("content", "")
                    return role_name, {
                        "status": "completed",
                        "content": content,
                        "model": result.get("model", ""),
                        "endpoint": endpoint,
                        "latency_ms": latency,
                        "input_tokens": result.get("input_tokens", 0),
                        "output_tokens": result.get("tokens_used", 0),
                    }
                except Exception as e:
                    latency = int((time.perf_counter() - start) * 1000)
                    return role_name, {
                        "status": "failed",
                        "error": str(e),
                        "latency_ms": latency,
                    }

            # Run all agents in parallel
            tasks = [run_agent(role) for role in roles]
            results = await asyncio.gather(*tasks)

            return {name: result for name, result in results}

        except ImportError:
            return {"error": "agents.roles not available"}

    # =========================================================================
    # OIP Methods (Direct access to KServe OIP)
    # =========================================================================

    async def server_live(self) -> bool:
        """Check if server is live (OIP ServerLive)."""
        response = await self._inference_stub.ServerLive(
            ServerLiveRequest(),
            timeout=self.config.timeout,
        )
        return response.live

    async def server_ready(self) -> bool:
        """Check if server is ready (OIP ServerReady)."""
        response = await self._inference_stub.ServerReady(
            ServerReadyRequest(),
            timeout=self.config.timeout,
        )
        return response.ready

    async def model_ready(self, model_name: str) -> bool:
        """Check if a specific model is ready (OIP ModelReady)."""
        response = await self._inference_stub.ModelReady(
            ModelReadyRequest(name=model_name),
            timeout=self.config.timeout,
        )
        return response.ready

    async def server_metadata(self) -> dict:
        """Get server metadata (OIP ServerMetadata)."""
        response = await self._inference_stub.ServerMetadata(
            ServerMetadataRequest(),
            timeout=self.config.timeout,
        )
        return MessageToDict(response, preserving_proto_field_name=True)

    async def model_metadata(self, model_name: str) -> dict:
        """Get model metadata (OIP ModelMetadata)."""
        response = await self._inference_stub.ModelMetadata(
            ModelMetadataRequest(name=model_name),
            timeout=self.config.timeout,
        )
        return MessageToDict(response, preserving_proto_field_name=True)

    # =========================================================================
    # Streaming
    # =========================================================================

    def subscribe_events(self, callback: Callable) -> None:
        """Subscribe to event notifications.

        Args:
            callback: Function called with each event (dict)
        """
        self._event_callbacks.append(callback)

        # Start event stream if not running
        if self._event_task is None and self._connected:
            self._event_task = asyncio.create_task(self._event_stream_loop())

    def subscribe_health(self, callback: Callable) -> None:
        """Subscribe to health updates.

        Args:
            callback: Function called with each health update (dict)
        """
        self._health_callbacks.append(callback)

        # Start health stream if not running
        if self._health_task is None and self._connected:
            self._health_task = asyncio.create_task(self._health_stream_loop())

    def unsubscribe_events(self, callback: Callable) -> None:
        """Unsubscribe from events."""
        if callback in self._event_callbacks:
            self._event_callbacks.remove(callback)

    def unsubscribe_health(self, callback: Callable) -> None:
        """Unsubscribe from health updates."""
        if callback in self._health_callbacks:
            self._health_callbacks.remove(callback)

    async def _event_stream_loop(self) -> None:
        """Background task to receive event stream."""
        try:
            request = EventStreamRequest()
            async for event in self._gaius_stub.EventStream(request):
                event_dict = MessageToDict(event, preserving_proto_field_name=True)
                for callback in self._event_callbacks:
                    try:
                        callback(event_dict)
                    except Exception as e:
                        logger.error(f"Event callback error: {e}")
        except asyncio.CancelledError:
            pass
        except grpc.RpcError as e:
            if e.code() != grpc.StatusCode.CANCELLED:
                logger.error(f"Event stream error: {e}")

    async def _health_stream_loop(self) -> None:
        """Background task to receive health stream."""
        try:
            request = HealthStreamRequest(interval_ms=1000)
            async for metrics in self._gaius_stub.HealthStream(request):
                metrics_dict = MessageToDict(metrics, preserving_proto_field_name=True)
                for callback in self._health_callbacks:
                    try:
                        callback(metrics_dict)
                    except Exception as e:
                        logger.error(f"Health callback error: {e}")
        except asyncio.CancelledError:
            pass
        except grpc.RpcError as e:
            if e.code() != grpc.StatusCode.CANCELLED:
                logger.error(f"Health stream error: {e}")

    async def health_stream(
        self, interval_ms: int = 1000
    ) -> AsyncIterator[dict]:
        """Stream health metrics.

        Args:
            interval_ms: Update interval in milliseconds

        Yields:
            Health metrics dicts
        """
        request = HealthStreamRequest(interval_ms=interval_ms)
        async for metrics in self._gaius_stub.HealthStream(request):
            yield MessageToDict(metrics, preserving_proto_field_name=True)

    async def event_stream(
        self, event_types: Optional[list[str]] = None
    ) -> AsyncIterator[dict]:
        """Stream events.

        Args:
            event_types: Optional filter for event types

        Yields:
            Event dicts
        """
        request = EventStreamRequest(event_types=event_types or [])
        async for event in self._gaius_stub.EventStream(request):
            yield MessageToDict(event, preserving_proto_field_name=True)

    async def init_stream(self) -> AsyncIterator[dict]:
        """Stream initialization events (bidirectional).

        Connects to the InitStream RPC which provides real-time updates
        during engine initialization (~240s startup phase).

        Yields:
            InitEvent dicts with:
                - type: Event type (PHASE_STARTED, PROGRESS, ENDPOINT_READY, etc.)
                - phase: Current init phase
                - progress: 0.0-1.0 overall progress
                - endpoint: Endpoint name (for endpoint-specific events)
                - message: Human-readable status message
        """
        async def command_generator():
            """Generate commands to send to InitStream."""
            # Send initial SUBSCRIBE command
            yield InitCommand(
                type=InitCommand.Type.SUBSCRIBE,
                client_id="grpc_client",
            )
            # Keep connection alive (server handles command processing)
            # Additional commands would be sent here for pause/cancel/etc.

        try:
            # Bidirectional streaming - send commands, receive events
            call = self._gaius_stub.InitStream(command_generator())
            async for event in call:
                event_dict = {
                    "type": InitEvent.Type.Name(event.type),
                    "timestamp_ms": event.timestamp_ms,
                    "phase": event.phase,
                    "progress": event.progress,
                    "endpoint": event.endpoint,
                    "message": event.message,
                }
                # Parse data payload if present (contains full status on SUBSCRIBE)
                if event.data:
                    try:
                        import json
                        event_dict["data"] = json.loads(event.data.decode())
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass
                yield event_dict
        except grpc.RpcError as e:
            if e.code() != grpc.StatusCode.CANCELLED:
                logger.debug(f"InitStream error: {e}")
            # Don't re-raise - let caller handle stream end gracefully

    async def send_init_command(
        self,
        command_type: str,
        endpoint: str = "",
    ) -> None:
        """Send a command to the init stream.

        Args:
            command_type: Command type (PAUSE, RESUME, CANCEL, SKIP)
            endpoint: Target endpoint for CANCEL/SKIP commands
        """
        # Map string to enum
        type_map = {
            "SUBSCRIBE": InitCommand.Type.SUBSCRIBE,
            "HEALTH": InitCommand.Type.HEALTH,
            "STATUS": InitCommand.Type.STATUS,
            "CANCEL": InitCommand.Type.CANCEL,
            "SKIP": InitCommand.Type.SKIP,
            "PAUSE": InitCommand.Type.PAUSE,
            "RESUME": InitCommand.Type.RESUME,
        }
        cmd_type = type_map.get(command_type.upper(), InitCommand.Type.STATUS)

        # Create one-shot command stream
        async def single_command():
            yield InitCommand(
                type=cmd_type,
                client_id="grpc_client",
                endpoint=endpoint,
            )

        try:
            # Send command (don't wait for response stream)
            call = self._gaius_stub.InitStream(single_command())
            # Read one response to confirm receipt
            async for event in call:
                logger.debug(f"Init command response: {event.type}")
                break
        except grpc.RpcError as e:
            logger.debug(f"Init command error: {e}")

    async def swarm_stream(
        self,
        domain: str,
        context: str = "",
        roles: Optional[list[str]] = None,
    ) -> AsyncIterator[dict]:
        """Stream swarm analysis with real-time progress updates.

        Unlike the blocking run_swarm, this streams status updates during
        execution, handling backend wait internally. The stream continues
        even while waiting for backends to initialize, preventing timeouts.

        Args:
            domain: Domain to analyze (e.g., "pension", "kudu")
            context: Additional context for the analysis
            roles: Agent roles to include (default: all core roles)

        Yields:
            SwarmEvent dicts with:
                - type: Event type (QUEUED, WAITING_FOR_BACKENDS, STARTED,
                        AGENT_STARTED, AGENT_COMPLETED, AGENT_FAILED, COMPLETED)
                - timestamp_ms: Event timestamp
                - agent: Agent name (for AGENT_* events)
                - progress: 0.0-1.0 overall progress
                - message: Human-readable status message
                - data: JSON payload (agent result on AGENT_COMPLETED,
                        final results on COMPLETED)

        Example:
            async for event in client.swarm_stream("pension"):
                print(f"{event['type']}: {event['message']} ({event['progress']:.0%})")
                if event['type'] == 'COMPLETED':
                    final = json.loads(event['data'])
                    print(f"Saved to: {final['saved_path']}")
        """
        request = SwarmStreamRequest(
            domain=domain,
            context=context,
            roles=roles or [],
        )

        try:
            async for event in self._gaius_stub.SwarmStream(request):
                yield {
                    "type": SwarmEvent.Type.Name(event.type),
                    "timestamp_ms": event.timestamp_ms,
                    "agent": event.agent,
                    "progress": event.progress,
                    "message": event.message,
                    "data": event.data.decode() if event.data else "",
                }
        except grpc.RpcError as e:
            if e.code() != grpc.StatusCode.CANCELLED:
                logger.error(f"SwarmStream error: {e}")
                # Yield a failure event
                yield {
                    "type": "FAILED",
                    "timestamp_ms": int(time.time() * 1000),
                    "agent": "",
                    "progress": 0.0,
                    "message": f"Stream error: {e.details()}",
                    "data": "",
                }

    @property
    def is_connected(self) -> bool:
        """Whether client is connected."""
        return self._connected

    @property
    def using_socket(self) -> bool:
        """Whether using Unix socket (for compatibility - always False for gRPC)."""
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Convenience Functions
# ─────────────────────────────────────────────────────────────────────────────

_grpc_client: Optional[GrpcEngineClient] = None
_grpc_connect_lock: asyncio.Lock | None = None


def _get_connect_lock() -> asyncio.Lock:
    """Get or create the connection lock (lazy init for event loop compatibility)."""
    global _grpc_connect_lock
    if _grpc_connect_lock is None:
        _grpc_connect_lock = asyncio.Lock()
    return _grpc_connect_lock


async def get_grpc_client() -> GrpcEngineClient:
    """Get or create the gRPC engine client singleton.

    If the client exists but is not connected, attempts to reconnect.
    This handles the case where the engine wasn't running when TUI started.

    Uses a lock to prevent concurrent connection attempts (which cause
    ENHANCE_YOUR_CALM errors from the server).
    """
    global _grpc_client

    if _grpc_client is None:
        _grpc_client = GrpcEngineClient()

    # Use lock to prevent concurrent connect attempts
    if not _grpc_client.is_connected:
        async with _get_connect_lock():
            # Re-check after acquiring lock (another coroutine may have connected)
            if not _grpc_client.is_connected:
                connected = await _grpc_client.connect()
                if not connected:
                    logger.debug("gRPC client not connected, will retry on next call")

    return _grpc_client


def reset_grpc_client() -> None:
    """Reset the gRPC client singleton.

    Call this to force a fresh connection on the next get_grpc_client() call.
    """
    global _grpc_client, _grpc_connect_lock
    if _grpc_client is not None:
        # Don't await disconnect - just clear the reference
        _grpc_client = None
    # Also reset the lock to avoid stale lock from previous event loop
    _grpc_connect_lock = None


async def call_grpc(
    service: str,
    action: str,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Convenience function to call engine service via gRPC.

    Args:
        service: Service name
        action: Action to perform
        params: Action parameters

    Returns:
        Response result
    """
    client = await get_grpc_client()
    return await client.call(service, action, params)
