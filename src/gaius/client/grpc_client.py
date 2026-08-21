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
    GaiusServiceAsyncStub,
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
    # HealthObserver
    HealthObserverStatusRequest,
    HealthObserverControlRequest,
    ForceHealthCheckRequest,
    ListIncidentsRequest,
    GetIncidentDetailRequest,
    ResolveIncidentRequest,
    GetOrphanedIssuesRequest,
    # Observability Dashboard
    ObserveStatusRequest,
    SignalsTelemetryRequest,
    # X Bookmarks
    XBookmarksAuthRequest,
    XBookmarksCompleteAuthRequest,
    XBookmarksAuthStatusRequest,
    XBookmarksSyncRequest,
    XBookmarksSyncStatusRequest,
    XBookmarksServiceStatusRequest,
    XBookmarksListFoldersRequest,
    XBookmarksQueueStatusRequest,
    XBookmarksEmitTestEventRequest,
    # Streaming (Cognition/Evolution/Activity)
    CognitionStreamRequest,
    CognitionEvent,
    EvolutionStreamRequest,
    EvolutionEvent,
    ActivityStreamRequest,
    ActivityEvent,
    # Ambient Computing
    AmbientCycleRequest,
    AmbientPhaseEvent,
    AmbientStartRequest,
    AmbientStartResponse,
    AmbientStopRequest,
    AmbientStopResponse,
    AmbientSubscribeRequest,
    # Prospects/Stewardship
    ProspectsStatusRequest,
    ProspectsStatusResponse,
    ProspectsCheckRequest,
    ProspectsCheckResponse,
    ProspectsUpdateRequest,
    ProspectsUpdateEvent,
    # Collections (Public Content Landing Page)
    CollectionStatusRequest,
    CollectionStatusResponse,
    CollectionListRequest,
    CollectionListResponse,
    CollectionCreateRequest,
    CollectionCreateResponse,
    CollectionSetFeaturedRequest,
    CollectionSetFeaturedResponse,
    CollectionAddCardRequest,
    CollectionAddCardResponse,
    CollectionListCardsRequest,
    CollectionListCardsResponse,
    CollectionPublishCardsRequest,
    CollectionPublishCardsResponse,
    CollectionPublishVizRequest,
    CollectionPublishVizResponse,
    CollectionSyncThemeRequest,
    CollectionSyncThemeResponse,
    # Multi-Phase Search Flow
    SearchFlowRequest,
    SearchFlowEvent,
    # Deep Research Flow (MemRL)
    ResearchFlowRequest,
    ResearchFlowEvent,
    # Article Curation
    ArticleStatusRequest,
    ArticleStatusResponse,
    ArticleNewRequest,
    ArticleNewResponse,
    ArticleCurateRequest,
    ArticleCurationEvent,
    # Rendering (Blender Card Visualization)
    RenderCardsRequest,
    RenderCardEvent,
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
        max_retries: Max connection retries (-1 = infinite, for TUI)
        retry_interval: Seconds between retry attempts
    """

    host: str = "localhost"
    port: int = 50051
    timeout: float = 30.0
    connect_timeout: float = 5.0
    max_retries: int = 3  # Default for CLI/MCP (finite)
    retry_interval: float = 5.0  # Poll every 5 seconds

    @classmethod
    def from_env(cls) -> "GrpcClientConfig":
        """Create config from environment variables."""
        return cls(
            host=os.environ.get("GAIUS_GRPC_HOST", "localhost"),
            port=int(os.environ.get("GAIUS_GRPC_PORT", "50051")),
            timeout=float(os.environ.get("GAIUS_ENGINE_TIMEOUT", "30")),
            connect_timeout=float(os.environ.get("GAIUS_CONNECT_TIMEOUT", "5")),
            max_retries=int(os.environ.get("GAIUS_MAX_RETRIES", "3")),
            retry_interval=float(os.environ.get("GAIUS_RETRY_INTERVAL", "5")),
        )

    @classmethod
    def for_tui(cls) -> "GrpcClientConfig":
        """Create config for TUI (infinite retries).

        TUI should never give up - it polls forever until engine is available.
        """
        config = cls.from_env()
        config.max_retries = -1  # Infinite retries
        return config

    @classmethod
    def for_cli(cls, max_retries: int = 3) -> "GrpcClientConfig":
        """Create config for CLI (finite retries).

        CLI operations are transactional - fail after max_retries.
        """
        config = cls.from_env()
        config.max_retries = max_retries
        return config

    @classmethod
    def for_mcp(cls, max_retries: int = 3) -> "GrpcClientConfig":
        """Create config for MCP server (finite retries).

        MCP operations are transactional - fail after max_retries.
        """
        config = cls.from_env()
        config.max_retries = max_retries
        return config


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
        self._gaius_stub: Optional[GaiusServiceAsyncStub] = None

        # Event subscribers
        self._event_callbacks: list[Callable] = []
        self._health_callbacks: list[Callable] = []

        # Background tasks
        self._event_task: Optional[asyncio.Task] = None
        self._health_task: Optional[asyncio.Task] = None

        # State
        self._connected = False
        self._using_socket = False  # For compatibility with EngineClient

    @property
    def _stub(self) -> GaiusServiceAsyncStub:
        """Get the Gaius service stub, raising if not connected.

        This property provides type-safe access to the stub with fail-fast
        behavior if the client is not connected.

        Raises:
            RuntimeError: If client is not connected.
        """
        if self._gaius_stub is None:
            raise RuntimeError(
                "gRPC client not connected.\n"
                "  Guru Meditation: #GRPC.00000001.NOT_CONNECTED\n"
                "  Call connect() before using the client."
            )
        return self._gaius_stub

    @property
    def _inference(self) -> GRPCInferenceServiceStub:
        """Get the inference service stub, raising if not connected.

        Raises:
            RuntimeError: If client is not connected.
        """
        if self._inference_stub is None:
            raise RuntimeError(
                "gRPC client not connected.\n"
                "  Guru Meditation: #GRPC.00000001.NOT_CONNECTED\n"
                "  Call connect() before using the client."
            )
        return self._inference_stub

    # ─────────────────────────────────────────────────────────────────────────
    # Async Context Manager Support
    # ─────────────────────────────────────────────────────────────────────────

    async def __aenter__(self) -> "GrpcEngineClient":
        """Async context manager entry - connects to the engine."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit - disconnects from the engine."""
        await self.disconnect()

    # ─────────────────────────────────────────────────────────────────────────
    # Connection Management
    # ─────────────────────────────────────────────────────────────────────────

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
            self._gaius_stub = GaiusServiceAsyncStub(self._channel)

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

        # Close channel (grace=None for immediate close)
        if self._channel:
            await self._channel.close(grace=None)

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
        """Call a service action with automatic retry on connection failure.

        Maps service/action pairs to gRPC method calls. Retries on connection
        failures according to config.max_retries (-1 = infinite for TUI).

        Args:
            service: Service name (Orchestrator, Scheduler, etc.)
            action: Action to perform
            params: Action parameters
            timeout: Request timeout (default from config)

        Returns:
            Response result dict

        Raises:
            TimeoutError: If request times out
            ConnectionError: If not connected after max retries
            RuntimeError: If request fails
        """
        timeout = timeout or self.config.timeout
        params = params or {}

        attempt = 0
        last_error: Optional[Exception] = None

        while True:
            attempt += 1
            infinite_retries = self.config.max_retries == -1

            # Attempt connection if not connected
            if not self._connected:
                connected = await self.connect()
                if not connected:
                    # Check if we should retry
                    if infinite_retries or attempt <= self.config.max_retries:
                        logger.debug(
                            f"gRPC connection failed, retry {attempt}"
                            f"{'/' + str(self.config.max_retries) if not infinite_retries else ' (infinite)'}"
                            f" in {self.config.retry_interval}s"
                        )
                        await asyncio.sleep(self.config.retry_interval)
                        continue
                    else:
                        # #GR.00000001.CONNFAIL - gRPC connection failed after max retries
                        error_msg = (
                            f"#GR.00000001.CONNFAIL: gRPC connection failed after {attempt} attempts.\n"
                            f"  Engine may not be running. Try:\n"
                            f"  1. Check engine status: devenv processes\n"
                            f"  2. Restart engine: just restart-clean\n"
                            f"  3. Check logs: tail -f .devenv/processes.log"
                        )
                        logger.error(error_msg)
                        raise ConnectionError(error_msg)

            try:
                # Route to appropriate gRPC method
                return await self._dispatch_call(service, action, params, timeout)

            except asyncio.TimeoutError:
                raise TimeoutError(f"Request {service}.{action} timed out")
            except grpc.RpcError as e:
                code = e.code()
                details = e.details()

                if code == grpc.StatusCode.DEADLINE_EXCEEDED:
                    raise TimeoutError(f"Request {service}.{action} timed out")

                elif code == grpc.StatusCode.UNAVAILABLE:
                    # Mark as disconnected for retry
                    self._connected = False
                    last_error = ConnectionError(f"Service unavailable: {details}")

                    # Check if we should retry
                    if infinite_retries or attempt <= self.config.max_retries:
                        logger.debug(
                            f"gRPC service unavailable, retry {attempt}"
                            f"{'/' + str(self.config.max_retries) if not infinite_retries else ' (infinite)'}"
                            f" in {self.config.retry_interval}s"
                        )
                        await asyncio.sleep(self.config.retry_interval)
                        continue
                    else:
                        # #GR.00000002.SVCUNAVAIL - Service unavailable after max retries
                        error_msg = (
                            f"#GR.00000002.SVCUNAVAIL: gRPC service unavailable after {attempt} attempts.\n"
                            f"  Engine may have crashed or restarted. Try:\n"
                            f"  1. Check engine status: /health quick\n"
                            f"  2. Restart engine: just restart-clean"
                        )
                        logger.error(error_msg)
                        raise ConnectionError(error_msg)

                else:
                    raise RuntimeError(f"gRPC error ({code.name}): {details}")

    async def stream(
        self,
        service: str,
        action: str,
        params: Optional[dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream events from a server-streaming RPC with idle timeout.

        Uses an idle timeout that resets each time an event is received.
        This allows long-running operations to proceed indefinitely as long
        as they're making progress, while detecting stuck operations.

        Currently supports:
            - Prospects.update: Stream progress events during full analysis

        Args:
            service: Service name (e.g., "Prospects")
            action: Action to perform (e.g., "update")
            params: Action parameters
            timeout: Idle timeout in seconds (default 300s = 5 minutes).
                     Only triggers if no events received for this duration.

        Yields:
            Event dicts from the streaming response

        Raises:
            TimeoutError: If no events received within idle timeout
            ConnectionError: If not connected
            RuntimeError: If request fails
        """
        timeout = timeout or 300.0  # 5 minute idle timeout (resets on each event received)
        params = params or {}

        # Ensure connected
        if not self._connected:
            connected = await self.connect()
            if not connected:
                raise ConnectionError(
                    "#GR.00000001.CONNFAIL: gRPC not connected for streaming call"
                )

        # Dispatch to appropriate streaming method
        if service == "Prospects" and action == "update":
            async for event in self._stream_prospects_update(params, timeout):
                yield event
        elif service == "Search" and action == "semantic_stream":
            async for event in self._stream_semantic_search(params, timeout):
                yield event
        elif service == "SearchFlow" and action == "search_stream":
            async for event in self._stream_search_flow(params, timeout):
                yield event
        elif service == "ResearchFlow" and action == "research_stream":
            async for event in self._stream_research_flow(params, timeout):
                yield event
        else:
            raise ValueError(
                f"Streaming not supported for {service}.{action}. "
                f"Use call() for non-streaming operations."
            )

    async def _stream_prospects_update(
        self,
        params: dict,
        idle_timeout: float,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream ProspectsUpdate events with idle timeout.

        Uses an idle timeout that resets on each received event, rather than
        an absolute deadline. This allows long-running operations to proceed
        as long as they're making progress.

        Args:
            params: Update parameters (profile, domain, symbols, force)
            idle_timeout: Idle timeout in seconds (default 300s = 5 minutes).
                          Only triggers if no events received for this duration.

        Yields:
            Event dicts with type, progress, message, etc.
        """
        profile = params.get("profile", "zndx")
        domain = params.get("domain", "prospecting")
        symbols = params.get("symbols", [])
        force = params.get("force", False)
        filings_per_symbol = params.get("filings_per_symbol", 0)

        request = ProspectsUpdateRequest(
            profile=profile,
            domain=domain,
            symbols=symbols,
            force=force,
            filings_per_symbol=filings_per_symbol,
        )

        try:
            # Use no gRPC timeout - we manage idle timeout ourselves
            stream = self._stub.ProspectsUpdate(request)
            async_iter = stream.__aiter__()

            while True:
                try:
                    # Wait for next event with idle timeout
                    event = await asyncio.wait_for(
                        async_iter.__anext__(),
                        timeout=idle_timeout,
                    )
                    yield MessageToDict(event, preserving_proto_field_name=True)
                except StopAsyncIteration:
                    # Stream completed normally
                    break
                except asyncio.TimeoutError:
                    # No event received within idle timeout
                    raise TimeoutError(
                        f"ProspectsUpdate stream idle for {idle_timeout}s with no events. "
                        f"The operation may be stuck. Check /prospects status for details."
                    )

        except grpc.RpcError as e:
            code = e.code()
            details = e.details()

            if code == grpc.StatusCode.UNAVAILABLE:
                self._connected = False
                raise ConnectionError(f"Service unavailable during streaming: {details}")
            else:
                raise RuntimeError(f"ProspectsUpdate stream error ({code.name}): {details}")

    async def _stream_search_flow(
        self,
        params: dict,
        idle_timeout: float,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream SearchFlow events with idle timeout.

        Uses Metaflow-based multi-phase search with:
        - BM25 lexical search
        - ColNomic vector search (GPU orchestrated)
        - Web search (Brave API)
        - Parallel synthesis (local + Grok)
        - KB artifact creation

        Args:
            params: Search parameters (query, skip_grok, limits)
            idle_timeout: Idle timeout in seconds (default 300s = 5 minutes).
                          Only triggers if no events received for this duration.

        Yields:
            Event dicts with type, progress, message, etc.
        """
        request = SearchFlowRequest(
            query=params.get("query", ""),
            skip_grok=params.get("skip_grok", False),
            bm25_limit=params.get("bm25_limit", 0),
            vector_limit=params.get("vector_limit", 0),
            web_limit=params.get("web_limit", 0),
        )

        # Map proto Type enum to string names
        TYPE_NAMES = {
            0: "UNSPECIFIED",
            1: "QUEUED",
            2: "BM25_STARTED",
            3: "BM25_COMPLETED",
            4: "VECTOR_STARTED",
            5: "VECTOR_EVICTING",
            6: "VECTOR_LOADING",
            7: "VECTOR_COMPLETED",
            8: "WEB_STARTED",
            9: "WEB_COMPLETED",
            10: "INSTRUCT_RESTORING",
            11: "INSTRUCT_READY",
            12: "LOCAL_SYNTHESIS_STARTED",
            13: "LOCAL_SYNTHESIS_COMPLETED",
            14: "GROK_SYNTHESIS_STARTED",
            15: "GROK_SYNTHESIS_COMPLETED",
            16: "SYNTHESIS_MERGED",
            17: "KB_WRITE",
            18: "COMPLETED",
            19: "FAILED",
        }

        try:
            stream = self._stub.SearchFlowStream(request)
            async_iter = stream.__aiter__()

            while True:
                try:
                    event = await asyncio.wait_for(
                        async_iter.__anext__(),
                        timeout=idle_timeout,
                    )

                    # Convert to dict with readable type name
                    event_dict = MessageToDict(event, preserving_proto_field_name=True)
                    event_type = event.type if hasattr(event, "type") else 0
                    event_dict["type_name"] = TYPE_NAMES.get(event_type, f"UNKNOWN_{event_type}")

                    yield event_dict

                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    raise TimeoutError(
                        f"SearchFlow stream idle for {idle_timeout}s with no events. "
                        f"The operation may be stuck. Check engine logs for details."
                    )

        except grpc.RpcError as e:
            code = e.code()
            details = e.details()

            if code == grpc.StatusCode.UNAVAILABLE:
                self._connected = False
                raise ConnectionError(f"Service unavailable during streaming: {details}")
            else:
                raise RuntimeError(f"SearchFlow stream error ({code.name}): {details}")

    async def _stream_research_flow(
        self,
        params: dict,
        idle_timeout: float,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream ResearchFlow events with idle timeout.

        Uses Metaflow-based multi-pass deep research with MemRL:
        - Episodic memory retrieval (Q-value weighted)
        - Multi-pass research cycles
        - 7-agent swarm analysis
        - Grok synthesis
        - Convergence detection
        - KB artifact creation

        Args:
            params: Research parameters (query, max_passes, drift_threshold, limits)
            idle_timeout: Idle timeout in seconds (default 600s = 10 minutes).
                          Only triggers if no events received for this duration.

        Yields:
            Event dicts with type, progress, message, pass_number, etc.
        """
        request = ResearchFlowRequest(
            query=params.get("query", ""),
            max_passes=params.get("max_passes", 0),
            drift_threshold=params.get("drift_threshold", 0.0),
            bm25_limit=params.get("bm25_limit", 0),
            vector_limit=params.get("vector_limit", 0),
            web_limit=params.get("web_limit", 0),
        )

        # Map proto Type enum to string names (matches proto definition)
        TYPE_NAMES = {
            0: "unspecified",
            1: "queued",
            2: "memories_retrieving",
            3: "memories_retrieved",
            4: "pass_started",
            5: "pass_search",
            6: "pass_swarm",
            7: "pass_grok",
            8: "pass_evaluate",
            9: "pass_qupdate",
            10: "pass_completed",
            11: "converged",
            12: "final_synthesis",
            13: "kb_write",
            14: "completed",
            15: "failed",
        }

        try:
            stream = self._stub.ResearchFlowStream(request)
            async_iter = stream.__aiter__()

            while True:
                try:
                    event = await asyncio.wait_for(
                        async_iter.__anext__(),
                        timeout=idle_timeout,
                    )

                    # Convert to dict with readable type name
                    event_dict = MessageToDict(event, preserving_proto_field_name=True)
                    event_type = event.type if hasattr(event, "type") else 0
                    event_dict["type_name"] = TYPE_NAMES.get(event_type, f"unknown_{event_type}")

                    yield event_dict

                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    raise TimeoutError(
                        f"ResearchFlow stream idle for {idle_timeout}s with no events. "
                        f"The operation may be stuck. Check engine logs for details."
                    )

        except grpc.RpcError as e:
            code = e.code()
            details = e.details()

            if code == grpc.StatusCode.UNAVAILABLE:
                self._connected = False
                raise ConnectionError(f"Service unavailable during streaming: {details}")
            else:
                raise RuntimeError(f"ResearchFlow stream error ({code.name}): {details}")

    async def _stream_semantic_search(
        self,
        params: dict,
        idle_timeout: float,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream SemanticSearchEvent progress events with idle timeout.

        Uses streaming to show GPU allocation and model loading progress
        during ColNomic cold start (~10-20s), rather than blocking on a
        long timeout.

        Args:
            params: Search parameters (query, limit, use_maxsim, etc.)
            idle_timeout: Idle timeout in seconds (default 60s for cold start).
                          Only triggers if no events received for this duration.

        Yields:
            Event dicts with phase, progress_pct, message, and results on COMPLETE.
        """
        from ..engine.generated import SemanticSearchRequest

        request = SemanticSearchRequest(
            query=params.get("query", ""),
            collection=params.get("collection", "kb"),
            limit=params.get("limit", 10),
            min_score=params.get("min_score", 0.0),
            use_maxsim=params.get("use_maxsim", True),
            content_type=params.get("content_type", ""),
        )

        # Map proto Phase enum to string names
        PHASE_NAMES = {
            0: "UNSPECIFIED",
            1: "REQUESTING_GPU",
            2: "EVICTING_ENDPOINTS",
            3: "LOADING_MODEL",
            4: "SEARCHING",
            5: "COMPLETE",
            6: "ERROR",
        }

        try:
            stream = self._stub.SemanticSearchStream(request)
            async_iter = stream.__aiter__()

            while True:
                try:
                    event = await asyncio.wait_for(
                        async_iter.__anext__(),
                        timeout=idle_timeout,
                    )

                    # Convert event to dict
                    event_dict = {
                        "phase": PHASE_NAMES.get(event.phase, "UNKNOWN"),
                        "message": event.message,
                        "progress_pct": event.progress_pct,
                        "timestamp_ms": event.timestamp_ms,
                    }

                    # Add error info if present
                    if event.error:
                        event_dict["error"] = event.error
                    if event.guru_code:
                        event_dict["guru_code"] = event.guru_code

                    # Add response on COMPLETE
                    if event.phase == 5 and event.response.total > 0:  # COMPLETE
                        event_dict["results"] = [
                            {
                                "path": r.path,
                                "title": r.title,
                                "score": r.score,
                                "snippet": r.snippet,
                                "chunk_id": r.chunk_id,
                                "content_type": r.content_type,
                            }
                            for r in event.response.results
                        ]
                        event_dict["total"] = event.response.total
                        event_dict["collection"] = event.response.collection
                        event_dict["embedding_model"] = event.response.embedding_model

                    yield event_dict

                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    raise TimeoutError(
                        f"SemanticSearchStream idle for {idle_timeout}s with no events. "
                        f"ColNomic loading may be stuck. Check /gpu status."
                    )

        except grpc.RpcError as e:
            code = e.code()
            details = e.details()

            if code == grpc.StatusCode.UNAVAILABLE:
                self._connected = False
                raise ConnectionError(f"Service unavailable during streaming: {details}")
            else:
                raise RuntimeError(f"SemanticSearchStream error ({code.name}): {details}")

    async def _dispatch_call(
        self, service: str, action: str, params: dict, timeout: float
    ) -> dict[str, Any]:
        """Dispatch call to appropriate service handler."""
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
        elif service == "Discover":
            return await self._call_discover(action, params, timeout)
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
        elif service == "CLT":
            return await self._call_clt(action, params, timeout)
        elif service == "HealthObserver":
            return await self._call_health_observer(action, params, timeout)
        elif service == "Observe":
            return await self._call_observe(action, params, timeout)
        elif service == "SignalsTelemetry":
            return await self._call_signals_telemetry(action, params, timeout)
        elif service == "XBookmarks":
            return await self._call_x_bookmarks(action, params, timeout)
        elif service == "Ambient":
            return await self._call_ambient(action, params, timeout)
        elif service == "Datasets":
            return await self._call_datasets(action, params, timeout)
        elif service == "Models":
            return await self._call_models(action, params, timeout)
        elif service == "Prospects":
            return await self._call_prospects(action, params, timeout)
        elif service == "ResearchFlow":
            return await self._call_research_flow(action, params, timeout)
        elif service == "Collection":
            return await self._call_collection(action, params, timeout)
        elif service == "Article":
            return await self._call_article(action, params, timeout)
        else:
            raise ValueError(f"Unknown service: {service}")

    async def _call_orchestrator(
        self, action: str, params: dict, timeout: float
    ) -> dict:
        """Handle Orchestrator service calls."""
        if action == "status":
            response = await self._stub.OrchestratorStatus(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "list_agents":
            response = await self._stub.OrchestratorStatus(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            result = MessageToDict(response, preserving_proto_field_name=True)
            return {"agents": result.get("endpoints", [])}

        elif action == "ensure":
            # Agent-first: ensure endpoint is available
            endpoint = params.get("endpoint", "")
            response = await self._stub.EnsureEndpoint(
                StartEndpointRequest(endpoint_name=endpoint),  # Reuse StartEndpointRequest
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "start":
            endpoint = params.get("endpoint", "")
            response = await self._stub.StartEndpoint(
                StartEndpointRequest(endpoint_name=endpoint),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "stop":
            endpoint = params.get("endpoint", "")
            force = params.get("force", False)
            response = await self._stub.StopEndpoint(
                StopEndpointRequest(endpoint_name=endpoint, force=force),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "restart":
            endpoint = params.get("endpoint", "")
            response = await self._stub.RestartEndpoint(
                RestartEndpointRequest(endpoint_name=endpoint),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "clean_start":
            from ..engine.generated import CleanStartRequest
            endpoints = params.get("endpoints", [])
            response = await self._stub.CleanStart(
                CleanStartRequest(endpoints=endpoints),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "phase_change":
            # Phase Change Pattern: Resilient dynamic workload coordination
            from ..engine.generated import PhaseChangeRequest
            response = await self._stub.PhaseChange(
                PhaseChangeRequest(
                    change_type=params.get("change_type", ""),
                    target_endpoint=params.get("target_endpoint", ""),
                    await_healthy=params.get("await_healthy", True),
                    timeout_s=params.get("timeout_s", 120.0),
                ),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "phase_change_profiles":
            response = await self._stub.GetPhaseChangeProfiles(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "active_phase_changes":
            response = await self._stub.GetActivePhaseChanges(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        else:
            raise ValueError(f"Unknown Orchestrator action: {action}")

    async def _call_scheduler(self, action: str, params: dict, timeout: float) -> dict:
        """Handle Scheduler service calls."""
        if action == "status":
            response = await self._stub.SchedulerStatus(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "complete":
            request = CompleteRequest(
                agent_alias=params.get("agent", "thinking"),
                prompt=params.get("prompt", ""),
                system_prompt=params.get("system_prompt", ""),
                max_tokens=params.get("max_tokens", 2048),
                temperature=params.get("temperature", 0.7),
                priority=params.get("priority", "normal"),
                technique=params.get("technique", ""),
            )
            response = await self._stub.Complete(request, timeout=timeout)
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "submit":
            request = SubmitJobRequest(
                agent_alias=params.get("agent", "thinking"),
                prompt=params.get("prompt", ""),
                system_prompt=params.get("system_prompt", ""),
                max_tokens=params.get("max_tokens", 2048),
                temperature=params.get("temperature", 0.7),
                priority=params.get("priority", "normal"),
            )
            response = await self._stub.SubmitJob(request, timeout=timeout)
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "get_result":
            job_id = params.get("job_id", "")
            response = await self._stub.GetJobResult(
                GetJobResultRequest(job_id=job_id),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "run_swarm":
            # Run swarm by calling Complete for each agent role
            return await self._run_swarm_via_grpc(params, timeout)

        elif action == "budget":
            # XAI budget status via gRPC
            response = await self._stub.XAIBudget(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        else:
            raise ValueError(f"Unknown Scheduler action: {action}")

    async def _call_evolution(self, action: str, params: dict, timeout: float) -> dict:
        """Handle Evolution service calls."""
        if action == "status":
            response = await self._stub.EvolutionStatus(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "trigger":
            agent_id = params.get("agent_id", "")
            response = await self._stub.TriggerEvolution(
                TriggerEvolutionRequest(agent_id=agent_id),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "start":
            response = await self._stub.StartEvolution(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "stop":
            response = await self._stub.StopEvolution(
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
            response = await self._stub.ProjectEmbeddings(
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
            response = await self._stub.ProjectQuery(
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
            response = await self._stub.ComputeTDA(
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

        response = await self._stub.Explain(
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
            response = await self._inference.ServerLive(
                ServerLiveRequest(),
                timeout=timeout,
            )
            return {"healthy": response.live, "live": response.live}

        elif action == "check":
            # Comprehensive health check - get endpoint status from orchestrator
            orch_response = await self._stub.OrchestratorStatus(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            result = MessageToDict(orch_response, preserving_proto_field_name=True)
            # Convert endpoints list to dict for easier access
            # Normalize protobuf enum status to simple strings
            status_map = {
                "PROCESS_STATUS_HEALTHY": "healthy",
                "PROCESS_STATUS_UNHEALTHY": "unhealthy",
                "PROCESS_STATUS_STARTING": "starting",
                "PROCESS_STATUS_STOPPED": "stopped",
                "PROCESS_STATUS_STOPPING": "stopping",
                "PROCESS_STATUS_FAILED": "failed",
            }
            endpoints = {}
            for ep in result.get("endpoints", []):
                raw_status = ep.get("status", "unknown")
                endpoints[ep.get("name", "")] = {
                    "status": status_map.get(raw_status, raw_status),
                    "port": ep.get("port", 0),
                    "model": ep.get("model", ""),
                }
            return {"endpoints": endpoints, "gpus": []}

        elif action == "gpu":
            # GPU utilization - not available via gRPC currently
            return {"utilization": {}}

        elif action == "ready":
            response = await self._inference.ServerReady(
                ServerReadyRequest(),
                timeout=timeout,
            )
            return {"ready": response.ready}

        elif action == "model_ready":
            model_name = params.get("model", "")
            response = await self._inference.ModelReady(
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

        elif action == "gpu_detailed":
            # Get detailed GPU health via HealthStream (single snapshot)
            from ..engine.generated import gaius_service_pb2
            request = gaius_service_pb2.HealthStreamRequest(interval_ms=0)
            try:
                # Stream returns first message immediately with interval_ms=0
                async for metrics in self._stub.HealthStream(request, timeout=timeout):
                    # Convert protobuf to dict
                    gpus = []
                    for gpu in metrics.gpus:
                        gpus.append({
                            "gpu_id": gpu.gpu_id,
                            "utilization": gpu.utilization,
                            "memory_used_gb": gpu.memory_used_gb,
                            "memory_total_gb": gpu.memory_total_gb,
                            "temperature_c": gpu.temperature_c,
                            "power_watts": gpu.power_watts,
                            "is_healthy": gpu.temperature_c < 85 and gpu.memory_used_gb < gpu.memory_total_gb * 0.95,
                        })
                    return {"gpus": gpus}
            except Exception as e:
                # Fallback: return empty GPU list with error
                return {"gpus": [], "error": str(e)}
            # Stream was empty (no messages received)
            return {"gpus": [], "error": "No GPU metrics received from stream"}

        else:
            raise ValueError(f"Unknown Health action: {action}")

    async def _call_discover(self, action: str, params: dict, timeout: float) -> dict:
        if action not in ("surface", "status", "refresh", ""):
            raise ValueError(f"Unknown Discover action: {action}")
        if action == "refresh":
            from ..engine.generated import RefreshDiscoverLandingRequest

            response = await self._stub.RefreshDiscoverLanding(
                RefreshDiscoverLandingRequest(
                    reason=str(params.get("reason") or "cli"),
                ),
                timeout=timeout,
            )
            if response.error:
                return {"error": response.error, "accepted": False}
            return {
                "accepted": bool(response.accepted),
                "started": bool(response.started),
                "refreshed_at": response.refreshed_at,
            }
        from ..engine.generated import DiscoverSurfaceRequest

        response = await self._stub.DiscoverSurface(
            DiscoverSurfaceRequest(
                window=str(params.get("window") or "36h"),
                query=str(params.get("query") or ""),
                breakdown=str(params.get("breakdown") or "source"),
                limit=int(params.get("limit") or 50),
                cursor=str(params.get("cursor") or ""),
                feature_pins=list(params.get("feature_pins") or []),
                from_ts=str(params.get("from_ts") or ""),
                to_ts=str(params.get("to_ts") or ""),
            ),
            timeout=timeout,
        )
        if response.error:
            return {"error": response.error}
        return {
            "window": response.window,
            "query": response.query,
            "interval": response.interval,
            "scraped_at": response.scraped_at,
            "total": response.total,
            "last_salience_at": response.last_salience_at,
            "clock": response.clock,
            "next_episode": (
                {
                    "kind": response.next_episode.kind,
                    "at": response.next_episode.at,
                    "eta_s": response.next_episode.eta_s,
                    "label": response.next_episode.label,
                }
                if response.next_episode.kind or response.next_episode.at
                else None
            ),
            "buckets": [
                {
                    "t": b.t,
                    "n": b.n,
                    "breakdown_key": b.breakdown_key,
                    "salience": b.salience,
                    "watts": b.watts,
                    "util": b.util,
                    "salience_ma": b.salience_ma,
                    "watts_ma": b.watts_ma,
                    "util_ma": b.util_ma,
                }
                for b in response.buckets
            ],
            "docs": [
                {
                    "id": d.id,
                    "stream": d.stream,
                    "source": d.source,
                    "ts": d.ts,
                    "title": d.title,
                    "body": d.body,
                    "source_id": d.source_id,
                    "url": d.url,
                }
                for d in response.docs
            ],
            "facets": [
                {
                    "key": f.key,
                    "kind": f.kind,
                    "count": f.count,
                    "salience": f.salience,
                }
                for f in response.facets
            ],
        }

    async def _call_cognition(self, action: str, params: dict, timeout: float) -> dict:
        """Handle Cognition service calls via gRPC."""
        from datetime import datetime

        if action == "status":
            response = await self._stub.CognitionStatus(
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
            response = await self._stub.GetRecentThoughts(
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
            response = await self._stub.CognitionActivity(
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

        elif action == "surface":
            from ..engine.generated import CognitionSurfaceRequest

            response = await self._stub.CognitionSurface(
                CognitionSurfaceRequest(
                    window_days=int(params.get("window_days") or 365),
                    thought_limit=int(params.get("thought_limit") or 80),
                    stream=str(params.get("stream") or ""),
                ),
                timeout=timeout,
            )
            if response.error:
                return {"error": response.error}
            last_cycle_at = None
            if response.last_cycle_timestamp_ms > 0:
                last_cycle_at = datetime.fromtimestamp(
                    response.last_cycle_timestamp_ms / 1000
                ).isoformat()

            def _thought(t: object) -> dict:
                ts = None
                ts_ms = getattr(t, "timestamp_ms", 0)
                if ts_ms:
                    ts = datetime.fromtimestamp(ts_ms / 1000).isoformat()
                return {
                    "id": getattr(t, "id", ""),
                    "type": getattr(t, "thought_type", ""),
                    "title": getattr(t, "title", ""),
                    "summary": getattr(t, "summary", ""),
                    "salience": getattr(t, "salience", 0.0),
                    "generation": getattr(t, "generation", 0),
                    "timestamp": ts,
                    "note_path": getattr(t, "note_path", ""),
                }

            return {
                "running": response.running,
                "cycles_completed": response.cycles_completed,
                "cycles_in_window": response.cycles_in_window,
                "last_cycle_at": last_cycle_at,
                "current_task": response.current_task or None,
                "thoughts": response.thoughts,
                "streams": response.streams,
                "active_days": response.active_days,
                "thoughts_per_cycle": response.thoughts_per_cycle,
                "concentration_stream": response.concentration_stream,
                "concentration_pct": response.concentration_pct,
                "reserve_tokens": response.reserve_tokens,
                "project": response.project,
                "unit": response.unit,
                "recent": [_thought(t) for t in response.recent],
                "top": [_thought(t) for t in response.top],
                "days": [
                    {"date": d.date, "thoughts": d.thoughts, "cycles": d.cycles}
                    for d in response.days
                ],
                "hours": [
                    {"weekday": h.weekday, "hour": h.hour, "thoughts": h.thoughts}
                    for h in response.hours
                ],
                "stream_counts": [
                    {"id": s.id, "thoughts": s.thoughts}
                    for s in response.stream_counts
                ],
            }

        elif action == "trigger":
            from ..engine.generated import TriggerCognitionRequest

            max_thoughts = params.get("max_thoughts", 5)
            trigger_reason = params.get("trigger_reason", "manual")
            response = await self._stub.TriggerCognition(
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
                "kb_path": response.kb_path if response.kb_path else None,
                "tokens_out": response.tokens_out,
                "error": response.error or None,
            }

        elif action == "self_observation":
            from ..engine.generated import SelfObservationRequest

            max_observations = params.get("max_observations", 5)
            response = await self._stub.SelfObservation(
                SelfObservationRequest(max_observations=max_observations),
                timeout=timeout,
            )
            return {
                "success": response.success,
                "observations_generated": response.observations_generated,
                "duration_ms": response.duration_ms,
                "error": response.error or None,
                "observation_ids": list(response.observation_ids),
            }

        elif action == "engine_audit":
            from ..engine.generated import EngineAuditRequest

            include_metrics = params.get("include_metrics", True)
            response = await self._stub.EngineAudit(
                EngineAuditRequest(include_metrics=include_metrics),
                timeout=timeout,
            )
            return {
                "success": response.success,
                "observations_recorded": response.observations_recorded,
                "anomalies_found": response.anomalies_found,
                "duration_ms": response.duration_ms,
                "error": response.error or None,
                "anomaly_details": list(response.anomaly_details),
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
            response = await self._stub.BeginWorkload(request, timeout=timeout)
            result = MessageToDict(response, preserving_proto_field_name=True)
            return result

        elif action == "complete":
            request = CompleteWorkloadRequest(
                workload_id=params.get("workload_id", ""),
            )
            await self._stub.CompleteWorkload(request, timeout=timeout)
            return {"success": True}

        elif action == "active":
            response = await self._stub.GetActiveWorkloads(
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
            response = await self._stub.EmbedTexts(request, timeout=timeout)

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
            response = await self._stub.SemanticSearch(request, timeout=timeout)

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
        """Handle Gaius-specific service calls (MetaAgent, ThetaAgent, etc.)."""
        from ..engine.generated import (
            MetaAgentQueryRequest,
            ThetaSitrepRequest,
            ThetaConsolidateRequest,
            ThetaConsolidationStatsRequest,
            ThetaAgendaRequest,
            AgendaListRequest,
            AgendaGetRequest,
            AgendaCreateRequest,
            AgendaUpdateRequest,
            AgendaCheck,
            WeeklySignalsSummaryRequest,
            WeeklySignalsSummaryListRequest,
            WeeklySignalsSummaryGetRequest,
            KnowledgeSummaryRequest,
            FederationSurfacesRequest,
            AskPresentRequest,
            FmpNewsRequest,
            FmpSearchRequest,
            SummaryIndexRequest,
            SummaryGetRequest,
            SummaryHopRequest,
            SummaryForkRequest,
            SummarySchedulesRequest,
            SummaryScheduleTriggerRequest,
        )

        def _card(c: object) -> dict:
            if c is None:
                return {}
            return {
                "path": getattr(c, "path", ""),
                "kind": getattr(c, "kind", ""),
                "title": getattr(c, "title", ""),
                "body": getattr(c, "body", ""),
                "excerpt": getattr(c, "excerpt", ""),
                "prev": getattr(c, "prev", ""),
                "next": getattr(c, "next", ""),
                "starts": getattr(c, "starts", ""),
                "ends": getattr(c, "ends", ""),
                "tags": list(getattr(c, "tags", [])),
                "pin": bool(getattr(c, "pin", False)),
                "checks": [
                    {"done": ch.done, "text": ch.text}
                    for ch in getattr(c, "checks", [])
                ],
                "created_ms": getattr(c, "created_ms", 0),
                "intent": getattr(c, "intent", ""),
                "with": getattr(c, "with_whom", ""),
                "calendar_url": getattr(c, "calendar_url", ""),
                "timezone": getattr(c, "timezone", ""),
            }

        if action == "AgendaList":
            response = await self._stub.AgendaList(
                AgendaListRequest(
                    window_days=int(params.get("window_days") or 14),
                    kind=str(params.get("kind") or ""),
                    tag=str(params.get("tag") or ""),
                    origin=str(params.get("origin") or ""),
                    timezone=str(params.get("timezone") or ""),
                ),
                timeout=timeout,
            )
            if response.error:
                return {"error": response.error}
            return {"items": [_card(i) for i in response.items]}

        if action == "AgendaGet":
            response = await self._stub.AgendaGet(
                AgendaGetRequest(path=str(params.get("path") or "")),
                timeout=timeout,
            )
            if response.error:
                return {"error": response.error}
            return {"item": _card(response.item)}

        if action == "AgendaCreate":
            response = await self._stub.AgendaCreate(
                AgendaCreateRequest(
                    kind=str(params.get("kind") or "note"),
                    title=str(params.get("title") or ""),
                    body=str(params.get("body") or ""),
                    starts=str(params.get("starts") or ""),
                    ends=str(params.get("ends") or ""),
                    tags=list(params.get("tags") or []),
                    pin=bool(params.get("pin") or False),
                    intent=str(params.get("intent") or ""),
                    with_whom=str(params.get("with") or params.get("with_whom") or ""),
                    timezone=str(params.get("timezone") or ""),
                ),
                timeout=timeout,
            )
            if response.error:
                return {"error": response.error}
            return {"item": _card(response.item)}

        if action == "AgendaUpdate":
            checks_in = params.get("checks")
            req = AgendaUpdateRequest(
                path=str(params.get("path") or ""),
                title=str(params.get("title") or ""),
                body=str(params.get("body") or ""),
                starts=str(params.get("starts") or ""),
                ends=str(params.get("ends") or ""),
                tags=list(params.get("tags") or []),
                pin=bool(params.get("pin") or False),
                has_pin="pin" in params,
                has_checks=checks_in is not None,
                intent=str(params.get("intent") or ""),
                has_intent="intent" in params,
                with_whom=str(params.get("with") or params.get("with_whom") or ""),
                has_with="with" in params or "with_whom" in params,
                timezone=str(params.get("timezone") or ""),
                has_timezone="timezone" in params,
            )
            if checks_in is not None:
                req.checks.extend(
                    AgendaCheck(done=bool(c.get("done")), text=str(c.get("text", "")))
                    for c in checks_in
                )
            response = await self._stub.AgendaUpdate(req, timeout=timeout)
            if response.error:
                return {"error": response.error}
            return {"item": _card(response.item)}

        if action == "WeeklySignalsSummary":
            response = await self._stub.WeeklySignalsSummary(
                WeeklySignalsSummaryRequest(
                    week=str(params.get("week") or ""),
                    previous=bool(params.get("previous") or False),
                ),
                timeout=timeout,
            )
            if response.error:
                return {"error": response.error}
            return {
                "path": response.path,
                "week": response.week,
                "body": response.body,
                "projects": list(response.projects),
                "remotes": [
                    {"project": r.project, "name": r.name, "url": r.url}
                    for r in response.remotes
                ],
                "acp_used": response.acp_used,
            }

        if action == "WeeklySignalsSummaryList":
            response = await self._stub.WeeklySignalsSummaryList(
                WeeklySignalsSummaryListRequest(limit=int(params.get("limit") or 12)),
                timeout=timeout,
            )
            if response.error:
                return {"error": response.error}
            return {
                "items": [
                    {"path": i.path, "week": i.week, "title": i.title}
                    for i in response.items
                ]
            }

        if action == "WeeklySignalsSummaryGet":
            response = await self._stub.WeeklySignalsSummaryGet(
                WeeklySignalsSummaryGetRequest(path=str(params.get("path") or "")),
                timeout=timeout,
            )
            if response.error:
                return {"error": response.error}
            return {"path": response.path, "body": response.body}

        if action == "KnowledgeSummary":
            response = await self._stub.KnowledgeSummary(
                KnowledgeSummaryRequest(
                    week=str(params.get("week") or ""),
                    section=str(params.get("section") or ""),
                ),
                timeout=timeout,
            )
            if response.error:
                return {"error": response.error}
            return {
                "week": response.week,
                "items": [
                    {"section": i.section, "path": i.path, "notes": i.notes}
                    for i in response.items
                ],
            }

        if action == "FederationSurfaces":
            response = await self._stub.FederationSurfaces(
                FederationSurfacesRequest(),
                timeout=timeout,
            )
            if response.error:
                return {"error": response.error}
            return {
                "items": [
                    {
                        "project": i.project,
                        "engine_target": i.engine_target,
                        "primary_ui": i.primary_ui,
                    }
                    for i in response.items
                ]
            }

        if action == "FmpNews":
            response = await self._stub.FmpNews(
                FmpNewsRequest(
                    kind=str(params.get("kind") or "stock"),
                    symbol=str(params.get("symbol") or ""),
                    limit=int(params.get("limit") or 15),
                ),
                timeout=timeout,
            )
            if response.error:
                return {"error": response.error}
            import json as _json

            try:
                items = _json.loads(response.items_json or "[]")
            except _json.JSONDecodeError:
                items = []
            return {"items": items}

        if action == "FmpSearch":
            response = await self._stub.FmpSearch(
                FmpSearchRequest(
                    query=str(params.get("query") or ""),
                    limit=int(params.get("limit") or 8),
                ),
                timeout=timeout,
            )
            if response.error:
                return {"error": response.error}
            import json as _json

            try:
                items = _json.loads(response.items_json or "[]")
            except _json.JSONDecodeError:
                items = []
            return {"items": items}

        if action == "AskPresent":
            response = await self._stub.AskPresent(
                AskPresentRequest(
                    kind=str(params.get("kind") or "ohlc"),
                    symbol=str(params.get("symbol") or ""),
                    title=str(params.get("title") or ""),
                    from_date=str(params.get("from_date") or ""),
                    to_date=str(params.get("to_date") or ""),
                    payload_json=str(params.get("payload_json") or params.get("bars") or ""),
                ),
                timeout=timeout,
            )
            if response.error:
                return {"error": response.error}
            import json as _json

            try:
                artifact = _json.loads(response.artifact_json or "{}")
            except _json.JSONDecodeError:
                artifact = {}
            return {
                "artifact": artifact,
                "n_items": response.n_items,
            }

        if action == "SummaryIndex":
            response = await self._stub.SummaryIndex(
                SummaryIndexRequest(
                    section=str(params.get("section") or ""),
                    lens=str(params.get("lens") or ""),
                    week=str(params.get("week") or ""),
                    limit=int(params.get("limit") or 48),
                ),
                timeout=timeout,
            )
            if response.error:
                return {"error": response.error}

            def _sn(n: object) -> dict:
                if n is None:
                    return {}
                return {
                    "id": getattr(n, "id", ""),
                    "title": getattr(n, "title", ""),
                    "body": getattr(n, "body", ""),
                    "section": getattr(n, "section", ""),
                    "lens": getattr(n, "lens", ""),
                    "week": getattr(n, "week", ""),
                    "mtime_ms": getattr(n, "mtime_ms", 0),
                    "links": list(getattr(n, "links", [])),
                    "origin_project": getattr(n, "origin_project", ""),
                    "origin_id": getattr(n, "origin_id", ""),
                    "excerpt": getattr(n, "excerpt", ""),
                    "virtual": bool(getattr(n, "virtual", False)),
                }

            return {
                "week": response.week,
                "landing_id": response.landing_id,
                "seed": _sn(response.seed),
                "items": [_sn(i) for i in response.items],
            }

        if action == "SummaryGet":
            response = await self._stub.SummaryGet(
                SummaryGetRequest(
                    id=str(params.get("id") or params.get("path") or ""),
                    section=str(params.get("section") or ""),
                    lens=str(params.get("lens") or ""),
                    week=str(params.get("week") or ""),
                ),
                timeout=timeout,
            )
            if response.error:
                return {"error": response.error}
            n = response.note
            return {
                "id": n.id,
                "title": n.title,
                "body": n.body,
                "section": n.section,
                "lens": n.lens,
                "week": n.week,
                "mtime_ms": n.mtime_ms,
                "links": list(n.links),
                "origin_project": n.origin_project,
                "origin_id": n.origin_id,
                "excerpt": n.excerpt,
                "virtual": n.virtual,
            }

        if action == "SummaryHop":
            response = await self._stub.SummaryHop(
                SummaryHopRequest(
                    from_id=str(params.get("from_id") or ""),
                    target=str(params.get("target") or ""),
                    section=str(params.get("section") or ""),
                    lens=str(params.get("lens") or ""),
                    week=str(params.get("week") or ""),
                ),
                timeout=timeout,
            )
            if response.error:
                return {"error": response.error}
            n = response.note
            return {
                "resolved_id": response.resolved_id,
                "id": n.id,
                "title": n.title,
                "body": n.body,
                "links": list(n.links),
                "excerpt": n.excerpt,
            }

        if action == "SummaryFork":
            response = await self._stub.SummaryFork(
                SummaryForkRequest(
                    id=str(params.get("id") or ""),
                    origin_project=str(params.get("origin_project") or ""),
                ),
                timeout=timeout,
            )
            if response.error:
                return {"error": response.error}
            n = response.note
            return {
                "id": n.id,
                "title": n.title,
                "body": n.body,
                "origin_project": n.origin_project,
                "origin_id": n.origin_id,
            }

        if action == "SummarySchedules":
            response = await self._stub.SummarySchedules(
                SummarySchedulesRequest(), timeout=timeout
            )
            if response.error:
                return {"error": response.error}
            return {
                "items": [
                    {
                        "id": i.id,
                        "cron": i.cron,
                        "task_type": i.task_type,
                        "source": i.source,
                        "enabled": i.enabled,
                        "triggerable": i.triggerable,
                        "cadence": i.cadence,
                    }
                    for i in response.items
                ]
            }

        if action == "SummaryScheduleTrigger":
            response = await self._stub.SummaryScheduleTrigger(
                SummaryScheduleTriggerRequest(id=str(params.get("id") or "")),
                timeout=timeout,
            )
            if response.error:
                return {"error": response.error}
            return {"task_id": response.task_id, "task_type": response.task_type}

        if action == "ThetaAgenda":
            request = ThetaAgendaRequest(
                action=params.get("action", "list"),
                horizon=params.get("horizon", "day"),
            )
            response = await self._stub.ThetaAgenda(request, timeout=timeout)
            return {
                "success": response.success,
                "action": response.action,
                "horizon": response.horizon,
                "path": response.path,
                "created": response.created,
                "items": [
                    {
                        "description": i.description,
                        "priority": i.priority,
                        "project": i.project,
                        "due_date": i.due_date,
                        "completed": i.completed,
                        "source_path": i.source_path,
                    }
                    for i in response.items
                ],
                "ascii_format": response.ascii_format,
                "error": response.error,
            }

        if action == "ThetaSitrep":
            request = ThetaSitrepRequest(
                horizon=params.get("horizon", "day"),
            )
            response = await self._stub.ThetaSitrep(request, timeout=timeout)
            # Parse report_json if available for detailed data
            import json
            report_data = {}
            if response.report_json:
                try:
                    report_data = json.loads(response.report_json.decode())
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
            return {
                "success": response.success,
                "horizon": response.horizon,
                "healthy": response.healthy,
                "status_text": response.status_text,
                "gpu_count": response.gpu_count,
                "endpoint_count": response.endpoint_count,
                "priority_count": response.priority_count,
                "thought_count": response.thought_count,
                "objective_count": response.objective_count,
                "project_count": response.project_count,
                "ascii_format": response.ascii_format,
                "report": report_data,
                "error": response.error,
            }

        elif action == "ThetaConsolidate":
            request = ThetaConsolidateRequest(
                temporal_slice=params.get("temporal_slice", ""),
                max_candidates=params.get("max_candidates", 10),
                research_mode=params.get("research_mode", True),
            )
            response = await self._stub.ThetaConsolidate(request, timeout=timeout)
            return {
                "success": response.success,
                "slice_id": response.slice_id,
                "urgency": response.urgency,
                "drift": response.drift,
                "candidates_evaluated": response.candidates_evaluated,
                "candidates_selected": response.candidates_selected,
                "documents_augmented": response.documents_augmented,
                "error": response.error,
                "guru_meditation": response.guru_meditation,
            }

        elif action == "ThetaConsolidationStats":
            request = ThetaConsolidationStatsRequest()
            response = await self._stub.ThetaConsolidationStats(
                request, timeout=timeout
            )
            return {
                "dynamics": {
                    "k": response.nvar_k,
                    "polynomial_order": response.nvar_order,
                    "slice_count": response.slice_count,
                    "can_predict": response.can_predict,
                },
                "kg_policy": {
                    "research_mode": response.research_mode,
                    "measurement_cost": response.measurement_cost,
                    "belief_state": {
                        "n_measurements": response.n_measurements,
                        "current_best": response.current_best_value,
                    },
                },
                "effectiveness": {
                    "history_length": response.effectiveness_history_length,
                    "trend": {
                        "trend": response.effectiveness_trend,
                        "mean_contribution": response.mean_contribution,
                    },
                },
                "subsumption": {
                    "confidence_threshold": response.confidence_threshold,
                    "template_type": response.template_type,
                    "classifier_loaded": response.classifier_loaded,
                },
            }

        elif action == "MetaAgentQuery":
            request = MetaAgentQueryRequest(
                query=params.get("query", ""),
                domains=params.get("domains", []),
                include_dot=params.get("include_dot", True),
                include_markdown=params.get("include_markdown", True),
                max_agents=params.get("max_agents", 5),
            )
            response = await self._stub.MetaAgentQuery(request, timeout=timeout)

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

    async def _call_clt(self, action: str, params: dict, timeout: float) -> dict:
        """Handle CLT (Cross-Layer Transcoders) service calls.

        CLT provides interpretable sparse feature extraction and attribution
        graphs for circuit tracing via BluelightAI's circuit-tracer library.

        Args:
            action: Action to perform (status, extract, attribute)
            params: Action parameters
            timeout: Request timeout

        Returns:
            Result dict with sparse features or attribution edges
        """
        from ..engine.generated import (
            CLTStatusRequest,
            CLTExtractRequest,
            CLTAttributeRequest,
        )

        if action == "status":
            request = CLTStatusRequest()
            response = await self._stub.CLTStatus(request, timeout=timeout)
            return {
                "available": response.available,
                "models": list(response.models),
                "loaded_model": response.loaded_model,
                "features_per_layer": response.features_per_layer,
                "l0_sparsity": response.l0_sparsity,
                "error": response.error,
            }

        elif action == "extract":
            request = CLTExtractRequest(
                text=params.get("text", ""),
                model_name=params.get("model_name", "qwen3-1.7b"),
                layer_indices=params.get("layer_indices", []),
                top_k=params.get("top_k", 115),
                device=params.get("device", "cuda"),
            )
            response = await self._stub.CLTExtract(request, timeout=timeout)

            # Convert proto features to dicts
            features = [
                {
                    "layer_idx": f.layer_idx,
                    "position": f.position,
                    "feature_idx": f.feature_idx,
                    "activation": f.activation,
                    "semantic_label": f.semantic_label,
                }
                for f in response.features
            ]

            return {
                "success": response.success,
                "features": features,
                "total_positions": response.total_positions,
                "sparsity": response.sparsity,
                "text": params.get("text", ""),  # Echo back input text
                "error": response.error,
            }

        elif action == "attribute":
            request = CLTAttributeRequest(
                text=params.get("text", ""),
                model_name=params.get("model_name", "qwen3-1.7b"),
                target_positions=params.get("target_positions", []),
                threshold=params.get("threshold", 0.01),
                device=params.get("device", "cuda"),
            )
            response = await self._stub.CLTAttribute(request, timeout=timeout)

            # Convert proto edges to dicts
            edges = [
                {
                    "source_layer": e.source_layer,
                    "source_feature": e.source_feature,
                    "target_layer": e.target_layer,
                    "target_feature": e.target_feature,
                    "weight": e.weight,
                }
                for e in response.edges
            ]

            return {
                "success": response.success,
                "edges": edges,
                "dot_graph": response.dot_graph,
                "text": params.get("text", ""),  # Echo back input text
                "target_positions": params.get("target_positions", []),  # Echo back input
                "error": response.error,
            }

        else:
            raise ValueError(f"Unknown CLT action: {action}")

    async def _call_health_observer(
        self, action: str, params: dict, timeout: float
    ) -> dict:
        """Handle HealthObserver service calls via gRPC.

        HealthObserver provides autonomous FMEA-based health monitoring
        with tiered remediation and ACP escalation for complex issues.

        Args:
            action: Action to perform (status, start, stop, incidents, check, incident_detail)
            params: Action parameters
            timeout: Request timeout

        Returns:
            Result dict with status, incidents, or health check results
        """
        if action == "status":
            request = HealthObserverStatusRequest()
            response = await self._stub.HealthObserverStatus(
                request, timeout=timeout
            )
            return {
                "running": response.running,
                "enabled": response.enabled,
                "poll_count": response.poll_count,
                "last_poll_at": response.last_poll_at or None,
                "poll_interval": response.config.poll_interval if response.config else 30,
                "escalate_to_acp": response.config.escalate_to_acp if response.config else True,
                "github_repo": response.config.github_repo if response.config else "",
                "incidents_created": response.metrics.incidents_created if response.metrics else 0,
                "incidents_resolved": response.metrics.incidents_resolved if response.metrics else 0,
                "acp_escalations": response.metrics.acp_escalations if response.metrics else 0,
                "active_incident_count": response.active_incidents,
                "incidents": [
                    {
                        "incident_id": inc.incident_id,
                        "fingerprint": inc.fingerprint,
                        "endpoint": inc.endpoint,
                        "failure_mode_id": inc.failure_mode_id,
                        "rpn_score": inc.rpn_score,
                        "current_tier": inc.current_tier,
                        "attempts": inc.attempts,
                        "status": inc.status,
                        "created_at": inc.created_at,
                        "github_issue": inc.github_issue if inc.github_issue else None,
                    }
                    for inc in response.incidents
                ],
            }

        elif action == "start":
            response = await self._stub.HealthObserverStart(
                empty_pb2.Empty(), timeout=timeout
            )
            return {
                "status": "started" if response.running else "already_running",
                "poll_interval": response.config.poll_interval if response.config else 30,
                "escalate_to_acp": response.config.escalate_to_acp if response.config else True,
            }

        elif action == "stop":
            response = await self._stub.HealthObserverStop(
                empty_pb2.Empty(), timeout=timeout
            )
            return {
                "status": "stopped",
                "active_incidents": response.active_incidents,  # Already an int count
            }

        elif action == "incidents":
            status_filter = params.get("status", "active")
            request = ListIncidentsRequest(status=status_filter)
            response = await self._stub.HealthObserverListIncidents(
                request, timeout=timeout
            )
            return {
                "status_filter": status_filter,
                "count": len(response.incidents),
                "incidents": [
                    {
                        "incident_id": inc.incident_id,
                        "fingerprint": inc.fingerprint,
                        "endpoint": inc.endpoint,
                        "failure_mode_id": inc.failure_mode_id,
                        "rpn_score": inc.rpn_score,
                        "current_tier": inc.current_tier,
                        "attempts": inc.attempts,
                        "status": inc.status,
                        "created_at": inc.created_at,
                        "github_issue": inc.github_issue if inc.github_issue else None,
                    }
                    for inc in response.incidents
                ],
            }

        elif action == "check":
            import json

            request = ForceHealthCheckRequest()
            response = await self._stub.HealthObserverForceCheck(
                request, timeout=timeout
            )
            # Parse check details from proto messages
            checks = []
            for check in response.checks:
                checks.append({
                    "name": check.name,
                    "status": check.status,
                    "message": check.message,
                    "heuristic_id": check.heuristic_id,
                    "details": json.loads(check.details_json) if check.details_json else {},
                })
            return {
                "healthy": response.healthy,
                "summary": response.summary,
                "passed": response.passed,
                "warnings": response.warnings,
                "failures": response.failures,
                "new_incidents": response.new_incidents,
                "checks": checks,
            }

        elif action == "incident_detail":
            fingerprint = params.get("fingerprint", "")
            request = GetIncidentDetailRequest(fingerprint=fingerprint)
            response = await self._stub.HealthObserverGetIncident(
                request, timeout=timeout
            )
            if not response.found:
                return {
                    "error": f"Incident not found: {fingerprint}",
                }
            inc = response.incident
            return {
                "incident": {
                    "incident_id": inc.incident_id,
                    "fingerprint": inc.fingerprint,
                    "endpoint": inc.endpoint,
                    "failure_mode_id": inc.failure_mode_id,
                    "rpn_score": inc.rpn_score,
                    "rpn_severity": inc.rpn_severity,
                    "rpn_occurrence": inc.rpn_occurrence,
                    "rpn_detection": inc.rpn_detection,
                    "current_tier": inc.current_tier,
                    "sequence_id": inc.sequence_id,
                    "created_at": inc.created_at,
                    "last_check_at": inc.last_check_at,
                    "attempts": inc.attempts,
                    "github_issue": inc.github_issue,
                    "status": inc.status,
                },
            }

        elif action == "resolve_incident":
            fingerprint = params.get("fingerprint", "")
            request = ResolveIncidentRequest(fingerprint=fingerprint)
            response = await self._stub.HealthObserverResolveIncident(
                request, timeout=timeout
            )
            return {
                "resolved": response.resolved,
                "fingerprint": response.fingerprint,
                "was_active": response.was_active,
                "note": response.note or None,
            }

        elif action == "get_orphaned_issues":
            request = GetOrphanedIssuesRequest()
            response = await self._stub.HealthObserverGetOrphanedIssues(
                request, timeout=timeout
            )
            return {
                "orphans": [
                    {
                        "issue_number": orphan.issue_number,
                        "repo": orphan.repo,
                        "fingerprint": orphan.fingerprint,
                        "created_at": orphan.created_at or None,
                        "issue_url": orphan.issue_url or None,
                    }
                    for orphan in response.orphans
                ],
            }

        else:
            raise ValueError(f"Unknown HealthObserver action: {action}")

    async def _call_observe(
        self, action: str, params: dict, timeout: float
    ) -> dict:
        """Handle Observe service calls via gRPC.

        Provides observability dashboard data, aggregating metrics from
        Prometheus and engine state for CLI /observe command.

        Args:
            action: Action to perform (status)
            params: Action parameters (include_sparklines, sparkline_points)
            timeout: Request timeout

        Returns:
            Result dict with metrics, endpoints, and health summary
        """
        if action == "status":
            include_sparklines = params.get("include_sparklines", False)
            sparkline_points = params.get("sparkline_points", 20)

            request = ObserveStatusRequest(
                include_sparklines=include_sparklines,
                sparkline_points=sparkline_points,
            )
            response = await self._stub.ObserveStatus(
                request, timeout=timeout
            )
            return {
                "timestamp": response.timestamp,
                "prometheus_available": response.prometheus_available,
                "metrics": [
                    {
                        "name": m.name,
                        "display_name": m.display_name,
                        "current_value": m.current_value,
                        "unit": m.unit,
                        "sparkline_data": list(m.sparkline_data) if m.sparkline_data else [],
                        "status": m.status,
                    }
                    for m in response.metrics
                ],
                "endpoints": [
                    {
                        "name": ep.name,
                        "status": ep.status,
                        "gpus": list(ep.gpus) if ep.gpus else [],
                        "model": ep.model,
                    }
                    for ep in response.endpoints
                ],
                "healthy_endpoints": response.healthy_endpoints,
                "unhealthy_endpoints": response.unhealthy_endpoints,
                "active_incidents": response.active_incidents,
                "evolution_cycles": response.evolution_cycles,
            }

        else:
            raise ValueError(f"Unknown Observe action: {action}")

    async def _call_signals_telemetry(
        self, action: str, params: dict, timeout: float
    ) -> dict:
        if action not in ("snapshot", "status", ""):
            raise ValueError(f"Unknown SignalsTelemetry action: {action}")
        response = await self._stub.SignalsTelemetry(
            SignalsTelemetryRequest(), timeout=timeout
        )
        if response.error:
            return {"error": response.error}
        return {
            "source_url": response.source_url,
            "scraped_at": response.scraped_at,
            "total_w": response.total_w,
            "parked_w": response.parked_w,
            "inferring_w": response.inferring_w,
            "gpus": [
                {
                    "index": g.index,
                    "uuid": g.uuid,
                    "model": g.model,
                    "power_w": g.power_w,
                    "util": g.util,
                    "memory_used_mib": g.memory_used_mib,
                    "memory_free_mib": g.memory_free_mib,
                    "energy_mj": g.energy_mj,
                    "temp_c": g.temp_c,
                }
                for g in response.gpus
            ],
        }

    async def _call_x_bookmarks(
        self, action: str, params: dict, timeout: float
    ) -> dict:
        """Handle X Bookmarks service calls via gRPC.

        X Bookmarks provides sync of X/Twitter bookmarks to Gaius KB
        with OAuth 2.0 PKCE authentication and rate limiting.

        Args:
            action: Action to perform (get_auth_url, complete_auth, auth_status, trigger_sync, sync_status, service_status)
            params: Action parameters
            timeout: Request timeout

        Returns:
            Result dict with auth info, sync status, or service status
        """
        if action == "get_auth_url":
            request = XBookmarksAuthRequest()
            response = await self._stub.XBookmarksGetAuthUrl(
                request, timeout=timeout
            )
            return {
                "auth_url": response.auth_url,
                "state": response.state,
                "verifier": response.verifier,
            }

        elif action == "complete_auth":
            code = params.get("code", "")
            verifier = params.get("verifier", "")
            request = XBookmarksCompleteAuthRequest(code=code, verifier=verifier)
            response = await self._stub.XBookmarksCompleteAuth(
                request, timeout=timeout
            )
            return {
                "success": response.success,
                "message": response.message,
            }

        elif action == "auth_status":
            request = XBookmarksAuthStatusRequest()
            response = await self._stub.XBookmarksAuthStatus(
                request, timeout=timeout
            )
            result = {
                "authenticated": response.authenticated,
                "user_id": response.user_id,
                "username": response.username,
                "expires_at": response.expires_at,
                "scopes": list(response.scopes),
                "error": response.error if response.error else None,
                "guru_code": response.guru_code if response.guru_code else None,
            }
            # Add guidance fields if present
            if response.action_required:
                result["action_required"] = response.action_required
            if response.guidance_message:
                result["message"] = response.guidance_message
            return result

        elif action == "trigger_sync":
            full_sync = params.get("full_sync", False)
            folder_id = params.get("folder_id", "")
            request = XBookmarksSyncRequest(full_sync=full_sync, folder_id=folder_id)
            response = await self._stub.XBookmarksTriggerSync(
                request, timeout=timeout
            )
            result = {
                "started": response.started,
                "run_id": response.run_id,
                "message": response.message,
                # Extended fields for detailed sync results
                "status": response.status,
                "bookmarks_fetched": response.bookmarks_fetched,
                "iceberg_written": response.iceberg_written,
                "queue_items": response.queue_items,
            }
            # Add guidance fields if present
            if response.action_required:
                result["action_required"] = response.action_required
            if response.guidance_message:
                result["guidance_message"] = response.guidance_message
            return result

        elif action == "sync_status":
            user_id = params.get("user_id", "")
            request = XBookmarksSyncStatusRequest(user_id=user_id)
            response = await self._stub.XBookmarksSyncStatus(
                request, timeout=timeout
            )
            result = {
                "configured": response.configured,
                "user_id": response.user_id,
                "username": response.username,
                "token_status": response.token_status,
                "folder_count": response.folder_count,
                "bookmark_count": response.bookmark_count,
                "queued_requests": response.queued_requests,
                "last_sync_at": response.last_sync_at,
                "last_run_status": response.last_run_status,
            }
            # Add guidance fields if present
            if response.action_required:
                result["action_required"] = response.action_required
            if response.guidance_message:
                result["message"] = response.guidance_message
            return result

        elif action == "service_status":
            request = XBookmarksServiceStatusRequest()
            response = await self._stub.XBookmarksServiceStatus(
                request, timeout=timeout
            )
            return {
                "running": response.running,
                "total_syncs": response.total_syncs,
                "total_bookmarks": response.total_bookmarks,
                "last_sync_at": response.last_sync_at,
                "queue_poll_interval_s": response.queue_poll_interval_s,
            }

        elif action == "list_folders":
            user_id = params.get("user_id", "")
            request = XBookmarksListFoldersRequest(user_id=user_id)
            response = await self._stub.XBookmarksListFolders(
                request, timeout=timeout
            )
            return {
                "folders_available": response.folders_available,
                "folders": [
                    {
                        "id": f.id,
                        "name": f.name,
                        "kb_path": f.kb_path,
                        "bookmark_count": f.bookmark_count,
                    }
                    for f in response.folders
                ],
                "message": response.message,
            }

        elif action == "queue_status":
            request = XBookmarksQueueStatusRequest()
            response = await self._stub.XBookmarksQueueStatus(
                request, timeout=timeout
            )
            return {
                "queue_depth": response.queue_depth,
                "cooldown_end_iso": response.cooldown_end_iso,
                "cooldown_seconds": response.cooldown_seconds,
                "can_request": response.can_request,
            }

        elif action == "emit_test_event":
            event_type = params.get("event_type", "XB_AUTH_COMPLETED")
            request = XBookmarksEmitTestEventRequest(event_type=event_type)
            response = await self._stub.XBookmarksEmitTestEvent(
                request, timeout=timeout
            )
            return {
                "success": response.success,
                "event_type": response.event_type,
                "message": response.message,
            }

        else:
            raise ValueError(f"Unknown XBookmarks action: {action}")

    async def _call_ambient(self, action: str, params: dict, timeout: float) -> dict:
        """Handle Ambient Computing service calls via gRPC.

        Ambient Computing provides invisible, self-sustaining workloads that
        maintain baseline endpoints and exercise GPU resources.

        Args:
            action: Action to perform (status, cycle)
            params: Action parameters
            timeout: Request timeout

        Returns:
            Result dict with status or cycle results
        """
        if action == "status":
            response = await self._stub.AmbientStatus(
                empty_pb2.Empty(), timeout=timeout
            )
            # Map the proto field name to a friendlier name for CLI
            current_phase_value = response.current_phase
            # Get phase name from proto enum
            phase_name = "IDLE"
            try:
                from ..engine.generated import AmbientPhase
                phase_name = AmbientPhase.Name(current_phase_value)
            except Exception:
                phase_name = str(current_phase_value)

            return {
                "running": response.cycle_running,
                "current_phase": phase_name,
                "last_cycle_at": response.last_cycle_timestamp_ms,
                "cycles_completed": response.cycles_completed,
                "baseline_endpoints": list(response.baseline_endpoints),
                "reasoning_endpoint": response.reasoning_endpoint,
                # Daemon mode fields
                "daemon_running": response.daemon_running,
                "current_cycle": response.current_cycle,
                "max_cycles": response.max_cycles,
                "daemon_started_at": response.daemon_started_at_ms,
                "daemon_stopped_at": response.daemon_stopped_at_ms,
            }

        elif action == "start":
            # Start ambient daemon
            baseline_only = params.get("baseline_only", False)
            max_cycles = params.get("max_cycles", 0)

            request = AmbientStartRequest(
                baseline_only=baseline_only,
                max_cycles=max_cycles,
            )

            response = await self._stub.AmbientStart(request, timeout=timeout)

            return {
                "success": response.success,
                "message": response.message,
                "max_cycles": response.max_cycles,
            }

        elif action == "stop":
            # Stop ambient daemon
            request = AmbientStopRequest()
            response = await self._stub.AmbientStop(request, timeout=timeout)

            return {
                "success": response.success,
                "message": response.message,
                "cycles_completed": response.cycles_completed,
            }

        elif action == "cycle":
            # For non-streaming cycle, collect all events and return final result
            from ..engine.generated import AmbientPhase

            skip_reasoning = params.get("skip_reasoning", False)
            baseline_task_count = params.get("baseline_task_count", 1)
            reasoning_prompt = params.get("reasoning_prompt", "")

            request = AmbientCycleRequest(
                skip_reasoning=skip_reasoning,
                baseline_task_count=baseline_task_count,
                reasoning_prompt=reasoning_prompt,
            )

            events = []
            final_result = {}
            async for event in self._stub.AmbientCycle(request, timeout=timeout):
                # Get phase name from enum
                try:
                    phase_name = AmbientPhase.Name(event.phase)
                except Exception:
                    phase_name = str(event.phase)

                # Extract metrics from the map field
                metrics = dict(event.metrics) if event.metrics else {}

                event_dict = {
                    "phase": phase_name,
                    "message": event.message,
                    "progress": event.progress,
                    "metrics": metrics,
                    "timestamp_ms": event.timestamp_ms,
                    # Derived fields for CLI display
                    "endpoint": metrics.get("endpoint", ""),
                    "success": "error" not in event.message.lower(),
                    "latency_ms": int(metrics.get("latency_ms", 0)) if metrics.get("latency_ms") else 0,
                }
                events.append(event_dict)

                # Check if this is a terminal phase
                if phase_name in ("AMBIENT_PHASE_COMPLETE", "AMBIENT_PHASE_ERROR"):
                    final_result = event_dict

            return {
                "events": events,
                "final": final_result,
                "total_events": len(events),
            }

        elif action == "buffer_export":
            # Export buffer to zettelkasten file
            from ..engine.generated import AmbientBufferExportRequest

            kb_root = params.get("kb_root", "build/dev")
            request = AmbientBufferExportRequest(kb_root=kb_root)
            response = await self._stub.AmbientBufferExport(request, timeout=timeout)

            return {
                "path": response.path,
                "entry_count": response.entry_count,
                "total_bytes": response.total_bytes,
                "error": response.error if response.error else None,
            }

        else:
            raise ValueError(f"Unknown Ambient action: {action}")

    async def ambient_cycle_stream(
        self,
        skip_reasoning: bool = False,
        baseline_task_count: int = 1,
        reasoning_prompt: str = "",
    ) -> AsyncIterator[dict]:
        """Stream ambient cycle progress events.

        Executes a full ambient computing cycle with real-time progress updates.
        Use this for CLI/TUI progress display.

        Args:
            skip_reasoning: Skip reasoning phase (baseline-only test)
            baseline_task_count: Number of tasks per baseline endpoint
            reasoning_prompt: Custom reasoning prompt (optional)

        Yields:
            AmbientPhaseEvent dicts with phase, endpoint, message, progress, success
        """
        if not self._connected:
            await self.connect()

        request = AmbientCycleRequest(
            skip_reasoning=skip_reasoning,
            baseline_task_count=baseline_task_count,
            reasoning_prompt=reasoning_prompt,
        )

        try:
            from ..engine.generated import AmbientPhase

            async for event in self._stub.AmbientCycle(request):
                # Get phase name from enum
                try:
                    phase_name = AmbientPhase.Name(event.phase)
                except Exception:
                    phase_name = str(event.phase)

                # Extract metrics from the map field
                metrics = dict(event.metrics) if event.metrics else {}

                yield {
                    "phase": phase_name,
                    "message": event.message,
                    "progress": event.progress,
                    "metrics": metrics,
                    "timestamp_ms": event.timestamp_ms,
                    # Derived fields for CLI display
                    "endpoint": metrics.get("endpoint", ""),
                    "success": "error" not in event.message.lower(),
                    "latency_ms": int(metrics.get("latency_ms", 0)) if metrics.get("latency_ms") else 0,
                }
        except grpc.RpcError as e:
            if e.code() != grpc.StatusCode.CANCELLED:
                logger.error(f"AmbientCycle error: {e}")
                yield {
                    "phase": "AMBIENT_PHASE_ERROR",
                    "message": f"Stream error: {e.details()}",
                    "progress": 0.0,
                    "success": False,
                    "endpoint": "",
                    "latency_ms": 0,
                    "metrics": {},
                    "timestamp_ms": 0,
                }

    async def ambient_subscribe_stream(self) -> AsyncIterator[dict]:
        """Subscribe to ambient daemon events stream.

        Yields events from a running ambient daemon.
        Used by TUI to display progress while daemon runs.

        Yields:
            AmbientPhaseEvent dicts with phase, message, progress, metrics
        """
        if not self._connected:
            await self.connect()

        request = AmbientSubscribeRequest()

        try:
            from ..engine.generated import AmbientPhase

            async for event in self._stub.AmbientSubscribe(request):
                # Get phase name from enum
                try:
                    phase_name = AmbientPhase.Name(event.phase)
                except Exception:
                    phase_name = str(event.phase)

                # Extract metrics from the map field
                metrics = dict(event.metrics) if event.metrics else {}

                yield {
                    "phase": phase_name,
                    "message": event.message,
                    "progress": event.progress,
                    "metrics": metrics,
                    "timestamp_ms": event.timestamp_ms,
                }
        except grpc.RpcError as e:
            if e.code() != grpc.StatusCode.CANCELLED:
                logger.error(f"AmbientSubscribe error: {e}")
                yield {
                    "phase": "AMBIENT_PHASE_ERROR",
                    "message": f"Stream error: {e.details()}",
                    "progress": 0.0,
                    "metrics": {},
                    "timestamp_ms": 0,
                }

    async def _call_datasets(self, action: str, params: dict, timeout: float) -> dict:
        """Handle HuggingFace Dataset Discovery service calls via gRPC.

        Provides operations for discovering datasets from HuggingFace Hub
        and managing dataset references in the KB.

        Args:
            action: Action to perform (list, add, info, list_kb)
            params: Action parameters
            timeout: Request timeout

        Returns:
            Result dict with datasets or operation status
        """
        from ..engine.generated import (
            ListHFDatasetsRequest,
            AddExternalDatasetRequest,
            GetHFDatasetInfoRequest,
            ListKBDatasetsRequest,
        )

        if action == "list":
            limit = params.get("limit", 20)
            request = ListHFDatasetsRequest(limit=limit)
            response = await self._stub.ListHFDatasets(request, timeout=timeout)

            if response.error:
                return {"error": response.error}

            return {
                "datasets": [
                    {
                        "id": ds.id,
                        "author": ds.author,
                        "description": ds.description,
                        "downloads": ds.downloads,
                        "likes": ds.likes,
                        "private": ds.private,
                        "created_at": ds.created_at,
                        "last_modified": ds.last_modified,
                        "tags": list(ds.tags),
                    }
                    for ds in response.datasets
                ],
                "count": response.count,
                "saved_to": response.saved_to,
            }

        elif action == "add":
            dataset_id = params.get("dataset_id", "")
            notes = params.get("notes", "")
            request = AddExternalDatasetRequest(dataset_id=dataset_id, notes=notes)
            response = await self._stub.AddExternalDataset(request, timeout=timeout)

            if response.error:
                return {"error": response.error, "success": False}

            return {
                "success": response.success,
                "dataset_id": response.dataset_id,
                "saved_to": response.saved_to,
                "downloads": response.downloads,
                "likes": response.likes,
                "description": response.description,
            }

        elif action == "info":
            dataset_id = params.get("dataset_id", "")
            request = GetHFDatasetInfoRequest(dataset_id=dataset_id)
            response = await self._stub.GetHFDatasetInfo(request, timeout=timeout)

            if response.error:
                return {"error": response.error}

            info = response.info
            return {
                "id": info.id,
                "author": info.author,
                "description": info.description,
                "downloads": info.downloads,
                "likes": info.likes,
                "private": info.private,
                "created_at": info.created_at,
                "last_modified": info.last_modified,
                "tags": list(info.tags),
                "url": response.url,
            }

        elif action == "list_kb":
            request = ListKBDatasetsRequest()
            response = await self._stub.ListKBDatasets(request, timeout=timeout)

            return {
                "internal": [
                    {"id": ds.id, "type": ds.type, "path": ds.path}
                    for ds in response.internal
                ],
                "external": [
                    {"id": ds.id, "type": ds.type, "path": ds.path}
                    for ds in response.external
                ],
                "internal_count": response.internal_count,
                "external_count": response.external_count,
            }

        else:
            raise ValueError(f"Unknown Datasets action: {action}")

    async def _call_models(self, action: str, params: dict, timeout: float) -> dict:
        """Handle Models service calls via gRPC.

        Actions:
            list: List recent models from HuggingFace
            add: Add external model reference to KB
            info: Get detailed info for a specific model
            list_kb: List models in KB (internal = cached, external = references)

        Args:
            action: Action to perform
            params: Action parameters (model_id, limit, filter, notes)
            timeout: Request timeout

        Returns:
            Result dict with models list or model info
        """
        from ..engine.generated import (
            ListHFModelsRequest,
            AddExternalModelRequest,
            GetHFModelInfoRequest,
            ListKBModelsRequest,
        )

        if action == "list":
            limit = params.get("limit", 20)
            filter_tag = params.get("filter", "")
            request = ListHFModelsRequest(limit=limit, filter=filter_tag)
            response = await self._stub.ListHFModels(request, timeout=timeout)

            if response.error:
                return {"error": response.error}

            return {
                "models": [
                    {
                        "id": m.id,
                        "author": m.author,
                        "pipeline_tag": m.pipeline_tag,
                        "downloads": m.downloads,
                        "likes": m.likes,
                        "private": m.private,
                        "created_at": m.created_at,
                        "last_modified": m.last_modified,
                        "tags": list(m.tags),
                        "gated": m.gated,
                        "library_name": m.library_name,
                    }
                    for m in response.models
                ],
                "count": response.count,
                "saved_to": response.saved_to,
            }

        elif action == "add":
            model_id = params.get("model_id", "")
            notes = params.get("notes", "")
            request = AddExternalModelRequest(model_id=model_id, notes=notes)
            response = await self._stub.AddExternalModel(request, timeout=timeout)

            if response.error:
                return {"error": response.error}

            return {
                "success": response.success,
                "model_id": response.model_id,
                "saved_to": response.saved_to,
                "downloads": response.downloads,
                "likes": response.likes,
                "pipeline_tag": response.pipeline_tag,
            }

        elif action == "info":
            model_id = params.get("model_id", "")
            request = GetHFModelInfoRequest(model_id=model_id)
            response = await self._stub.GetHFModelInfo(request, timeout=timeout)

            if response.error:
                return {"error": response.error}

            info = response.info
            return {
                "id": info.id,
                "author": info.author,
                "pipeline_tag": info.pipeline_tag,
                "downloads": info.downloads,
                "likes": info.likes,
                "private": info.private,
                "created_at": info.created_at,
                "last_modified": info.last_modified,
                "tags": list(info.tags),
                "gated": info.gated,
                "library_name": info.library_name,
                "url": response.url,
            }

        elif action == "list_kb":
            request = ListKBModelsRequest()
            response = await self._stub.ListKBModels(request, timeout=timeout)

            return {
                "internal": [
                    {
                        "id": m.id,
                        "type": m.type,
                        "path": m.path,
                        "size_bytes": m.size_bytes,
                        "pipeline_tag": m.pipeline_tag,
                    }
                    for m in response.internal
                ],
                "external": [
                    {
                        "id": m.id,
                        "type": m.type,
                        "path": m.path,
                        "size_bytes": m.size_bytes,
                        "pipeline_tag": m.pipeline_tag,
                    }
                    for m in response.external
                ],
                "internal_count": response.internal_count,
                "external_count": response.external_count,
                "total_cache_bytes": response.total_cache_bytes,
            }

        else:
            raise ValueError(f"Unknown Models action: {action}")

    async def _call_prospects(self, action: str, params: dict, timeout: float) -> dict:
        """Handle Prospects/Stewardship service calls via gRPC.

        Actions:
            status: Get current prospects status (cached, $0)
            check: Check for new SEC filings (~$0)
            update: Run full LLM analysis (~$0.60/prospect) - NOT IMPLEMENTED via call()

        Note: For streaming update operations, use the stream() method instead.

        Args:
            action: Action to perform
            params: Action parameters (profile, domain, force, symbols)
            timeout: Request timeout

        Returns:
            Result dict with prospects status or check results
        """
        profile = params.get("profile", "zndx")
        domain = params.get("domain", "prospecting")

        if action == "status":
            request = ProspectsStatusRequest(profile=profile, domain=domain)
            response = await self._stub.ProspectsStatus(request, timeout=timeout)
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "check":
            force = params.get("force", False)
            request = ProspectsCheckRequest(profile=profile, domain=domain, force=force)
            response = await self._stub.ProspectsCheck(request, timeout=timeout)
            return MessageToDict(response, preserving_proto_field_name=True)

        else:
            raise ValueError(
                f"Unknown Prospects action: {action}. "
                f"For 'update', use stream() method instead of call()."
            )

    async def _call_research_flow(self, action: str, params: dict, timeout: float) -> dict:
        """Handle ResearchFlow service calls via gRPC.

        Actions:
            status: Get current research status
            stop: Request stop of running research

        Note: For streaming research operations, use the stream() method instead.

        Args:
            action: Action to perform (status, stop)
            params: Action parameters (unused)
            timeout: Request timeout

        Returns:
            Result dict with research status or stop result
        """
        if action == "status":
            response = await self._stub.ResearchFlowStatus(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "stop":
            response = await self._stub.ResearchFlowStop(
                empty_pb2.Empty(),
                timeout=timeout,
            )
            return MessageToDict(response, preserving_proto_field_name=True)

        else:
            raise ValueError(
                f"Unknown ResearchFlow action: {action}. "
                f"For 'research_stream', use stream() method instead of call()."
            )

    async def _call_collection(self, action: str, params: dict, timeout: float) -> dict:
        """Handle Collection service calls via gRPC.

        Actions:
            status: Get collection statistics
            list_collections: List all collections
            create_collection: Create new collection
            set_featured: Set featured collection
            add_card: Add card to collection
            list_cards: List cards in collection
            publish_cards: Publish pending cards
            publish_viz: Update 3D visualization data

        Args:
            action: Action to perform
            params: Action parameters
            timeout: Request timeout

        Returns:
            Result dict with collection/card data
        """
        if action == "status":
            request = CollectionStatusRequest()
            response = await self._stub.CollectionStatus(request, timeout=timeout)
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "list_collections":
            request = CollectionListRequest(
                status=params.get("status", ""),
                limit=params.get("limit", 50),
            )
            response = await self._stub.CollectionList(request, timeout=timeout)
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "create_collection":
            request = CollectionCreateRequest(
                slug=params.get("slug", ""),
                name=params.get("name", ""),
                description=params.get("description", ""),
                featured=params.get("featured", False),
            )
            response = await self._stub.CollectionCreate(request, timeout=timeout)
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "set_featured":
            request = CollectionSetFeaturedRequest(slug=params.get("slug", ""))
            response = await self._stub.CollectionSetFeatured(request, timeout=timeout)
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "add_card":
            request = CollectionAddCardRequest(
                slug=params.get("slug", ""),
                title=params.get("title", ""),
                summary=params.get("summary", ""),
                source_url=params.get("source_url", ""),
                source_type=params.get("source_type", "web"),
                image_url=params.get("image_url", ""),
            )
            response = await self._stub.CollectionAddCard(request, timeout=timeout)
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "list_cards":
            request = CollectionListCardsRequest(
                slug=params.get("slug", ""),
                status=params.get("status", ""),
                limit=params.get("limit", 100),
            )
            response = await self._stub.CollectionListCards(request, timeout=timeout)
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "publish_cards":
            request = CollectionPublishCardsRequest(
                count=params.get("count", 3),
                collection_slug=params.get("collection_slug", ""),
            )
            response = await self._stub.CollectionPublishCards(request, timeout=timeout)
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "publish_viz":
            request = CollectionPublishVizRequest()
            response = await self._stub.CollectionPublishViz(request, timeout=timeout)
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "sync_theme":
            request = CollectionSyncThemeRequest()
            response = await self._stub.CollectionSyncTheme(request, timeout=timeout)
            return MessageToDict(response, preserving_proto_field_name=True)

        else:
            raise ValueError(f"Unknown Collection action: {action}")

    async def _call_article(self, action: str, params: dict, timeout: float) -> dict:
        """Handle Article service calls via gRPC.

        Article curation pipeline for landing page content.

        Args:
            action: Action to perform (status, new, curate)
            params: Action parameters
            timeout: Request timeout

        Returns:
            Result dict with article data
        """
        if action == "status":
            request = ArticleStatusRequest()
            response = await self._stub.ArticleStatus(request, timeout=timeout)
            return MessageToDict(response, preserving_proto_field_name=True)

        elif action == "new":
            request = ArticleNewRequest(
                slug=params.get("slug", ""),
                title=params.get("title", ""),
            )
            response = await self._stub.ArticleNew(request, timeout=timeout)
            return MessageToDict(response, preserving_proto_field_name=True)

        else:
            raise ValueError(f"Unknown Article action: {action}")

    async def ArticleStatus(self) -> ArticleStatusResponse:
        """Get article curation situational awareness.

        Direct gRPC call for TUI/CLI use.

        Returns:
            ArticleStatusResponse with articles list and metrics
        """
        request = ArticleStatusRequest()
        response = await self._stub.ArticleStatus(request)
        return response

    async def ArticleNew(self, slug: str, title: str = "") -> ArticleNewResponse:
        """Create new article via gRPC.

        Architecture compliance: Client -> gRPC -> Engine -> KB filesystem
        The engine owns the KB filesystem - clients MUST NOT write directly.

        Args:
            slug: URL-friendly identifier
            title: Display title (defaults to slug if not provided)

        Returns:
            ArticleNewResponse with created article info
        """
        request = ArticleNewRequest(slug=slug, title=title)
        response = await self._stub.ArticleNew(request)
        return response

    async def ArticleCurate(
        self,
        slug: str = "",
        skip_grok: bool = False,
        max_sources: int = 10,
    ) -> AsyncIterator[ArticleCurationEvent]:
        """Run article curation pipeline via gRPC streaming.

        Architecture compliance: Client -> gRPC -> Engine -> Metaflow
        NOT: Client -> subprocess.run() -> Metaflow

        Args:
            slug: Specific article to curate (empty = all pending)
            skip_grok: Skip Grok synthesis for testing
            max_sources: Maximum external sources per article

        Yields:
            ArticleCurationEvent stream with progress updates
        """
        request = ArticleCurateRequest(
            slug=slug,
            skip_grok=skip_grok,
            max_sources=max_sources,
        )
        async for event in self._stub.ArticleCurate(request):
            yield event

    async def RenderCards(
        self,
        collection_slug: str = "",
        card_id: str = "",
        sample: int = 0,
        variants: list[str] | None = None,
        force: bool = False,
        upload: bool = True,
    ) -> AsyncIterator[RenderCardEvent]:
        """Stream card rendering progress via gRPC.

        Architecture compliance: Client -> gRPC -> Engine -> Blender subprocess

        Args:
            collection_slug: Render cards in this collection (empty = all)
            card_id: Render specific card (overrides collection)
            sample: Random sample N cards (0 = all matching)
            variants: Resolution variants to render (empty = all)
            force: Re-render even if image exists
            upload: Upload to R2 after rendering

        Yields:
            RenderCardEvent stream with progress updates
        """
        request = RenderCardsRequest(
            collection_slug=collection_slug,
            card_id=card_id,
            sample=sample,
            variants=variants or [],
            force=force,
            upload=upload,
        )
        async for event in self._stub.RenderCards(request):
            yield event

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
            response = await self._stub.Init(request, timeout=timeout)
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
            response = await self._stub.Reindex(request, timeout=timeout)
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

        async for progress in self._stub.InitProgressStream(request):
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

        async for progress in self._stub.ReindexStream(request):
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
    ) -> dict[str, dict | str]:
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
        # Capabilities: reasoning, instruct, long_context, adversarial, synthesis
        ROLE_TO_ENDPOINT = {
            "Leader": "orchestrator",      # reasoning/synthesis
            "Risk": "thinking",            # analysis
            "Optimizer": "thinking",       # analysis
            "Planner": "orchestrator",     # reasoning
            "Critic": "thinking",          # adversarial/analysis
            "Executor": "thinking",        # execution
            "Adversary": "thinking",       # adversarial
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
                    endpoint = ROLE_TO_ENDPOINT.get(role_name, "thinking")

                    request = CompleteRequest(
                        agent_alias=endpoint,
                        prompt=prompt,
                        system_prompt=role_def.system_prompt or "",
                        max_tokens=role_def.max_tokens,
                        temperature=role_def.temperature,
                        priority="high",
                    )
                    response = await self._stub.Complete(request, timeout=timeout)
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
        response = await self._inference.ServerLive(
            ServerLiveRequest(),
            timeout=self.config.timeout,
        )
        return response.live

    async def server_ready(self) -> bool:
        """Check if server is ready (OIP ServerReady)."""
        response = await self._inference.ServerReady(
            ServerReadyRequest(),
            timeout=self.config.timeout,
        )
        return response.ready

    async def model_ready(self, model_name: str) -> bool:
        """Check if a specific model is ready (OIP ModelReady)."""
        response = await self._inference.ModelReady(
            ModelReadyRequest(name=model_name),
            timeout=self.config.timeout,
        )
        return response.ready

    async def server_metadata(self) -> dict:
        """Get server metadata (OIP ServerMetadata)."""
        response = await self._inference.ServerMetadata(
            ServerMetadataRequest(),
            timeout=self.config.timeout,
        )
        return MessageToDict(response, preserving_proto_field_name=True)

    async def model_metadata(self, model_name: str) -> dict:
        """Get model metadata (OIP ModelMetadata)."""
        response = await self._inference.ModelMetadata(
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
            async for event in self._stub.EventStream(request):
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
            async for metrics in self._stub.HealthStream(request):
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
        async for metrics in self._stub.HealthStream(request):
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
        async for event in self._stub.EventStream(request):
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
            call = self._stub.InitStream(command_generator())
            async for event in call:
                event_dict = {
                    "type": InitEvent.Type.Name(event.type),
                    "type_enum": event.type,  # Raw proto enum for direct comparison
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
            call = self._stub.InitStream(single_command())
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
        clt: bool = False,
    ) -> AsyncIterator[dict]:
        """Stream swarm analysis with real-time progress updates.

        Unlike the blocking run_swarm, this streams status updates during
        execution, handling backend wait internally. The stream continues
        even while waiting for backends to initialize, preventing timeouts.

        Args:
            domain: Domain to analyze (e.g., "pension", "kudu")
            context: Additional context for the analysis
            roles: Agent roles to include (default: all core roles)
            clt: Use CLT-enhanced swarm with interpretable features

        Yields:
            SwarmEvent dicts with:
                - type: Event type (QUEUED, WAITING_FOR_BACKENDS, STARTED,
                        AGENT_STARTED, AGENT_COMPLETED, AGENT_FAILED, COMPLETED)
                - timestamp_ms: Event timestamp
                - agent: Agent name (for AGENT_* events)
                - progress: 0.0-1.0 overall progress
                - message: Human-readable status message
                - data: JSON payload (agent result on AGENT_COMPLETED,
                        final results on COMPLETED, includes _clt if clt=True)

        Example:
            async for event in client.swarm_stream("pension", clt=True):
                print(f"{event['type']}: {event['message']} ({event['progress']:.0%})")
                if event['type'] == 'COMPLETED':
                    final = json.loads(event['data'])
                    print(f"Saved to: {final['saved_path']}")
        """
        request = SwarmStreamRequest(
            domain=domain,
            context=context,
            roles=roles or [],
            clt=clt,
        )

        try:
            async for event in self._stub.SwarmStream(request):
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

    # ─────────────────────────────────────────────────────────────────────────
    # Cognition/Evolution Streaming
    # ─────────────────────────────────────────────────────────────────────────

    async def subscribe_cognition(
        self,
        buffer_size: int = 100,
        event_types: Optional[list[str]] = None,
    ) -> AsyncIterator[dict]:
        """Subscribe to cognition events (thoughts, patterns, connections).

        Real-time stream of engine cognition activity. Use this instead of
        polling get_recent_thoughts() for responsive TUI updates.

        Args:
            buffer_size: Server-side buffer size for events
            event_types: Filter to specific event types (default: all)

        Yields:
            CognitionEvent dicts with:
                - type: Event type (CYCLE_START, THOUGHT, PATTERN, CONNECTION,
                        CURIOSITY, SELF_OBSERVATION, ENGINE_AUDIT, CYCLE_END, ERROR)
                - timestamp_ms: Event timestamp
                - thought_id: Unique thought ID
                - thought_type: Thought type string
                - title: Thought title/summary
                - content: Full thought content
                - confidence: Confidence score (0.0-1.0)
                - cycle_id: Cognition cycle ID
                - error_message: Error details (for ERROR type)
        """
        request = CognitionStreamRequest(
            buffer_size=buffer_size,
            event_types=event_types or [],
        )

        try:
            async for event in self._stub.SubscribeCognition(request):
                yield {
                    "type": CognitionEvent.Type.Name(event.type),
                    "timestamp_ms": event.timestamp_ms,
                    "thought_id": event.thought_id,
                    "thought_type": event.thought_type,
                    "title": event.title,
                    "summary": event.summary,
                    "salience": event.salience,
                    "generation": event.generation,
                    "cycle_id": event.cycle_id,
                }
        except grpc.RpcError as e:
            if e.code() != grpc.StatusCode.CANCELLED:
                logger.error(f"SubscribeCognition error: {e}")
                yield {
                    "type": "ERROR",
                    "timestamp_ms": int(time.time() * 1000),
                    "thought_id": "",
                    "thought_type": "",
                    "title": "Stream error",
                    "summary": str(e.details()) if hasattr(e, 'details') else str(e),
                    "salience": 0.0,
                    "generation": 0,
                    "cycle_id": "",
                }

    async def subscribe_evolution(
        self,
        buffer_size: int = 100,
        agent_filter: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        """Subscribe to evolution events (optimization cycles, metrics).

        Real-time stream of agent evolution activity. Use this instead of
        polling evolution_status() for responsive TUI updates.

        Args:
            buffer_size: Server-side buffer size for events
            agent_filter: Filter to specific agent (default: all)

        Yields:
            EvolutionEvent dicts with:
                - type: Event type (CYCLE_START, OPTIMIZATION_STEP, EVALUATION,
                        PROMOTION, ROLLBACK, CYCLE_END, ERROR)
                - timestamp_ms: Event timestamp
                - cycle_id: Evolution cycle ID
                - agent_id: Agent being optimized
                - version_id: Version being evaluated
                - score: Evaluation score
                - improvement: Score improvement delta
                - message: Status message
                - error_message: Error details (for ERROR type)
        """
        request = EvolutionStreamRequest(
            buffer_size=buffer_size,
            agent_filter=agent_filter or "",
        )

        try:
            async for event in self._stub.SubscribeEvolution(request):
                yield {
                    "type": EvolutionEvent.Type.Name(event.type),
                    "timestamp_ms": event.timestamp_ms,
                    "cycle_number": event.cycle_number,
                    "agent_id": event.agent_id,
                    "version_id": event.version_id,
                    "score": event.score,
                    "improvement_pct": event.improvement_pct,
                    "details": event.details,
                    "merge_id": event.merge_id,
                    "error": event.error,
                }
        except grpc.RpcError as e:
            if e.code() != grpc.StatusCode.CANCELLED:
                logger.error(f"SubscribeEvolution error: {e}")
                yield {
                    "type": "ERROR",
                    "timestamp_ms": int(time.time() * 1000),
                    "cycle_number": 0,
                    "agent_id": "",
                    "version_id": "",
                    "score": 0.0,
                    "improvement_pct": 0.0,
                    "details": "Stream error",
                    "merge_id": "",
                    "error": str(e.details()) if hasattr(e, 'details') else str(e),
                }

    async def subscribe_activity(
        self,
        buffer_size: int = 100,
        domains: list[str] | None = None,
    ) -> AsyncIterator[dict]:
        """Subscribe to general engine activity events.

        Unified stream for health, endpoints, and other engine activity.
        Useful for TUI status updates.

        Args:
            buffer_size: Server-side buffer size for events
            domains: Filter by domain (empty/None = all)

        Yields:
            ActivityEvent dicts with:
                - type: Event type (HEALTH_UPDATE, ENDPOINT_STATUS, GPU_METRICS,
                        QUEUE_STATUS, DAEMON_STATUS, ERROR)
                - timestamp_ms: Event timestamp
                - data: JSON payload with event-specific data
        """
        request = ActivityStreamRequest(
            buffer_size=buffer_size,
            domains=domains or [],
        )

        try:
            async for event in self._stub.SubscribeActivity(request):
                yield {
                    "type": event.event_type,
                    "timestamp_ms": event.timestamp_ms,
                    "data": event.data.decode() if event.data else "",
                }
        except grpc.RpcError as e:
            if e.code() != grpc.StatusCode.CANCELLED:
                logger.error(f"SubscribeActivity error: {e}")
                yield {
                    "type": "ERROR",
                    "timestamp_ms": int(time.time() * 1000),
                    "data": f'{{"error": "{e.details()}"}}',
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
_grpc_default_config: Optional[GrpcClientConfig] = None


def configure_grpc_client(config: GrpcClientConfig) -> None:
    """Configure the gRPC client singleton before first use.

    Call this early in application startup (e.g., in TUI __init__) to set
    the retry behavior. Must be called before first get_grpc_client() call.

    Args:
        config: Configuration to use. Common patterns:
            - GrpcClientConfig.for_tui() - TUI with infinite retries
            - GrpcClientConfig.for_cli() - CLI with finite retries
            - GrpcClientConfig.for_mcp() - MCP with finite retries
    """
    global _grpc_default_config
    _grpc_default_config = config
    logger.debug(f"gRPC client configured: max_retries={config.max_retries}")


def _get_connect_lock() -> asyncio.Lock:
    """Get or create the connection lock (lazy init for event loop compatibility)."""
    global _grpc_connect_lock
    if _grpc_connect_lock is None:
        _grpc_connect_lock = asyncio.Lock()
    return _grpc_connect_lock


async def get_grpc_client(
    config: Optional[GrpcClientConfig] = None,
) -> GrpcEngineClient:
    """Get or create the gRPC engine client singleton.

    If the client exists but is not connected, attempts to reconnect.
    This handles the case where the engine wasn't running when TUI started.

    Uses a lock to prevent concurrent connection attempts (which cause
    ENHANCE_YOUR_CALM errors from the server).

    Args:
        config: Optional config to use when creating a new client.
                - Use GrpcClientConfig.for_tui() for infinite retries
                - Use GrpcClientConfig.for_cli() for finite retries (default)
                Ignored if client already exists.
    """
    global _grpc_client, _grpc_default_config

    if _grpc_client is None:
        # Use provided config, or default config, or create from env
        effective_config = config or _grpc_default_config
        _grpc_client = GrpcEngineClient(effective_config)

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


# Alias for backward compatibility
# Some code uses GaiusClient as the class name
GaiusClient = GrpcEngineClient
