"""Aeron IPC client for communicating with gaius-engine.

Provides a client-side interface for sending requests to the engine
daemon via Aeron IPC or Unix socket fallback.
"""

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

# OpenTelemetry is optional
try:
    from opentelemetry import trace
    from opentelemetry.propagate import inject
    OTEL_AVAILABLE = True
except ImportError:
    trace = None
    inject = None
    OTEL_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class ClientConfig:
    """Client configuration.

    Attributes:
        aeron_dir: Aeron shared memory directory
        request_stream: Stream ID for requests
        response_stream: Stream ID for responses
        event_stream: Stream ID for events
        health_stream: Stream ID for health broadcasts
        timeout: Request timeout in seconds
        socket_path: Unix socket path (fallback)
    """

    aeron_dir: str = "/dev/shm/gaius-aeron"
    request_stream: int = 100
    response_stream: int = 101
    event_stream: int = 102
    health_stream: int = 103
    timeout: float = 30.0
    socket_path: str = "/tmp/gaius-engine.sock"

    @classmethod
    def from_env(cls) -> "ClientConfig":
        """Create config from environment variables."""
        return cls(
            aeron_dir=os.environ.get("GAIUS_AERON_DIR", "/dev/shm/gaius-aeron"),
            timeout=float(os.environ.get("GAIUS_ENGINE_TIMEOUT", "30")),
            socket_path=os.environ.get(
                "GAIUS_ENGINE_SOCKET", "/tmp/gaius-engine.sock"
            ),
        )


