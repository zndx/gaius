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
                f"KV sync: {result.get('kv_sync', {}).get('success', False)}"
            )

            return {
                "slot": slot,
                "published_count": result.get("published_count", 0),
                "kv_sync_success": result.get("kv_sync", {}).get("success", False),
            }

        async def handle_article_curate(task: ScheduledTask) -> dict[str, Any]:
            """Handle article_curate task.

            Triggers ArticleCurationFlow via Metaflow CLI.

            Uses async subprocess to avoid blocking the event loop — the
            previous blocking select.select() implementation deadlocked
            the engine's gRPC server, preventing callback requests from
            the flow subprocess (which calls Scheduler.complete for
            cot_reflection inference).

            Progress-based idle timeout: the subprocess must produce
            stdout within IDLE_TIMEOUT seconds or it's considered stalled.
            No hard wall-clock limit — a flow that keeps printing progress
            can run as long as it needs (render step alone can take 15+
            minutes for many cards).
            """
            import time

            # Must exceed the engine's wall-clock timeout (600s) for
            # cot_reflection calls, since the flow prints nothing during
            # long gRPC calls. The engine's idle-timeout (120s) handles
            # stall detection; this is just the subprocess safety net.
            IDLE_TIMEOUT = 900  # 15 minutes without output

            logger.info("Triggering ArticleCurationFlow...")

            # Propagate full environment to subprocess (API keys, etc.)
            env = dict(os.environ)
            has_xai = "XAI_API_KEY" in env
            has_brave = "BRAVE_API_KEY" in env
            logger.info(f"  Subprocess env: XAI_API_KEY={'present' if has_xai else 'MISSING'}, "
                        f"BRAVE_API_KEY={'present' if has_brave else 'MISSING'}, "
                        f"METAFLOW_HOME={env.get('METAFLOW_HOME', 'unset')}")

            try:
                proc = await asyncio.create_subprocess_exec(
                    "uv", "run", "python", "-m",
                    "gaius.flows.article_curation.flow", "run",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env=env,
                    cwd=os.environ.get("GAIUS_ROOT", "/home/rch/local/src/zndx/gaius"),
                )

                last_output = time.monotonic()
                output_lines: list[str] = []

                while True:
                    try:
                        # Async readline — yields control to event loop
                        raw = await asyncio.wait_for(
                            proc.stdout.readline(),
                            timeout=IDLE_TIMEOUT,
                        )
                    except asyncio.TimeoutError:
                        idle_s = time.monotonic() - last_output
                        if proc.returncode is not None:
                            break  # Already exited
                        logger.error(
                            f"ArticleCurationFlow stalled: no output for {idle_s:.0f}s"
                        )
                        proc.kill()
                        await proc.wait()
                        return {
                            "status": "stalled",
                            "idle_seconds": idle_s,
                            "last_lines": output_lines[-10:],
                        }

                    if raw:
                        line = raw.decode("utf-8", errors="replace").rstrip()
                        last_output = time.monotonic()
                        output_lines.append(line)
                        logger.info(f"  ArticleCuration: {line}")
                    else:
                        # EOF — subprocess closed stdout
                        break

                retcode = await proc.wait()
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

        async def handle_prospects_check(task: ScheduledTask) -> dict[str, Any]:
            """Handle prospects_check task — lightweight daily FMP check.

            Creates a fresh ProspectsService, runs the check, and if updates
            are recommended, schedules a prospects_update task with the
            relevant symbols.
            """
            from .prospects_service import ProspectsService, ProspectsConfig

            force = task.payload.get("force", False)
            logger.info(f"Running prospects daily check (force={force})...")

            # Create fresh service with shared pool
            kb_root = os.environ.get("GAIUS_KB_ROOT", "build/dev")
            config = ProspectsConfig(kb_root=kb_root)
            service = ProspectsService(pool=self._pool, config=config)
            await service.start()

            try:
                result = await service.run_check(force=force)

                # Mark cooldown state
                async with self._pool.acquire() as conn:
                    await conn.execute("SELECT meta.mark_prospects_check_started()")

                logger.info(
                    f"Prospects check complete: update_recommended={result.get('update_recommended')}, "
                    f"reason={result.get('reason', 'none')}"
                )

                # If update recommended, schedule prospects_update task
                # (only if no pending prospects_update task exists)
                if result.get("update_recommended"):
                    symbols = result.get("symbols_with_new_filings", [])
                    # Also include symbols with pending analysis/synthesis
                    pending_symbols = list(result.get("pending_analysis_by_symbol", {}).keys())
                    synthesis_symbols = result.get("pending_synthesis_symbols", [])
                    all_symbols = list(set(symbols + pending_symbols + synthesis_symbols))

                    if all_symbols:
                        async with self._pool.acquire() as conn:
                            pending_count = await conn.fetchval(
                                """
                                SELECT COUNT(*) FROM scheduled_tasks
                                WHERE task_type = 'prospects_update'
                                  AND picked_up_at IS NULL
                                  AND completed_at IS NULL
                                """,
                            )

                            if pending_count == 0:
                                await conn.execute(
                                    """
                                    INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
                                    VALUES ('prospects_update', $1, 'prospects_check', NOW())
                                    """,
                                    json.dumps({"symbols": all_symbols}),
                                )
                                logger.info(
                                    f"Scheduled prospects_update for {len(all_symbols)} symbols: "
                                    f"{', '.join(all_symbols)}"
                                )
                            else:
                                logger.info(
                                    f"Skipping prospects_update scheduling: {pending_count} "
                                    f"pending update task(s) already exist"
                                )

                return {
                    "update_recommended": result.get("update_recommended", False),
                    "reason": result.get("reason", ""),
                    "new_filings_count": result.get("new_filings_count", 0),
                    "symbols_checked": len(result.get("symbols_with_new_filings", [])),
                }
            finally:
                await service.stop()

        async def handle_prospects_update(task: ScheduledTask) -> dict[str, Any]:
            """Handle prospects_update task — full billable analysis via subprocess.

            Spawns ProspectsUpdateFlow via uv/Metaflow CLI.
            Uses async subprocess with progress-based idle timeout
            (same pattern as handle_article_curate).
            """
            import time

            IDLE_TIMEOUT = 900  # 15 minutes without output

            symbols = task.payload.get("symbols", [])
            if not symbols:
                logger.warning("prospects_update task has no symbols in payload")
                return {"status": "skipped", "reason": "no symbols"}

            symbols_csv = ",".join(symbols)
            logger.info(f"Triggering ProspectsUpdateFlow for symbols: {symbols_csv}")

            # Propagate full environment to subprocess (API keys, etc.)
            env = dict(os.environ)
            has_fmp = "FMP_API_KEY" in env
            has_xai = "XAI_API_KEY" in env
            logger.info(
                f"  Subprocess env: FMP_API_KEY={'present' if has_fmp else 'MISSING'}, "
                f"XAI_API_KEY={'present' if has_xai else 'MISSING'}"
            )

            try:
                proc = await asyncio.create_subprocess_exec(
                    "uv", "run", "python", "-m",
                    "gaius.flows.prospects.update_flow", "run",
                    f"--symbols={symbols_csv}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env=env,
                    cwd=os.environ.get("GAIUS_ROOT", "/home/rch/local/src/zndx/gaius"),
                )

                last_output = time.monotonic()
                output_lines: list[str] = []

                while True:
                    try:
                        raw = await asyncio.wait_for(
                            proc.stdout.readline(),
                            timeout=IDLE_TIMEOUT,
                        )
                    except asyncio.TimeoutError:
                        idle_s = time.monotonic() - last_output
                        if proc.returncode is not None:
                            break
                        logger.error(
                            f"ProspectsUpdateFlow stalled: no output for {idle_s:.0f}s"
                        )
                        proc.kill()
                        await proc.wait()
                        return {
                            "status": "stalled",
                            "symbols": symbols,
                            "idle_seconds": idle_s,
                            "last_lines": output_lines[-10:],
                        }

                    if raw:
                        line = raw.decode("utf-8", errors="replace").rstrip()
                        last_output = time.monotonic()
                        output_lines.append(line)
                        logger.info(f"  ProspectsUpdate: {line}")
                    else:
                        break

                retcode = await proc.wait()
                if retcode == 0:
                    logger.info("ProspectsUpdateFlow completed successfully")
                    return {
                        "status": "completed",
                        "symbols": symbols,
                        "returncode": 0,
                        "last_lines": output_lines[-10:],
                    }
                else:
                    logger.error(f"ProspectsUpdateFlow failed (exit {retcode})")
                    return {
                        "status": "failed",
                        "symbols": symbols,
                        "returncode": retcode,
                        "last_lines": output_lines[-20:],
                    }

            except Exception as e:
                logger.error(f"ProspectsUpdateFlow error: {e}")
                return {"status": "error", "symbols": symbols, "error": str(e)}

        async def handle_metabase_sync(task: ScheduledTask) -> dict[str, Any]:
            """Handle metabase_sync task — sync Metabase models from PostgreSQL views."""
            from .metaagent_service import get_metaagent_service

            full_refresh = task.payload.get("full_refresh", False)
            logger.info(f"Triggering Metabase sync (full_refresh={full_refresh})")

            svc = get_metaagent_service()
            resp = await svc.trigger_sync(full_refresh=full_refresh)

            if resp.success:
                logger.info(
                    f"Metabase sync completed: {resp.models_synced} models, "
                    f"{resp.dashboards_synced} dashboards"
                )
            else:
                logger.error(f"Metabase sync failed: {resp.error}")

            return {
                "status": "completed" if resp.success else "failed",
                "models_synced": resp.models_synced,
                "dashboards_synced": resp.dashboards_synced,
                "error": resp.error or None,
            }

        async def handle_metaagent_audit(task: ScheduledTask) -> dict[str, Any]:
            """Handle metaagent_audit task — run MetaAgent LLM audit."""
            from .metaagent_service import get_metaagent_service

            scope = task.payload.get("scope", "full")
            use_remote = task.payload.get("use_remote_llm", True)
            logger.info(f"Triggering MetaAgent audit (scope={scope}, remote={use_remote})")

            svc = get_metaagent_service()
            resp = await svc.trigger_audit(scope=scope, use_remote_llm=use_remote)

            if resp.success:
                logger.info(
                    f"MetaAgent audit completed: {len(resp.findings)} findings, "
                    f"{len(resp.recommendations)} recommendations"
                )
            else:
                logger.error(f"MetaAgent audit failed: {resp.error}")

            return {
                "status": "completed" if resp.success else "failed",
                "audit_id": resp.audit_id,
                "findings_count": len(resp.findings),
                "recommendations_count": len(resp.recommendations),
                "error": resp.error or None,
            }

        self.register_handler("publish_cards", handle_publish_cards)
        self.register_handler("article_curate", handle_article_curate)
        self.register_handler("prospects_check", handle_prospects_check)
        self.register_handler("prospects_update", handle_prospects_update)
        self.register_handler("metabase_sync", handle_metabase_sync)
        self.register_handler("metaagent_audit", handle_metaagent_audit)

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
            # If the handler reports failure in result, propagate to error column
            # so health checks correctly identify failed tasks.
            result_status = result.get("status", "completed") if isinstance(result, dict) else "completed"
            error_msg = None
            if result_status in ("failed", "error", "stalled"):
                # Extract error from result for the error column
                if isinstance(result, dict):
                    last_lines = result.get("last_lines", [])
                    error_msg = result.get("error") or (last_lines[-1] if last_lines else f"Handler returned status: {result_status}")
                else:
                    error_msg = f"Handler returned status: {result_status}"
                self._tasks_failed += 1

            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE scheduled_tasks
                    SET completed_at = NOW(),
                        result = $2,
                        error = $3
                    WHERE id = $1
                    """,
                    task_id,
                    json.dumps(result),
                    error_msg[:1000] if error_msg else None,
                )

            if error_msg:
                logger.error(f"Task {task_id} handler failed: {error_msg}")
            else:
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
