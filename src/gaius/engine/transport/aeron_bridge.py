"""Aeron IPC bridge for gaius-engine communication.

Provides pub/sub abstraction over Aeron IPC channels for:
- Request/response (streams 100/101)
- Event broadcast (stream 102)
- Health metrics broadcast (stream 103)

When aeron-python is unavailable, falls back to Unix domain sockets
for development/testing.
"""

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

from ..config import AeronConfig

logger = logging.getLogger(__name__)


@dataclass
class AeronMessage:
    """Message received from Aeron."""

    stream_id: int
    data: bytes
    session_id: int = 0


class AeronBridge(ABC):
    """Abstract base for Aeron IPC communication."""

    @abstractmethod
    async def start(self) -> None:
        """Start the bridge and connect to Aeron."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the bridge and cleanup resources."""
        pass

    @abstractmethod
    async def publish(self, stream_id: int, data: bytes) -> bool:
        """Publish data to a stream.

        Args:
            stream_id: Target stream (100=request, 101=response, 102=event, 103=health)
            data: Serialized message

        Returns:
            True if published successfully
        """
        pass

    @abstractmethod
    async def subscribe(
        self, stream_id: int, handler: Callable[[AeronMessage], None]
    ) -> None:
        """Subscribe to a stream.

        Args:
            stream_id: Stream to subscribe to
            handler: Callback for received messages
        """
        pass

    @abstractmethod
    def messages(self, stream_id: int) -> AsyncIterator[AeronMessage]:
        """Async iterator for messages on a stream.

        Args:
            stream_id: Stream to receive from

        Yields:
            AeronMessage for each received message
        """
        pass


class RealAeronBridge(AeronBridge):
    """Aeron IPC bridge using official Aeron C API via ctypes.

    Requires:
    - aeronmd media driver running
    - libaeron_client_shared.so (from aeron-cpp package)

    Status: NOT YET IMPLEMENTED
    The Python bindings for the official Aeron C API are planned.
    Currently raises RuntimeError - use UnixSocketBridge with GAIUS_ALLOW_FALLBACKS=true.
    """

    def __init__(self, config: AeronConfig):
        self.config = config
        self._aeron = None
        self._publications: dict[int, "Publication"] = {}
        self._subscriptions: dict[int, "Subscription"] = {}
        self._handlers: dict[int, Callable[[AeronMessage], None]] = {}
        self._running = False

    async def start(self) -> None:
        """Connect to Aeron media driver.

        NOTE: Aeron C API bindings not yet implemented.
        Use GAIUS_ALLOW_FALLBACKS=true for Unix socket transport.
        """
        # TODO: Implement ctypes bindings for libaeron_client_shared.so
        # The official Aeron C API provides:
        # - aeron_context_init(), aeron_context_close()
        # - aeron_init(), aeron_start(), aeron_close()
        # - aeron_add_publication(), aeron_add_subscription()
        # - aeron_publication_offer(), aeron_subscription_poll()
        raise RuntimeError(
            "Aeron C API bindings not yet implemented. "
            "Use GAIUS_ALLOW_FALLBACKS=true for Unix socket transport, "
            "or contribute the ctypes bindings at gaius/engine/transport/aeron_bridge.py"
        )

    async def stop(self) -> None:
        """Disconnect from Aeron."""
        self._running = False

        for pub in self._publications.values():
            pub.close()
        self._publications.clear()

        for sub in self._subscriptions.values():
            sub.close()
        self._subscriptions.clear()

        if self._aeron:
            self._aeron.close()
            self._aeron = None

        logger.info("Disconnected from Aeron")

    async def publish(self, stream_id: int, data: bytes) -> bool:
        """Publish to Aeron stream."""
        if not self._aeron:
            return False

        # Get or create publication
        if stream_id not in self._publications:
            channel = "aeron:ipc"
            self._publications[stream_id] = self._aeron.add_publication(
                channel, stream_id
            )
            # Wait for connection
            while not self._publications[stream_id].is_connected:
                await asyncio.sleep(0.001)

        pub = self._publications[stream_id]
        result = pub.offer(data)

        if result < 0:
            logger.warning(f"Failed to publish to stream {stream_id}: {result}")
            return False

        return True

    async def subscribe(
        self, stream_id: int, handler: Callable[[AeronMessage], None]
    ) -> None:
        """Subscribe to Aeron stream with callback."""
        if not self._aeron:
            return

        self._handlers[stream_id] = handler

        if stream_id not in self._subscriptions:
            channel = "aeron:ipc"
            self._subscriptions[stream_id] = self._aeron.add_subscription(
                channel, stream_id
            )

        # Start polling task
        asyncio.create_task(self._poll_subscription(stream_id))

    async def _poll_subscription(self, stream_id: int) -> None:
        """Poll subscription for messages."""
        sub = self._subscriptions.get(stream_id)
        handler = self._handlers.get(stream_id)

        if not sub or not handler:
            return

        def fragment_handler(buffer, offset, length, header):
            data = bytes(buffer[offset : offset + length])
            msg = AeronMessage(
                stream_id=stream_id,
                data=data,
                session_id=header.session_id,
            )
            handler(msg)

        while self._running and stream_id in self._subscriptions:
            sub.poll(fragment_handler, 10)
            await asyncio.sleep(0.001)

    async def messages(self, stream_id: int) -> AsyncIterator[AeronMessage]:
        """Async iterator for stream messages."""
        queue: asyncio.Queue[AeronMessage] = asyncio.Queue()

        def handler(msg: AeronMessage):
            queue.put_nowait(msg)

        await self.subscribe(stream_id, handler)

        try:
            while self._running:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield msg
                except asyncio.TimeoutError:
                    continue
        finally:
            # Cleanup subscription
            if stream_id in self._subscriptions:
                self._subscriptions[stream_id].close()
                del self._subscriptions[stream_id]
            if stream_id in self._handlers:
                del self._handlers[stream_id]


