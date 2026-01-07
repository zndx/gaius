"""Initialization controller for bidirectional gRPC streaming.

This module manages the initialization process with support for:
- Real-time progress broadcasting to TUI/MCP clients
- Pause/resume/cancel control from clients
- Command queue for operations that need endpoint readiness
- Immediate command execution for health checks during init

The InitController enables clients to connect during the ~240s vLLM preload
phase and receive progress updates, rather than timing out.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import AsyncIterator, Callable, Optional, cast

from .generated.gaius_service_pb2 import InitCommand, InitEvent

logger = logging.getLogger(__name__)


class InitPhase(Enum):
    """Engine initialization phases."""
    NOT_STARTED = auto()
    TELEMETRY = auto()
    BACKENDS = auto()
    ORCHESTRATOR = auto()
    PRELOAD = auto()
    GRPC = auto()
    AERON = auto()
    SOCKET = auto()
    EVOLUTION = auto()
    COGNITION = auto()
    READY = auto()


@dataclass
class EndpointProgress:
    """Progress tracking for a single endpoint preload."""
    name: str
    status: str = "pending"  # pending, starting, ready, failed, cancelled
    progress: float = 0.0
    message: str = ""
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


@dataclass
class InitState:
    """Current initialization state."""
    phase: InitPhase = InitPhase.NOT_STARTED
    overall_progress: float = 0.0
    message: str = ""
    endpoints: dict[str, EndpointProgress] = field(default_factory=dict)
    started_at: Optional[float] = None
    ready_at: Optional[float] = None


class InitController:
    """Manages initialization with bidirectional control.

    Key capabilities:
    - Pause/resume endpoint preloading
    - Cancel specific endpoint preloads
    - Broadcast progress events to subscribers
    - Execute immediate commands (health, status)
    - Queue commands that need endpoints to be ready
    """

    def __init__(self):
        """Initialize the controller."""
        self._state = InitState()
        self._paused = asyncio.Event()
        self._paused.set()  # Not paused initially
        self._cancelled_endpoints: set[str] = set()
        self._subscribers: list[asyncio.Queue[InitEvent]] = []
        self._command_queue: asyncio.Queue[tuple[InitCommand, asyncio.Future]] = asyncio.Queue()
        self._init_complete = asyncio.Event()
        self._lock = asyncio.Lock()

        # Callback for orchestrator service (set during server init)
        self._orchestrator_service: Optional[object] = None
        self._health_callback: Optional[Callable] = None

    def set_orchestrator(self, orchestrator_service: object) -> None:
        """Set the orchestrator service for endpoint management."""
        self._orchestrator_service = orchestrator_service

    def set_health_callback(self, callback: Callable) -> None:
        """Set callback for health checks during init."""
        self._health_callback = callback

    @property
    def state(self) -> InitState:
        """Get current initialization state."""
        return self._state

    @property
    def is_ready(self) -> bool:
        """Check if initialization is complete."""
        return self._init_complete.is_set()

    async def wait_ready(self, timeout: Optional[float] = None) -> bool:
        """Wait for initialization to complete."""
        try:
            await asyncio.wait_for(self._init_complete.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Subscriber Management
    # ─────────────────────────────────────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue[InitEvent]:
        """Subscribe to initialization events.

        Returns a queue that will receive InitEvent messages.
        Caller should remove the queue when done using unsubscribe().
        """
        queue: asyncio.Queue[InitEvent] = asyncio.Queue(maxsize=100)
        self._subscribers.append(queue)
        logger.debug(f"InitStream subscriber added, total: {len(self._subscribers)}")
        return queue

    def unsubscribe(self, queue: asyncio.Queue[InitEvent]) -> None:
        """Unsubscribe from initialization events."""
        if queue in self._subscribers:
            self._subscribers.remove(queue)
            logger.debug(f"InitStream subscriber removed, total: {len(self._subscribers)}")

    async def _broadcast(self, event: InitEvent) -> None:
        """Broadcast an event to all subscribers."""
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("InitStream subscriber queue full, dropping event")

    async def broadcast_xb_event(self, event_type: str, data: dict) -> None:
        """Broadcast X Bookmarks event to all InitStream subscribers with OTel tracing.

        Called by XBookmarksService when auth completes or status changes.
        The TUI's InitPanel listens for these events to update in real-time.

        Extracts trace context from data (if present) to continue the trace
        across the async boundary from XBookmarksService._emit_event.

        Args:
            event_type: One of XB_AUTH_COMPLETED, XB_AUTH_FAILED, XB_STATUS_CHANGED
            data: Event payload (user_id, username, error, etc.)
        """
        from gaius.core.telemetry import get_tracer, XBAuthAttrs

        tracer = get_tracer()

        # Extract trace context from data if present (cross-async-boundary linking)
        parent_ctx = None
        parent_span_ctx = None
        if "_trace_id" in data and "_span_id" in data:
            try:
                from opentelemetry import trace as otel_trace
                parent_span_ctx = otel_trace.SpanContext(
                    trace_id=int(data.pop("_trace_id"), 16),
                    span_id=int(data.pop("_span_id"), 16),
                    is_remote=True,
                    trace_flags=otel_trace.TraceFlags(1),
                )
                parent_ctx = otel_trace.set_span_in_context(
                    otel_trace.NonRecordingSpan(parent_span_ctx)
                )
            except Exception:
                # OTel not fully initialized - continue without trace context
                pass

        # Build span kwargs for proper trace linking
        span_kwargs = {"context": parent_ctx} if parent_ctx else {}
        if parent_span_ctx:
            try:
                from opentelemetry import trace as otel_trace
                span_kwargs["links"] = [otel_trace.Link(parent_span_ctx)]
            except Exception:
                pass

        with tracer.start_as_current_span("xb.auth_event.broadcast", **span_kwargs) as span:
            span.set_attribute(XBAuthAttrs.EVENT_TYPE, event_type)
            span.set_attribute(XBAuthAttrs.SUBSCRIBER_COUNT, len(self._subscribers))

            # Map string event type to proto enum value
            type_map = {
                "XB_AUTH_COMPLETED": InitEvent.Type.XB_AUTH_COMPLETED,
                "XB_AUTH_FAILED": InitEvent.Type.XB_AUTH_FAILED,
                "XB_STATUS_CHANGED": InitEvent.Type.XB_STATUS_CHANGED,
            }

            proto_type = type_map.get(event_type)
            if proto_type is None:
                span.add_event("xb.broadcast.unknown_type", {"event_type": event_type})
                logger.warning(f"Unknown XB event type: {event_type}")
                return

            # Build human-readable message
            if event_type == "XB_AUTH_COMPLETED":
                message = f"X Bookmarks authenticated as @{data.get('username', 'unknown')}"
                span.set_attribute(XBAuthAttrs.USERNAME, data.get('username', ''))
            elif event_type == "XB_AUTH_FAILED":
                message = f"X Bookmarks auth failed: {data.get('error', 'unknown error')}"
            else:
                message = f"X Bookmarks status changed"

            event = self._create_event(
                proto_type,
                message=message,
                data=data,
            )

            span.add_event("xb.broadcast.starting", {"subscriber_count": len(self._subscribers)})
            await self._broadcast(event)
            span.add_event("xb.broadcast.completed")

            logger.info(f"Broadcast XB event: {event_type} to {len(self._subscribers)} subscribers")

    def _create_event(
        self,
        event_type: int,
        phase: str = "",
        progress: float = 0.0,
        endpoint: str = "",
        message: str = "",
        data: Optional[dict] = None,
    ) -> InitEvent:
        """Create an InitEvent with current timestamp."""
        return InitEvent(
            # Proto enum stubs expect InitEvent.Type but we use raw ints for
            # convenience (e.g., InitEvent.Type.PROGRESS = 1). Cast is safe.
            type=cast("InitEvent.Type", event_type),
            timestamp_ms=int(time.time() * 1000),
            phase=phase or self._state.phase.name.lower(),
            progress=progress or self._state.overall_progress,
            endpoint=endpoint,
            message=message,
            data=json.dumps(data).encode() if data else b"",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Phase Management
    # ─────────────────────────────────────────────────────────────────────────

    async def start_phase(self, phase: InitPhase, message: str = "") -> None:
        """Mark the start of an initialization phase."""
        async with self._lock:
            self._state.phase = phase
            self._state.message = message or f"Starting {phase.name.lower()}"

            if phase == InitPhase.TELEMETRY:
                self._state.started_at = time.time()

            # Calculate overall progress based on phase
            phase_weights = {
                InitPhase.NOT_STARTED: 0.0,
                InitPhase.TELEMETRY: 0.02,
                InitPhase.BACKENDS: 0.05,
                InitPhase.ORCHESTRATOR: 0.08,
                InitPhase.PRELOAD: 0.10,  # Preload is 10-90%
                InitPhase.GRPC: 0.92,
                InitPhase.AERON: 0.94,
                InitPhase.SOCKET: 0.96,
                InitPhase.EVOLUTION: 0.98,
                InitPhase.COGNITION: 0.99,
                InitPhase.READY: 1.0,
            }
            self._state.overall_progress = phase_weights.get(phase, 0.0)

        event = self._create_event(
            InitEvent.Type.PHASE_STARTED,
            phase=phase.name.lower(),
            message=self._state.message,
        )
        await self._broadcast(event)
        logger.info(f"Init phase: {phase.name} - {message}")

    async def complete_init(self) -> None:
        """Mark initialization as complete."""
        async with self._lock:
            self._state.phase = InitPhase.READY
            self._state.overall_progress = 1.0
            self._state.ready_at = time.time()
            self._state.message = "Initialization complete"

        event = self._create_event(
            InitEvent.Type.READY,
            message="All systems ready",
        )
        await self._broadcast(event)
        self._init_complete.set()

        duration = (self._state.ready_at - self._state.started_at) if self._state.started_at else 0
        logger.info(f"Init complete in {duration:.1f}s")

    # ─────────────────────────────────────────────────────────────────────────
    # Endpoint Preload Control
    # ─────────────────────────────────────────────────────────────────────────

    async def preload_with_control(
        self,
        endpoints: list[str],
        start_endpoint_callback: Callable[[str], AsyncIterator[tuple[str, float]]],
    ) -> dict[str, bool]:
        """Preload endpoints with pause/cancel support.

        Args:
            endpoints: List of endpoint names to preload
            start_endpoint_callback: Async callback that yields (status, progress) tuples

        Returns:
            Dict mapping endpoint name to success status
        """
        results: dict[str, bool] = {}

        # Initialize endpoint tracking
        for name in endpoints:
            self._state.endpoints[name] = EndpointProgress(name=name)

        # Preload each endpoint with control checks
        total = len(endpoints)
        for idx, endpoint in enumerate(endpoints):
            # Check if cancelled
            if endpoint in self._cancelled_endpoints:
                self._state.endpoints[endpoint].status = "cancelled"
                await self._broadcast(self._create_event(
                    InitEvent.Type.CANCELLED,
                    endpoint=endpoint,
                    message=f"Skipped {endpoint} (user cancelled)",
                ))
                results[endpoint] = False
                continue

            # Wait if paused
            if not self._paused.is_set():
                await self._broadcast(self._create_event(
                    InitEvent.Type.PAUSED,
                    message="Preloading paused by user",
                ))
                await self._paused.wait()
                await self._broadcast(self._create_event(
                    InitEvent.Type.RESUMED,
                    message="Preloading resumed",
                ))

            # Start endpoint
            ep_progress = self._state.endpoints[endpoint]
            ep_progress.status = "starting"
            ep_progress.started_at = time.time()

            await self._broadcast(self._create_event(
                InitEvent.Type.ENDPOINT_STARTING,
                endpoint=endpoint,
                message=f"Starting {endpoint}",
            ))

            try:
                # Use callback to start endpoint and get progress
                async for status, progress in start_endpoint_callback(endpoint):
                    # Check for cancellation during loading
                    if endpoint in self._cancelled_endpoints:
                        raise asyncio.CancelledError(f"User cancelled {endpoint}")

                    # Update progress
                    ep_progress.progress = progress
                    ep_progress.message = status

                    # Calculate overall progress: 10% base + 80% for preload phase
                    base_progress = 0.10
                    preload_range = 0.80
                    endpoint_weight = preload_range / total
                    endpoint_progress = base_progress + (idx * endpoint_weight) + (progress * endpoint_weight)
                    self._state.overall_progress = min(endpoint_progress, 0.90)

                    await self._broadcast(self._create_event(
                        InitEvent.Type.PROGRESS,
                        endpoint=endpoint,
                        progress=progress,
                        message=status,
                    ))

                # Endpoint ready
                ep_progress.status = "ready"
                ep_progress.progress = 1.0
                ep_progress.completed_at = time.time()

                await self._broadcast(self._create_event(
                    InitEvent.Type.ENDPOINT_READY,
                    endpoint=endpoint,
                    message=f"{endpoint} ready",
                ))
                results[endpoint] = True

            except asyncio.CancelledError:
                ep_progress.status = "cancelled"
                await self._broadcast(self._create_event(
                    InitEvent.Type.CANCELLED,
                    endpoint=endpoint,
                    message=f"Cancelled {endpoint}",
                ))
                results[endpoint] = False

            except Exception as e:
                ep_progress.status = "failed"
                ep_progress.message = str(e)
                await self._broadcast(self._create_event(
                    InitEvent.Type.ENDPOINT_FAILED,
                    endpoint=endpoint,
                    message=f"Failed: {e}",
                ))
                results[endpoint] = False
                logger.error(f"Endpoint {endpoint} failed to start: {e}")

        return results

    # ─────────────────────────────────────────────────────────────────────────
    # Command Handling
    # ─────────────────────────────────────────────────────────────────────────

    async def handle_command(self, cmd: InitCommand) -> InitEvent:
        """Handle a command from a client.

        Immediate commands execute now. Queued commands wait for readiness.
        """
        cmd_type = cmd.type

        # Immediate commands
        if cmd_type == InitCommand.Type.SUBSCRIBE:
            return self._create_event(
                InitEvent.Type.PROGRESS,
                message="Subscribed to init events",
                data=self._get_status_data(),
            )

        elif cmd_type == InitCommand.Type.HEALTH:
            health_data = await self._get_health_data()
            return self._create_event(
                InitEvent.Type.HEALTH_OK,
                message="Health check OK",
                data=health_data,
            )

        elif cmd_type == InitCommand.Type.STATUS:
            return self._create_event(
                InitEvent.Type.PROGRESS,
                message=self._state.message,
                data=self._get_status_data(),
            )

        elif cmd_type == InitCommand.Type.PAUSE:
            self._paused.clear()
            return self._create_event(
                InitEvent.Type.PAUSED,
                message="Preloading paused",
            )

        elif cmd_type == InitCommand.Type.RESUME:
            self._paused.set()
            return self._create_event(
                InitEvent.Type.RESUMED,
                message="Preloading resumed",
            )

        elif cmd_type == InitCommand.Type.CANCEL:
            endpoint = cmd.endpoint
            if endpoint:
                self._cancelled_endpoints.add(endpoint)
                return self._create_event(
                    InitEvent.Type.CANCELLED,
                    endpoint=endpoint,
                    message=f"Cancelling {endpoint}",
                )
            else:
                return self._create_event(
                    InitEvent.Type.ERROR,
                    message="CANCEL requires endpoint name",
                )

        elif cmd_type == InitCommand.Type.SKIP:
            endpoint = cmd.endpoint
            if endpoint:
                self._cancelled_endpoints.add(endpoint)
                return self._create_event(
                    InitEvent.Type.CANCELLED,
                    endpoint=endpoint,
                    message=f"Skipping {endpoint}",
                )
            else:
                return self._create_event(
                    InitEvent.Type.ERROR,
                    message="SKIP requires endpoint name",
                )

        else:
            return self._create_event(
                InitEvent.Type.ERROR,
                message=f"Unknown command type: {cmd_type}",
            )

    def _get_status_data(self) -> dict:
        """Get current status as dict for JSON serialization.

        Combines preload progress tracking with actual orchestrator status
        to show both configured and dynamically started endpoints.
        """
        # Start with preload tracking data
        endpoints_data = {
            name: {
                "status": ep.status,
                "progress": ep.progress,
                "message": ep.message,
            }
            for name, ep in self._state.endpoints.items()
        }

        # Merge actual orchestrator status (for dynamically started endpoints)
        if self._orchestrator_service:
            try:
                get_status_fn = getattr(self._orchestrator_service, "get_status", None)
                orch_status = get_status_fn() if get_status_fn else {}
                for ep_info in orch_status.get("endpoints", []):
                    ep_name = ep_info.get("name", "")
                    if ep_name and ep_name not in endpoints_data:
                        # Add dynamically started endpoint not in preload list
                        ep_status = ep_info.get("status", "unknown")
                        endpoints_data[ep_name] = {
                            "status": "ready" if ep_status == "healthy" else ep_status,
                            "progress": 1.0 if ep_status == "healthy" else 0.5,
                            "message": ep_info.get("model", ""),
                        }
                    elif ep_name in endpoints_data:
                        # Update preload endpoint with actual status if ready
                        ep_status = ep_info.get("status", "unknown")
                        if ep_status == "healthy":
                            endpoints_data[ep_name]["status"] = "ready"
                            endpoints_data[ep_name]["progress"] = 1.0
            except Exception as e:
                logger.debug(f"Could not get orchestrator status for init: {e}")

        return {
            "phase": self._state.phase.name.lower(),
            "overall_progress": self._state.overall_progress,
            "message": self._state.message,
            "is_ready": self._init_complete.is_set(),
            "is_paused": not self._paused.is_set(),
            "endpoints": endpoints_data,
            "cancelled_endpoints": list(self._cancelled_endpoints),
        }

    async def _get_health_data(self) -> dict:
        """Get basic health data (works during init)."""
        data = {
            "engine_started": self._state.started_at is not None,
            "grpc_available": True,  # If they can call this, gRPC is up
            "phase": self._state.phase.name.lower(),
            "init_complete": self._init_complete.is_set(),
        }

        if self._health_callback:
            try:
                health = await self._health_callback()
                data.update(health)
            except Exception as e:
                data["health_error"] = str(e)

        return data


# Module-level singleton for easy access
_init_controller: Optional[InitController] = None


def get_init_controller() -> InitController:
    """Get or create the singleton InitController."""
    global _init_controller
    if _init_controller is None:
        _init_controller = InitController()
    return _init_controller


def reset_init_controller() -> None:
    """Reset the singleton (for testing)."""
    global _init_controller
    _init_controller = None
