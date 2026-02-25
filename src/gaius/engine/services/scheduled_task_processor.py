"""Scheduled Task Processor - LISTEN/NOTIFY driven task execution.

Processes tasks from the `scheduled_tasks` table when notified by pg_cron.
Uses PostgreSQL LISTEN/NOTIFY for real-time processing while engine is running.

Design:
- LISTEN on 'scheduled_task_ready' channel for immediate pickup
- Task handlers registered by task_type
- Marks tasks complete with result/error
- No automatic catch-up (manual trigger only)

Guru Meditation Codes:
- #STP.00000001.CONNFAIL: LISTEN connection failed
- #STP.00000002.TASKFAIL: Task execution failed
- #STP.00000003.NOHANDLER: No handler for task type
- #STP.00000004.PICKUPFAIL: Failed to pick up task
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

import asyncpg

from .base_daemon import BaseDaemon, DaemonCriticality, DaemonHealth

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    """A scheduled task from the database."""

    id: int
    task_type: str
    payload: dict[str, Any]
    scheduled_for: datetime
    source: str | None = None

    @classmethod
    def from_row(cls, row: asyncpg.Record) -> "ScheduledTask":
        """Create from database row."""
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return cls(
            id=row["id"],
            task_type=row["task_type"],
            payload=payload or {},
            scheduled_for=row["scheduled_for"],
            source=row.get("source"),
        )


# Type alias for task handlers
TaskHandler = Callable[[ScheduledTask], Awaitable[dict[str, Any]]]


class ScheduledTaskProcessor(BaseDaemon):
    """PostgreSQL LISTEN/NOTIFY processor for scheduled tasks.

    Listens for task insertions and executes registered handlers.
    No automatic catch-up - stale tasks require manual intervention.
    """

    def __init__(
        self,
        database_url: str | None = None,
        channel: str = "scheduled_task_ready",
    ):
        if database_url:
            self._database_url = database_url
        else:
            from gaius.core.config import get_database_url
            self._database_url = get_database_url()
        self._channel = channel

        self._running = False
        self._connection: asyncpg.Connection | None = None
        self._pool: asyncpg.Pool | None = None
        self._listen_task: asyncio.Task | None = None
        self._health_task: asyncio.Task | None = None

        # Task handlers by type
        self._handlers: dict[str, TaskHandler] = {}

        # Metrics
        self._tasks_processed = 0
        self._tasks_failed = 0
        self._connection_failures = 0
        self._last_task_at: datetime | None = None
        self._connected_at: datetime | None = None

    @property
    def name(self) -> str:
        return "scheduled_task_processor"

    @property
    def criticality(self) -> DaemonCriticality:
        return DaemonCriticality.OPTIONAL  # Landing page isn't critical to engine

    @property
    def is_running(self) -> bool:
        return self._running

    def register_handler(self, task_type: str, handler: TaskHandler) -> None:
        """Register a handler for a task type.

        Args:
            task_type: Task type string (e.g., 'publish_cards')
            handler: Async callable that receives ScheduledTask, returns result dict
        """
        self._handlers[task_type] = handler
        logger.info(f"Registered handler for task type: {task_type}")

    async def start(self) -> None:
        """Start the task processor."""
        if self._running:
            return

        logger.info("Starting ScheduledTaskProcessor...")
        self._running = True

        # Create connection pool for task execution
        self._pool = await asyncpg.create_pool(
            self._database_url,
            min_size=1,
            max_size=3,
        )

        # Register default handlers
        await self._register_default_handlers()

        # Start LISTEN loop
        self._listen_task = asyncio.create_task(self._listen_loop())

        # Start health check
        self._health_task = asyncio.create_task(self._health_check_loop())

        logger.info(f"ScheduledTaskProcessor started, listening on '{self._channel}'")

    async def stop(self) -> None:
        """Stop the task processor."""
        if not self._running:
            return

        logger.info("Stopping ScheduledTaskProcessor...")
        self._running = False

        # Cancel tasks
        for task in [self._listen_task, self._health_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Close connections
        if self._connection:
            try:
                await self._connection.close()
            except Exception:
                pass
            self._connection = None

        if self._pool:
            await self._pool.close()
            self._pool = None

        logger.info("ScheduledTaskProcessor stopped")

    async def health_check(self) -> DaemonHealth:
        """Check processor health."""
        if not self._running:
            return DaemonHealth(
                healthy=False,
                message="Processor not running",
                guru_code="#STP.00000001.CONNFAIL",
            )

        connected = self._connection is not None and not self._connection.is_closed()

        return DaemonHealth(
            healthy=connected,
            message="Listening" if connected else "Disconnected (reconnecting)",
            details={
                "channel": self._channel,
                "tasks_processed": self._tasks_processed,
                "tasks_failed": self._tasks_failed,
                "connection_failures": self._connection_failures,
                "last_task_at": self._last_task_at.isoformat() if self._last_task_at else None,
                "handlers": list(self._handlers.keys()),
            },
        )

    async def _register_default_handlers(self) -> None:
        """Register handlers for known task types."""
        # Import here to avoid circular imports
        from .collection_service import CollectionService

        async def handle_publish_cards(task: ScheduledTask) -> dict[str, Any]:
            """Handle publish_cards task."""
            count = task.payload.get("count", 3)
            slot = task.payload.get("slot", "unknown")

            logger.info(f"Publishing {count} cards (slot: {slot})")

            service = CollectionService(self._pool)
            result = await service.publish_and_sync(count=count)

            logger.info(
                f"Published {result.get('published_count', 0)} cards, "
                f"KV sync: {result.get('sync_result', {}).get('success', False)}"
            )

            return {
                "slot": slot,
                "published_count": result.get("published_count", 0),
                "kv_sync_success": result.get("sync_result", {}).get("success", False),
            }

        async def handle_article_curate(task: ScheduledTask) -> dict[str, Any]:
            """Handle article_curate task.

            Triggers ArticleCurationFlow via Metaflow CLI.

            Uses progress-based idle timeout: the subprocess must produce
            stdout within IDLE_TIMEOUT seconds or it's considered stalled.
            There is no hard wall-clock limit — a flow that keeps printing
            progress can run as long as it needs (render step alone can
            take 15+ minutes for many cards).
            """
            import subprocess
            import select
            import time

            IDLE_TIMEOUT = 300  # 5 minutes without output = stalled

            logger.info("Triggering ArticleCurationFlow...")

            try:
                proc = subprocess.Popen(
                    [
                        "uv", "run", "python", "-m",
                        "gaius.flows.article_curation.flow", "run",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=os.environ.get("GAIUS_ROOT", "/home/rch/local/src/zndx/gaius"),
                )

                last_output = time.monotonic()
                output_lines: list[str] = []
                stdout = proc.stdout
                assert stdout is not None  # guaranteed by stdout=PIPE

                while True:
                    # Wait for output with idle timeout
                    ready, _, _ = select.select(
                        [stdout], [], [], IDLE_TIMEOUT
                    )

                    if ready:
                        line = stdout.readline()
                        if line:
                            last_output = time.monotonic()
                            output_lines.append(line.rstrip())
                            logger.info(f"  ArticleCuration: {line.rstrip()}")
                        elif proc.poll() is not None:
                            # EOF + process exited
                            break
                    else:
                        # No output within idle timeout
                        idle_s = time.monotonic() - last_output
                        if proc.poll() is not None:
                            break  # Already exited
                        logger.error(
                            f"ArticleCurationFlow stalled: no output for {idle_s:.0f}s"
                        )
                        proc.kill()
                        proc.wait()
                        return {
                            "status": "stalled",
                            "idle_seconds": idle_s,
                            "last_lines": output_lines[-10:],
                        }

                retcode = proc.wait()
                if retcode == 0:
                    logger.info("ArticleCurationFlow completed successfully")
                    return {
                        "status": "completed",
                        "returncode": 0,
                        "last_lines": output_lines[-10:],
                    }
                else:
                    logger.error(
                        f"ArticleCurationFlow failed (exit {retcode})"
                    )
                    return {
                        "status": "failed",
                        "returncode": retcode,
                        "last_lines": output_lines[-20:],
                    }

            except Exception as e:
                logger.error(f"ArticleCurationFlow error: {e}")
                return {"status": "error", "error": str(e)}

        self.register_handler("publish_cards", handle_publish_cards)
        self.register_handler("article_curate", handle_article_curate)

    async def _listen_loop(self) -> None:
        """Main LISTEN loop with reconnection."""
        backoff_ms = 500
        max_backoff_ms = 30000

        while self._running:
            try:
                # Dedicated connection for LISTEN
                self._connection = await asyncpg.connect(self._database_url)
                self._connected_at = datetime.now()
                backoff_ms = 500

                logger.info(f"Connected for LISTEN on '{self._channel}'")

                # Register listener
                await self._connection.add_listener(
                    self._channel,
                    self._on_notification,
                )

                # Keep alive
                while self._running and not self._connection.is_closed():
                    await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connection_failures += 1
                logger.warning(f"LISTEN connection lost (#STP.00000001.CONNFAIL): {e}")

                if self._connection:
                    try:
                        await self._connection.close()
                    except Exception:
                        pass
                    self._connection = None
                    self._connected_at = None

                # Exponential backoff
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
        """Handle PostgreSQL notification."""
        logger.debug(f"Received notification: {payload}")
        asyncio.create_task(self._process_notification(payload))

    async def _process_notification(self, payload: str) -> None:
        """Process a notification by picking up and executing the task."""
        try:
            data = json.loads(payload)
            task_id = data.get("id")
            task_type = data.get("task_type")

            if not task_id:
                logger.warning(f"Notification missing task id: {payload}")
                return

            # Check if we have a handler
            if task_type not in self._handlers:
                logger.warning(
                    f"No handler for task type '{task_type}' (#STP.00000003.NOHANDLER)"
                )
                await self._mark_task_error(
                    task_id,
                    f"No handler registered for task type: {task_type}",
                )
                return

            # Pick up and execute task
            await self._execute_task(task_id)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse notification: {e}")
        except Exception as e:
            logger.error(f"Error processing notification: {e}")

    async def _execute_task(self, task_id: int) -> None:
        """Pick up and execute a task.

        Connection management: acquire/release around DB operations only,
        never hold a connection during handler execution. Handlers may need
        their own connections from the same pool.
        """
        # 1. Atomically pick up task (short-lived connection)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE scheduled_tasks
                SET picked_up_at = NOW()
                WHERE id = $1 AND picked_up_at IS NULL
                RETURNING *
                """,
                task_id,
            )

        if not row:
            logger.debug(f"Task {task_id} already picked up or doesn't exist")
            return

        task = ScheduledTask.from_row(row)
        logger.info(f"Executing task {task_id}: {task.task_type}")

        handler = self._handlers.get(task.task_type)
        if not handler:
            await self._mark_task_error(
                task_id,
                f"No handler for task type: {task.task_type}",
            )
            return

        # 2. Execute handler (no connection held — handler manages its own)
        try:
            result = await handler(task)
            self._tasks_processed += 1
            self._last_task_at = datetime.now()

            # 3. Mark complete (short-lived connection)
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE scheduled_tasks
                    SET completed_at = NOW(),
                        result = $2
                    WHERE id = $1
                    """,
                    task_id,
                    json.dumps(result),
                )

            logger.info(f"Task {task_id} completed: {result}")

        except Exception as e:
            self._tasks_failed += 1
            error_msg = str(e)
            logger.error(f"Task {task_id} failed (#STP.00000002.TASKFAIL): {e}")

            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE scheduled_tasks
                    SET completed_at = NOW(),
                        error = $2
                    WHERE id = $1
                    """,
                    task_id,
                    error_msg[:1000],
                )

    async def _mark_task_error(self, task_id: int, error: str) -> None:
        """Mark a task as failed with error."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE scheduled_tasks
                SET completed_at = NOW(),
                    error = $2
                WHERE id = $1
                """,
                task_id,
                error[:1000],
            )

    async def _health_check_loop(self) -> None:
        """Periodic health check."""
        while self._running:
            try:
                await asyncio.sleep(30)

                if self._connection and not self._connection.is_closed():
                    await self._connection.fetchval("SELECT 1")
                    logger.debug("LISTEN health check OK")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Health check failed: {e}")
                if self._connection:
                    try:
                        await self._connection.close()
                    except Exception:
                        pass
                    self._connection = None