class UnixSocketBridge(AeronBridge):
    """Fallback Unix socket bridge for development/testing.

    Uses separate socket files for each stream, mimicking Aeron's
    stream semantics. Good for testing without aeronmd running.
    """

    def __init__(self, config: AeronConfig):
        self.config = config
        self._socket_dir = Path(config.directory)
        self._servers: dict[int, asyncio.Server] = {}
        self._clients: dict[int, list[asyncio.StreamWriter]] = {}
        self._handlers: dict[int, Callable[[AeronMessage], None]] = {}
        self._running = False

    def _socket_path(self, stream_id: int) -> Path:
        """Get socket path for a stream."""
        return self._socket_dir / f"stream_{stream_id}.sock"

    async def start(self) -> None:
        """Start Unix socket servers."""
        self._socket_dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        logger.info(f"Unix socket bridge started at {self._socket_dir}")

    async def stop(self) -> None:
        """Stop all servers and cleanup sockets."""
        self._running = False

        for server in self._servers.values():
            server.close()
            await server.wait_closed()
        self._servers.clear()

        for writers in self._clients.values():
            for writer in writers:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
        self._clients.clear()

        # Remove socket files
        for stream_id in [100, 101, 102, 103]:
            sock_path = self._socket_path(stream_id)
            if sock_path.exists():
                sock_path.unlink()

        logger.info("Unix socket bridge stopped")

    async def publish(self, stream_id: int, data: bytes) -> bool:
        """Publish to all connected clients on stream."""
        writers = self._clients.get(stream_id, [])
        if not writers:
            return True  # No subscribers, but that's OK

        # Prefix with length
        length = len(data)
        frame = length.to_bytes(4, "big") + data

        success = True
        dead_writers = []

        for writer in writers:
            try:
                writer.write(frame)
                await writer.drain()
            except Exception as e:
                logger.debug(f"Failed to write to client: {e}")
                dead_writers.append(writer)
                success = False

        # Remove dead connections
        for writer in dead_writers:
            writers.remove(writer)

        return success

    async def subscribe(
        self, stream_id: int, handler: Callable[[AeronMessage], None]
    ) -> None:
        """Start server for stream and handle connections."""
        self._handlers[stream_id] = handler

        sock_path = self._socket_path(stream_id)
        if sock_path.exists():
            sock_path.unlink()

        async def client_connected(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ):
            if stream_id not in self._clients:
                self._clients[stream_id] = []
            self._clients[stream_id].append(writer)

            try:
                while self._running:
                    # Read length-prefixed message
                    length_bytes = await reader.readexactly(4)
                    length = int.from_bytes(length_bytes, "big")
                    data = await reader.readexactly(length)

                    msg = AeronMessage(stream_id=stream_id, data=data)
                    handler(msg)

            except asyncio.IncompleteReadError:
                pass  # Client disconnected
            except Exception as e:
                logger.debug(f"Client error: {e}")
            finally:
                if stream_id in self._clients and writer in self._clients[stream_id]:
                    self._clients[stream_id].remove(writer)
                writer.close()

        server = await asyncio.start_unix_server(client_connected, path=str(sock_path))
        self._servers[stream_id] = server

        logger.debug(f"Listening on {sock_path}")

    async def messages(self, stream_id: int) -> AsyncIterator[AeronMessage]:
        """Async iterator for stream messages."""
        queue: asyncio.Queue[AeronMessage] = asyncio.Queue()

        def handler(msg: AeronMessage):
            queue.put_nowait(msg)

        await self.subscribe(stream_id, handler)

        try:
            while self._running:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield msg
                except asyncio.TimeoutError:
                    continue
        finally:
            pass  # Server cleanup handled in stop()


