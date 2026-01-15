"""PostgreSQL LISTEN/NOTIFY listener for flow completion events.

Maintains a persistent connection to PostgreSQL and dispatches flow
completion notifications to registered handlers.

Design:
- Single dedicated connection for listening (not shared with main pool)
- Automatic reconnection with exponential backoff on connection loss
- Health check every 30s to verify listener is alive
- Falls back to polling if LISTEN fails (hybrid approach)

Guru Meditation Codes:
- #FL.00000001.CONNFAIL: LISTEN connection failed
- #FL.00000002.PARSENOTIFY: Failed to parse notification payload
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class FlowEvent:
    """Flow completion event from PostgreSQL notification."""

    run_id: str
    flow_type: str
    status: str  # completed, failed
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    event_id: str = ""

    @classmethod
    def from_payload(cls, payload: str, event_id: str = "") -> "FlowEvent":
        """Parse FlowEvent from pg_notify JSON payload.

        Args:
            payload: JSON string from pg_notify
            event_id: Optional event identifier

        Returns:
            FlowEvent instance

        Raises:
            ValueError: If payload is malformed
        """
        data = json.loads(payload)

        # Parse timestamps
        started_at = None
        if data.get("started_at"):
            try:
                started_at = datetime.fromisoformat(data["started_at"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        completed_at = None
        if data.get("completed_at"):
            try:
                completed_at = datetime.fromisoformat(data["completed_at"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        return cls(
            run_id=data["run_id"],
            flow_type=data["flow_type"],
            status=data["status"],
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=data.get("duration_ms"),
            event_id=event_id or data.get("event_id", ""),
        )


# Type alias for event handlers
FlowEventHandler = Callable[[FlowEvent], Awaitable[None]]


class FlowEventListener:
    """PostgreSQL LISTEN/NOTIFY listener for flow events.

    Maintains persistent connection to listen for flow_events channel.
    Dispatches notifications to async handlers via callback.

    Hybrid Design:
    - Primary: asyncpg LISTEN (push-based, ~5-10ms latency)
    - Fallback: Polling loop if connection lost (60s interval)
    - Health: Monitor listener connection every 30s
    """

    def __init__(
        self,
        database_url: str | None = None,
        handler: FlowEventHandler | None = None,
        channel: str = "flow_events",
    ):
        """Initialize the FlowEventListener.

        Args:
            database_url: PostgreSQL connection URL
            handler: Async callback for flow events
            channel: PostgreSQL LISTEN channel name
        """
        self.database_url = database_url or os.environ.get(
            "GAIUS_DATABASE_URL",
            "postgres://localhost:5438/zndx_gaius?sslmode=disable",
        )
        self._handler = handler
        self._channel = channel

        self._running = False
        self._connection: asyncpg.Connection | None = None
        self._listen_task: asyncio.Task | None = None
        self._fallback_task: asyncio.Task | None = None
        self._health_task: asyncio.Task | None = None

        # Metrics
        self._events_received = 0
        self._events_dispatched = 0
        self._connection_failures = 0
        self._last_event_at: datetime | None = None
        self._connected_at: datetime | None = None

    async def start(self) -> None:
        """Start the flow event listener."""
        if self._running:
            return

        logger.info("Starting FlowEventListener...")
        self._running = True

        # Start main listener task
        self._listen_task = asyncio.create_task(self._listen_loop())

        # Start fallback polling task
        self._fallback_task = asyncio.create_task(self._fallback_polling_loop())

        # Start health check task
        self._health_task = asyncio.create_task(self._health_check_loop())

        logger.info("FlowEventListener started")

    async def stop(self) -> None:
        """Stop the flow event listener."""
        if not self._running:
            return

        logger.info("Stopping FlowEventListener...")
        self._running = False

        # Cancel all tasks
        for task in [self._listen_task, self._fallback_task, self._health_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Close connection
        if self._connection:
            try:
                await self._connection.close()
            except Exception:
                pass
            self._connection = None

        logger.info("FlowEventListener stopped")

    def set_handler(self, handler: FlowEventHandler) -> None:
        """Register callback for flow events.

        Args:
            handler: Async callable that receives FlowEvent
        """
        self._handler = handler

    @property
    def is_connected(self) -> bool:
        """Check if LISTEN connection is active."""
        return self._connection is not None and not self._connection.is_closed()

    def get_status(self) -> dict[str, Any]:
        """Get listener status for health monitoring."""
        return {
            "running": self._running,
            "connected": self.is_connected,
            "channel": self._channel,
            "events_received": self._events_received,
            "events_dispatched": self._events_dispatched,
            "connection_failures": self._connection_failures,
            "last_event_at": self._last_event_at.isoformat() if self._last_event_at else None,
            "connected_at": self._connected_at.isoformat() if self._connected_at else None,
        }

    async def _listen_loop(self) -> None:
        """Main LISTEN loop with reconnection logic."""
        backoff_ms = 500
        max_backoff_ms = 30000

        while self._running:
            try:
                # Create dedicated connection for listening
                self._connection = await asyncpg.connect(self.database_url)
                self._connected_at = datetime.now()
                backoff_ms = 500  # Reset backoff on successful connection

                logger.info(f"Connected to PostgreSQL for LISTEN on '{self._channel}'")

                # Register listener callback
                await self._connection.add_listener(
                    self._channel,
                    self._on_notification,
                )

                # Keep connection open until cancelled or error
                while self._running and self.is_connected:
                    await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connection_failures += 1
                logger.warning(
                    f"LISTEN connection lost (#FL.00000001.CONNFAIL): {e}"
                )

                if self._connection:
                    try:
                        await self._connection.close()
                    except Exception:
                        pass
                    self._connection = None
                    self._connected_at = None

                # Exponential backoff before reconnecting
                wait_time = min(backoff_ms / 1000, max_backoff_ms / 1000)
                logger.info(f"Reconnecting in {wait_time:.1f}s...")
                await asyncio.sleep(wait_time)
                backoff_ms = min(backoff_ms * 2, max_backoff_ms)

    def _on_notification(
        self,
        connection: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """Handle incoming PostgreSQL notification.

        This is a sync callback from asyncpg, so we schedule async work.
        """
        self._events_received += 1
        self._last_event_at = datetime.now()

        # Schedule async dispatch
        asyncio.create_task(self._dispatch_notification(payload))

    async def _dispatch_notification(self, payload: str) -> None:
        """Parse and dispatch notification to handler."""
        try:
            event = FlowEvent.from_payload(payload)

            logger.info(
                f"Flow event: {event.flow_type} {event.run_id} -> {event.status} "
                f"({event.duration_ms}ms)"
            )

            # Dispatch to handler
            if self._handler:
                await self._handler(event)
                self._events_dispatched += 1

        except json.JSONDecodeError as e:
            logger.error(
                f"Failed to parse notification (#FL.00000002.PARSENOTIFY): {e}"
            )
        except Exception as e:
            logger.error(f"Error processing notification: {e}")

    async def _fallback_polling_loop(self) -> None:
        """Fallback polling loop if LISTEN connection is lost.

        Polls meta.flow_runs for any completed/failed runs that weren't
        caught by LISTEN (e.g., if connection dropped during event).
        """
        last_check: datetime | None = None
        poll_interval_s = 60

        while self._running:
            try:
                # Only poll if listener is disconnected
                if not self.is_connected:
                    now = datetime.now()
                    if last_check is None:
                        last_check = now
                        await asyncio.sleep(5)
                        continue

                    # Poll when disconnected
                    elapsed = (now - last_check).total_seconds()
                    if elapsed >= poll_interval_s:
                        await self._poll_completed_flows(since=last_check)
                        last_check = now

                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Fallback polling error: {e}")
                await asyncio.sleep(10)

    async def _poll_completed_flows(self, since: datetime) -> None:
        """Poll for completed flows since last check."""
        try:
            async with asyncpg.create_pool(
                self.database_url, min_size=1, max_size=1
            ) as pool:
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        """
                        SELECT run_id, flow_type, status, started_at, completed_at, duration_ms
                        FROM meta.flow_runs
                        WHERE status IN ('completed', 'failed')
                          AND updated_at > $1
                        ORDER BY updated_at DESC
                        LIMIT 100
                        """,
                        since,
                    )

                    for row in rows:
                        event = FlowEvent(
                            run_id=str(row["run_id"]),
                            flow_type=row["flow_type"],
                            status=row["status"],
                            started_at=row["started_at"],
                            completed_at=row["completed_at"],
                            duration_ms=row["duration_ms"],
                            event_id=f"fallback_{row['run_id']}",
                        )

                        if self._handler:
                            await self._handler(event)

                    if rows:
                        logger.info(
                            f"Fallback poll found {len(rows)} completed flows"
                        )

        except Exception as e:
            logger.error(f"Fallback polling failed: {e}")

    async def _health_check_loop(self) -> None:
        """Periodic health check of LISTEN connection."""
        check_interval_s = 30

        while self._running:
            try:
                await asyncio.sleep(check_interval_s)

                if self._connection is None:
                    logger.warning(
                        "LISTEN connection is NULL - waiting for reconnection"
                    )
                    continue

                if self._connection.is_closed():
                    logger.warning(
                        "LISTEN connection is closed - reconnection should trigger"
                    )
                    continue

                # Test connection with a simple query
                try:
                    await self._connection.fetchval("SELECT 1")
                    logger.debug("LISTEN connection health check OK")
                except Exception as e:
                    logger.warning(f"LISTEN connection health check failed: {e}")
                    # Close connection to trigger reconnect
                    try:
                        await self._connection.close()
                    except Exception:
                        pass
                    self._connection = None

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")