class EngineClient:
    """Client for communicating with gaius-engine.

    Sends requests via Aeron IPC (or Unix socket fallback) and
    handles response correlation, timeouts, and retries.

    Usage:
        client = EngineClient()
        await client.connect()

        # Call a service
        result = await client.call("Orchestrator", "status", {})

        # Subscribe to events
        client.subscribe_events(on_evolution_progress)

        await client.disconnect()
    """

    def __init__(self, config: Optional[ClientConfig] = None):
        """Initialize client.

        Args:
            config: Client configuration
        """
        self.config = config or ClientConfig.from_env()

        # Transport (set by connect)
        self._transport: Optional[Any] = None
        self._using_socket = False

        # Response correlation
        self._pending: dict[str, asyncio.Future] = {}
        self._pending_lock = asyncio.Lock()

        # Event subscribers
        self._event_callbacks: list[Callable] = []
        self._health_callbacks: list[Callable] = []

        # State
        self._connected = False
        self._receive_task: Optional[asyncio.Task] = None

        # Tracer for distributed tracing (optional)
        self._tracer = trace.get_tracer("gaius-client") if OTEL_AVAILABLE else None

    async def connect(self) -> bool:
        """Connect to the engine.

        Tries Aeron first. Falls back to Unix socket only if
        GAIUS_ENABLE_FALLBACKS=true environment variable is set.

        Returns:
            True if connected
        """
        if self._connected:
            return True

        # Try Aeron first
        if await self._try_aeron():
            self._connected = True
            logger.info("Connected to engine via Aeron IPC")
            return True

        # Check feature flag for fallback
        fallbacks_enabled = os.environ.get("GAIUS_ENABLE_FALLBACKS", "").lower() == "true"

        if fallbacks_enabled:
            # Fall back to Unix socket (only when enabled)
            if await self._try_socket():
                self._connected = True
                self._using_socket = True
                logger.info("Connected to engine via Unix socket (fallback)")
                return True
        else:
            logger.debug(
                "Unix socket fallback disabled (set GAIUS_ENABLE_FALLBACKS=true to enable)"
            )

        logger.error("Failed to connect to engine")
        return False

    async def _try_aeron(self) -> bool:
        """Try to connect via Aeron."""
        # Check if Aeron is available
        cnc_path = os.path.join(self.config.aeron_dir, "cnc.dat")
        if not os.path.exists(cnc_path):
            logger.debug("Aeron media driver not running")
            return False

        try:
            from ..engine.transport.aeron_bridge import AeronClient, create_bridge

            bridge = create_bridge(
                aeron_dir=self.config.aeron_dir,
                request_stream=self.config.request_stream,
                response_stream=self.config.response_stream,
            )

            if bridge is None:
                return False

            self._transport = AeronClient(bridge)
            await self._transport.start()

            # Start receive loop
            self._receive_task = asyncio.create_task(self._receive_loop())

            return True

        except Exception as e:
            logger.debug(f"Aeron connection failed: {e}")
            return False

    async def _try_socket(self) -> bool:
        """Try to connect via Unix socket."""
        if not os.path.exists(self.config.socket_path):
            logger.debug(f"Socket not found: {self.config.socket_path}")
            return False

        try:
            reader, writer = await asyncio.open_unix_connection(
                self.config.socket_path
            )

            self._transport = (reader, writer)

            # Start receive loop
            self._receive_task = asyncio.create_task(self._receive_loop_socket())

            return True

        except Exception as e:
            logger.debug(f"Socket connection failed: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from the engine."""
        if not self._connected:
            return

        # Cancel receive task
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        # Close transport
        if self._using_socket and self._transport:
            reader, writer = self._transport
            writer.close()
            await writer.wait_closed()
        elif self._transport:
            await self._transport.stop()

        self._connected = False
        self._transport = None
        logger.info("Disconnected from engine")

    async def call(
        self,
        service: str,
        action: str,
        params: Optional[dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        """Call a service action.

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
        request_id = str(uuid.uuid4())

        # Build request
        from ..engine.transport.protocol import (
            Request,
            Service as ServiceEnum,
            TraceContext,
            serialize_request,
        )

        # Map service name to enum
        service_map = {
            "Orchestrator": ServiceEnum.ORCHESTRATOR,
            "Scheduler": ServiceEnum.SCHEDULER,
            "Evolution": ServiceEnum.EVOLUTION,
            "Grid": ServiceEnum.GRID,
            "Tda": ServiceEnum.TDA,
            "Health": ServiceEnum.HEALTH,
        }

        service_enum = service_map.get(service)
        if service_enum is None:
            raise ValueError(f"Unknown service: {service}")

        # Create trace context - OTEL is required unless fallbacks enabled
        if OTEL_AVAILABLE:
            trace_ctx = TraceContext.from_current()
        elif os.environ.get("GAIUS_ENABLE_FALLBACKS", "").lower() == "true":
            trace_ctx = TraceContext()  # Empty context fallback
        else:
            raise RuntimeError(
                "OpenTelemetry not available. Install with: uv sync --extra telemetry "
                "(or set GAIUS_ENABLE_FALLBACKS=true to disable tracing)"
            )

        request = Request(
            id=request_id,
            service=service_enum,
            action=action,
            params=params or {},
            trace_context=trace_ctx,
        )

        # Create future for response
        future: asyncio.Future = asyncio.Future()
        async with self._pending_lock:
            self._pending[request_id] = future

        try:
            # Send request
            data = serialize_request(request)
            await self._send(data)

            # Wait for response
            result = await asyncio.wait_for(future, timeout=timeout)
            return result

        except asyncio.TimeoutError:
            async with self._pending_lock:
                self._pending.pop(request_id, None)
            raise TimeoutError(f"Request {service}.{action} timed out")

        except Exception as e:
            async with self._pending_lock:
                self._pending.pop(request_id, None)
            raise

    async def _send(self, data: bytes) -> None:
        """Send data to engine."""
        if self._using_socket:
            reader, writer = self._transport
            # Length-prefixed message
            length = len(data).to_bytes(4, "big")
            writer.write(length + data)
            await writer.drain()
        else:
            await self._transport.send(data)

    async def _receive_loop(self) -> None:
        """Receive loop for Aeron transport."""
        while self._connected:
            try:
                data = await self._transport.receive()
                if data:
                    await self._handle_message(data)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Receive error: {e}")
                await asyncio.sleep(0.1)

    async def _receive_loop_socket(self) -> None:
        """Receive loop for socket transport."""
        reader, writer = self._transport

        while self._connected:
            try:
                # Read length prefix
                length_bytes = await reader.readexactly(4)
                length = int.from_bytes(length_bytes, "big")

                # Read message
                data = await reader.readexactly(length)
                await self._handle_message(data)

            except asyncio.CancelledError:
                break
            except asyncio.IncompleteReadError:
                logger.warning("Connection closed by engine")
                self._connected = False
                break
            except Exception as e:
                logger.error(f"Receive error: {e}")
                await asyncio.sleep(0.1)

    async def _handle_message(self, data: bytes) -> None:
        """Handle received message."""
        from ..engine.transport.protocol import (
            deserialize_event,
            deserialize_health_metrics,
            deserialize_response,
        )

        try:
            # Try as response first
            response = deserialize_response(data)

            async with self._pending_lock:
                future = self._pending.pop(response.id, None)

            if future and not future.done():
                if response.error:
                    future.set_result({
                        "error": response.error.message,
                        "error_code": response.error.code,
                    })
                else:
                    future.set_result(response.result or {})

            return

        except Exception:
            pass

        try:
            # Try as event
            event = deserialize_event(data)
            for callback in self._event_callbacks:
                try:
                    callback(event)
                except Exception as e:
                    logger.error(f"Event callback error: {e}")
            return

        except Exception:
            pass

        try:
            # Try as health metrics
            health = deserialize_health_metrics(data)
            for callback in self._health_callbacks:
                try:
                    callback(health)
                except Exception as e:
                    logger.error(f"Health callback error: {e}")
            return

        except Exception:
            logger.warning("Unknown message format")

    def subscribe_events(self, callback: Callable) -> None:
        """Subscribe to event notifications.

        Args:
            callback: Function called with each event
        """
        self._event_callbacks.append(callback)

    def subscribe_health(self, callback: Callable) -> None:
        """Subscribe to health updates.

        Args:
            callback: Function called with each health update
        """
        self._health_callbacks.append(callback)

    def unsubscribe_events(self, callback: Callable) -> None:
        """Unsubscribe from events."""
        if callback in self._event_callbacks:
            self._event_callbacks.remove(callback)

    def unsubscribe_health(self, callback: Callable) -> None:
        """Unsubscribe from health updates."""
        if callback in self._health_callbacks:
            self._health_callbacks.remove(callback)

    @property
    def is_connected(self) -> bool:
        """Whether client is connected."""
        return self._connected

    @property
    def using_socket(self) -> bool:
        """Whether using Unix socket (vs Aeron)."""
        return self._using_socket


# ─────────────────────────────────────────────────────────────────────────────
# Convenience Functions
# ─────────────────────────────────────────────────────────────────────────────

_client: Optional[EngineClient] = None


async def get_client() -> EngineClient:
    """Get or create the engine client singleton."""
    global _client
    if _client is None:
        _client = EngineClient()
        await _client.connect()
    return _client


async def call(
    service: str,
    action: str,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Convenience function to call engine service.

    Args:
        service: Service name
        action: Action to perform
        params: Action parameters

    Returns:
        Response result
    """
    client = await get_client()
    return await client.call(service, action, params)