def create_bridge(config: AeronConfig) -> AeronBridge:
    """Create appropriate Aeron bridge based on environment.

    Currently only UnixSocketBridge is implemented (requires GAIUS_ALLOW_FALLBACKS=true).
    RealAeronBridge with ctypes bindings to libaeron is planned.

    Raises:
        RuntimeError: If Aeron bindings unavailable and fallbacks disabled
    """
    fallbacks_enabled = os.environ.get("GAIUS_ALLOW_FALLBACKS", "").lower() == "true"

    # Check for Aeron media driver
    aeron_dir = Path(config.directory)
    cnc_dat = aeron_dir / "cnc.dat"

    if cnc_dat.exists():
        # aeronmd is running, but we don't have Python bindings yet
        # TODO: When ctypes bindings are implemented, use RealAeronBridge here
        if fallbacks_enabled:
            logger.warning(
                "aeronmd running but Aeron C API bindings not yet implemented. "
                "Using Unix socket fallback."
            )
        else:
            raise RuntimeError(
                "Aeron C API bindings not yet implemented. "
                "Set GAIUS_ALLOW_FALLBACKS=true for Unix socket transport."
            )

    # aeronmd not running or bindings unavailable - use socket fallback
    if fallbacks_enabled:
        logger.info("Using Unix socket bridge (GAIUS_ALLOW_FALLBACKS=true)")
        return UnixSocketBridge(config)
    else:
        raise RuntimeError(
            f"Aeron transport not available (bindings not implemented, aeronmd: {cnc_dat.exists()}). "
            "Set GAIUS_ALLOW_FALLBACKS=true for Unix socket transport."
        )


class AeronClient:
    """Client-side Aeron connection for TUI/CLI/MCP.

    Connects to gaius-engine via Aeron IPC or Unix sockets.
    """

    def __init__(self, config: AeronConfig):
        self.config = config
        self._connected = False
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

    async def connect(self, stream_id: int = 100) -> bool:
        """Connect to engine request stream."""
        socket_path = Path(self.config.directory) / f"stream_{stream_id}.sock"

        try:
            self._reader, self._writer = await asyncio.open_unix_connection(
                str(socket_path)
            )
            self._connected = True
            return True
        except Exception as e:
            logger.error(f"Failed to connect to engine: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from engine."""
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._connected = False

    async def send(self, data: bytes) -> bool:
        """Send data to engine."""
        if not self._connected or not self._writer:
            return False

        try:
            # Length-prefixed frame
            length = len(data)
            frame = length.to_bytes(4, "big") + data
            self._writer.write(frame)
            await self._writer.drain()
            return True
        except Exception as e:
            logger.error(f"Failed to send: {e}")
            return False

    async def receive(self) -> Optional[bytes]:
        """Receive data from engine."""
        if not self._connected or not self._reader:
            return None

        try:
            length_bytes = await self._reader.readexactly(4)
            length = int.from_bytes(length_bytes, "big")
            return await self._reader.readexactly(length)
        except Exception as e:
            logger.error(f"Failed to receive: {e}")
            return None
