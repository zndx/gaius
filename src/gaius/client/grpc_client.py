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
            ConnectionError: If not connected
            RuntimeError: If request fails
        """
        if not self._connected:
            raise ConnectionError("Not connected to engine")

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

    async def _call_health(self, action: str, params: dict, timeout: float) -> dict:
        """Handle Health service calls."""
        if action == "status" or action == "live":
            # Use OIP ServerLive
            response = await self._inference_stub.ServerLive(
                ServerLiveRequest(),
                timeout=timeout,
            )
            return {"healthy": response.live, "live": response.live}

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


async def get_grpc_client() -> GrpcEngineClient:
    """Get or create the gRPC engine client singleton."""
    global _grpc_client
    if _grpc_client is None:
        _grpc_client = GrpcEngineClient()
        await _grpc_client.connect()
    return _grpc_client


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
