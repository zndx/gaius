"""Scheduled Task Processor - LISTEN/NOTIFY driven task execution.

Processes tasks from the `scheduled_tasks` table when notified by pg_cron.
Uses PostgreSQL LISTEN/NOTIFY for real-time processing while engine is running.

Design:
- LISTEN on 'scheduled_task_ready' channel for immediate pickup
- Task handlers registered by task_type
- Marks tasks complete with result/error
- Prospects check/update catch up on engine start so a recycle
  cannot skip the daily Data Product clock.

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
    Prospects product tasks catch up on start so ``gaius.prospects.corpus``
    stays current across ``signals.target`` recycles.
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
        self._catchup_task: asyncio.Task | None = None

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

    async def _run_spawned_metaflow(
        self,
        *,
        kind: str,
        task: ScheduledTask,
        argv: list[str],
        log_prefix: str,
        idle_timeout: int = 900,
    ) -> dict[str, Any]:
        """Spawn a Metaflow CLI child, register it for Yield, optional YK sentinel."""
        import time

        from gaius.engine.flow_processes import (
            SpawnedFlow,
            flow_processes,
            workload_id_for,
        )
        from gaius.engine.sentinel_claim import (
            YkAdmitError,
            apply_and_admit,
            bind_workload_id,
            delete_flow_sentinel,
        )

        proposed = workload_id_for(kind, task.id)
        try:
            wid = bind_workload_id(kind, proposed)
        except YkAdmitError as e:
            logger.error(f"{log_prefix} YK bind failed: {e}")
            return {"status": "error", "error": str(e), "workload_id": proposed}
        minted = True
        from gaius.flows.config import metaflow_child_env

        # Sentinel-spawned ticks run on this host (YK pause pod + host CUDA).
        # Platform profile (@kubernetes / S3) hangs the step after start.
        env = metaflow_child_env(mode="local")
        env["GAIUS_YK_APPLICATION_ID"] = wid
        env["GAIUS_YK_KIND"] = kind
        cwd = os.environ.get("GAIUS_ROOT", "/home/rch/local/src/zndx/gaius")
        table = flow_processes()
        try:
            apply_and_admit(wid, kind)
        except YkAdmitError as e:
            logger.error(f"{log_prefix} YK admit failed: {e}")
            return {"status": "error", "error": str(e), "workload_id": wid}
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                cwd=cwd,
            )
        except Exception as e:
            logger.error(f"{log_prefix} spawn failed: {e}")
            return {"status": "error", "error": str(e), "workload_id": wid}

        table.register(
            SpawnedFlow(
                workload_id=wid, kind=kind, proc=proc, task_id=task.id
            )
        )
        last_output = time.monotonic()
        output_lines: list[str] = []
        try:
            assert proc.stdout is not None
            while True:
                try:
                    raw = await asyncio.wait_for(
                        proc.stdout.readline(),
                        timeout=idle_timeout,
                    )
                except TimeoutError:
                    idle_s = time.monotonic() - last_output
                    if proc.returncode is not None:
                        break
                    logger.error(f"{log_prefix} stalled: no output for {idle_s:.0f}s")
                    proc.kill()
                    await proc.wait()
                    return {
                        "status": "stalled",
                        "workload_id": wid,
                        "idle_seconds": idle_s,
                        "last_lines": output_lines[-10:],
                    }
                if raw:
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    last_output = time.monotonic()
                    output_lines.append(line)
                    logger.info(f"  {log_prefix}: {line}")
                else:
                    break
            retcode = await proc.wait()
            if table.get(wid) is None and retcode not in (0, None):
                logger.info(f"{log_prefix} yielded workload_id={wid} rc={retcode}")
                return {
                    "status": "yielded",
                    "workload_id": wid,
                    "returncode": retcode,
                    "last_lines": output_lines[-10:],
                }
            if retcode == 0:
                logger.info(f"{log_prefix} completed workload_id={wid}")
                return {
                    "status": "completed",
                    "workload_id": wid,
                    "returncode": 0,
                    "last_lines": output_lines[-10:],
                }
            logger.error(f"{log_prefix} failed (exit {retcode})")
            return {
                "status": "failed",
                "workload_id": wid,
                "returncode": retcode,
                "last_lines": output_lines[-20:],
            }
        except Exception as e:
            logger.error(f"{log_prefix} error: {e}")
            return {"status": "error", "workload_id": wid, "error": str(e)}
        finally:
            # Natural end of the host child. Yield path already unregistered
            # and deleted the claim. Do not delete at spawn.
            if table.get(wid) is not None:
                table.unregister(wid)
                if minted:
                    delete_flow_sentinel(wid)

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

        # Catch-up must not block start(). DaemonRegistry times out at 30s;
        # awaiting prospects_check here cancelled LISTEN on signals.target recycle.
        self._catchup_task = asyncio.create_task(self._run_startup_catchup())

        logger.info(f"ScheduledTaskProcessor started, listening on '{self._channel}'")

    async def _run_startup_catchup(self) -> None:
        try:
            await self._catch_up_prospects()
        except Exception:
            logger.exception("prospects catch-up failed; LISTEN clock still running")
        try:
            await self._catch_up_board_reindex()
        except Exception:
            logger.exception("board reindex catch-up failed; LISTEN clock still running")

    async def stop(self) -> None:
        """Stop the task processor."""
        if not self._running:
            return

        logger.info("Stopping ScheduledTaskProcessor...")
        self._running = False

        # Cancel tasks
        for task in [self._listen_task, self._health_task, self._catchup_task]:
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
            """Handle publish_cards task.

            Enriches unenriched pending cards before publishing so the
            pg_cron critical path is self-sustaining — cards created by
            the curation flow (or backfills) that failed enrichment get
            retried here before each publish slot.
            """
            count = task.payload.get("count", 3)
            slot = task.payload.get("slot", "unknown")

            service = CollectionService(self._pool)

            # Enrich unenriched pending cards first (summaries + images)
            # This ensures the enrichment gate in publish_cards() has
            # candidates to select from, even if the curation flow's
            # enrichment step partially failed or cards were backfilled.
            enrich_result = await service.enrich_pending_cards(limit=count * 2)
            enrich_count = enrich_result.get("enriched_count", 0)
            enrich_failed = enrich_result.get("failed_count", 0)
            if enrich_count or enrich_failed:
                logger.info(
                    f"Pre-publish enrichment (slot={slot}): "
                    f"{enrich_count} enriched, {enrich_failed} failed"
                )

            # Now publish (only fully enriched cards pass the gate)
            logger.info(f"Publishing {count} cards (slot: {slot})")
            result = await service.publish_and_sync(count=count)

            logger.info(
                f"Published {result.get('published_count', 0)} cards, "
                f"KV sync: {result.get('kv_sync', {}).get('success', False)}"
            )

            published = {
                "slot": slot,
                "enriched_count": enrich_count,
                "enriched_failed": enrich_failed,
                "published_count": result.get("published_count", 0),
                "kv_sync_success": result.get("kv_sync", {}).get("success", False),
            }
            from gaius.engine.services.agenda_emit import emit_publish_cards

            emit_publish_cards(published)
            return published

        async def handle_article_curate(task: ScheduledTask) -> dict[str, Any]:
            """ArticleCurationFlow via Metaflow CLI (Yield-visible child)."""
            env = dict(os.environ)
            logger.info(
                "Triggering ArticleCurationFlow "
                f"XAI_API_KEY={'present' if 'XAI_API_KEY' in env else 'MISSING'} "
                f"BRAVE_API_KEY={'present' if 'BRAVE_API_KEY' in env else 'MISSING'}"
            )
            return await self._run_spawned_metaflow(
                kind="article-curate",
                task=task,
                argv=["uv", "run", "python", "-m", "gaius.flows.article_curation.flow", "run"],
                log_prefix="ArticleCuration",
            )

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
                        await self._enqueue_prospects_update(
                            all_symbols, source="prospects_check"
                        )
                else:
                    from gaius.flows.prospects.publish import record_availability

                    avail = record_availability(
                        reason=str(result.get("reason") or "no new filings")
                    )
                    result["availability"] = {
                        k: avail.get(k)
                        for k in (
                            "needs_update",
                            "snapshot_uri",
                            "tx_id",
                            "reason",
                        )
                    }
                    if avail.get("needs_update"):
                        from gaius.flows.prospects.flow import load_watchlist

                        watch = [
                            str(e.get("symbol"))
                            for e in load_watchlist()
                            if e.get("symbol")
                        ]
                        if watch:
                            await self._enqueue_prospects_update(
                                watch, source="prospects_maintain"
                            )

                return {
                    "update_recommended": result.get("update_recommended", False),
                    "reason": result.get("reason", ""),
                    "new_filings_count": result.get("new_filings_count", 0),
                    "symbols_checked": len(result.get("symbols_with_new_filings", [])),
                    "availability": result.get("availability"),
                }
            finally:
                await service.stop()

        async def handle_prospects_update(task: ScheduledTask) -> dict[str, Any]:
            """ProspectsUpdateFlow via Metaflow CLI (Yield-visible child)."""
            symbols = task.payload.get("symbols", [])
            if not symbols:
                logger.warning("prospects_update task has no symbols in payload")
                return {"status": "skipped", "reason": "no symbols"}
            symbols_csv = ",".join(symbols)
            env = dict(os.environ)
            logger.info(
                f"Triggering ProspectsUpdateFlow symbols={symbols_csv} "
                f"FMP_API_KEY={'present' if 'FMP_API_KEY' in env else 'MISSING'} "
                f"XAI_API_KEY={'present' if 'XAI_API_KEY' in env else 'MISSING'}"
            )
            result = await self._run_spawned_metaflow(
                kind="prospects-update",
                task=task,
                argv=[
                    "uv", "run", "python", "-m",
                    "gaius.flows.prospects.update_flow", "run",
                    f"--symbols={symbols_csv}",
                ],
                log_prefix="ProspectsUpdate",
                idle_timeout=3600,
            )
            result["symbols"] = symbols
            from gaius.engine.services.agenda_emit import emit_prospects_update

            emit_prospects_update(result)
            return result

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
        async def handle_board_reindex(task: ScheduledTask) -> dict[str, Any]:
            """Publish the live KB onto current_state. The board IS this row."""
            from gaius.storage.kb_board import (
                build_board_snapshot,
                load_content_index,
                publish_board_snapshot,
            )

            kb_root = str(
                task.payload.get("kb_root")
                or os.environ.get("GAIUS_KB_ROOT", "build/dev")
            )
            snap = build_board_snapshot(
                kb_root, catalog=await load_content_index()
            )
            generation = await publish_board_snapshot(snap)
            if self._pool:
                async with self._pool.acquire() as conn:
                    try:
                        await conn.execute(
                            "SELECT meta.mark_board_reindex_started($1, $2)",
                            generation,
                            snap.n_documents,
                        )
                    except Exception as e:
                        logger.warning("mark_board_reindex_started: %s", e)
            logger.info(
                "board_reindex generation=%s docs=%s iced=%s cells=%s",
                generation,
                snap.n_documents,
                snap.n_iceberg,
                snap.cells_occupied,
            )
            return {**snap.summary(), "generation": generation}

        async def handle_weekly_signals_summary(task: ScheduledTask) -> dict[str, Any]:
            """S2S remotes + week log → scratch YYYY-MM-DD-HHmmss_wWW-summary.md."""
            from gaius.engine.services.weekly_signals_summary import (
                WeeklySummaryError,
                run_weekly_summary,
            )

            previous = bool(task.payload.get("previous", True))
            week = str(task.payload.get("week") or "")
            try:
                result = await run_weekly_summary(
                    week=week,
                    previous=previous and not week,
                )
            except WeeklySummaryError as e:
                logger.error("weekly_signals_summary: %s", e)
                return {"status": "failed", "error": str(e)}
            if self._pool:
                async with self._pool.acquire() as conn:
                    try:
                        await conn.execute(
                            "SELECT meta.mark_weekly_signals_summary_started($1, $2)",
                            result.week.label,
                            result.path,
                        )
                    except Exception as e:
                        logger.warning("mark_weekly_signals_summary_started: %s", e)
            logger.info(
                "weekly_signals_summary week=%s path=%s projects=%s",
                result.week.label,
                result.path,
                ",".join(p.project for p in result.participants),
            )
            await self._enqueue_knowledge_summary(
                week=result.week.label, source="weekly_signals_summary"
            )
            return {
                "status": "completed",
                "week": result.week.label,
                "path": result.path,
                "projects": [p.project for p in result.participants],
                "commits": len(result.commits),
                "notes": len(result.notes),
                "acp_used": result.acp_used,
            }

        async def handle_knowledge_summary(task: ScheduledTask) -> dict[str, Any]:
            """KnowledgeSummaryFlow: ontology + heuristics summary.md (foreach)."""
            week = str(task.payload.get("week") or "")
            section = str(task.payload.get("section") or "")
            argv = [
                "uv",
                "run",
                "python",
                "-m",
                "gaius.flows.summary.flow",
                "run",
            ]
            if week:
                argv.extend(["--week", week])
            if section:
                argv.extend(["--section", section])
            return await self._run_spawned_metaflow(
                kind="knowledge-summary",
                task=task,
                argv=argv,
                log_prefix="KnowledgeSummary",
            )

        self.register_handler("publish_cards", handle_publish_cards)
        self.register_handler("article_curate", handle_article_curate)
        self.register_handler("prospects_check", handle_prospects_check)
        self.register_handler("prospects_update", handle_prospects_update)
        self.register_handler("metabase_sync", handle_metabase_sync)
        self.register_handler("metaagent_audit", handle_metaagent_audit)
        self.register_handler("board_reindex", handle_board_reindex)
        self.register_handler("weekly_signals_summary", handle_weekly_signals_summary)
        self.register_handler("knowledge_summary", handle_knowledge_summary)

        async def handle_feature_probe(task: ScheduledTask) -> dict[str, Any]:
            from .feature_probe import run_probe_batch

            gpu = int(task.payload.get("gpu_index") or 4)
            if not self._pool:
                raise RuntimeError("feature_probe needs db pool")
            return await run_probe_batch(self._pool, gpu_index=gpu)

        self.register_handler("feature_probe", handle_feature_probe)

        async def handle_clt_skos_admit(task: ScheduledTask) -> dict[str, Any]:
            return await self._run_spawned_metaflow(
                kind="clt-skos-admit",
                task=task,
                argv=[
                    "uv",
                    "run",
                    "python",
                    "-m",
                    "gaius.flows.clt_skos.admit",
                    "run",
                    "--scheduled-task-id",
                    str(task.id),
                ],
                log_prefix="CltSkosAdmit",
            )

        async def handle_clt_skos_label(task: ScheduledTask) -> dict[str, Any]:
            return await self._run_spawned_metaflow(
                kind="clt-skos-label",
                task=task,
                argv=[
                    "uv",
                    "run",
                    "python",
                    "-m",
                    "gaius.flows.clt_skos.label",
                    "run",
                    "--scheduled-task-id",
                    str(task.id),
                ],
                log_prefix="CltSkosLabel",
            )

        self.register_handler("clt_skos_admit", handle_clt_skos_admit)
        self.register_handler("clt_skos_label", handle_clt_skos_label)

    async def _enqueue_knowledge_summary(self, *, week: str, source: str) -> None:
        """Fan out KNOWLEDGE pages after the weekly zettel. Does not block it."""
        if not self._pool:
            return
        async with self._pool.acquire() as conn:
            pending_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM scheduled_tasks
                WHERE task_type = 'knowledge_summary'
                  AND picked_up_at IS NULL
                  AND completed_at IS NULL
                """,
            )
            if pending_count:
                logger.info("Skipping knowledge_summary scheduling: %s pending", pending_count)
                return
            await conn.execute(
                """
                INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
                VALUES ('knowledge_summary', $1, $2, NOW())
                """,
                json.dumps({"week": week}),
                source,
            )
        logger.info("Scheduled knowledge_summary from %s week=%s", source, week)

    async def _enqueue_prospects_update(
        self, symbols: list[str], *, source: str
    ) -> None:
        if not self._pool or not symbols:
            return
        async with self._pool.acquire() as conn:
            pending_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM scheduled_tasks
                WHERE task_type = 'prospects_update'
                  AND picked_up_at IS NULL
                  AND completed_at IS NULL
                """,
            )
            if pending_count:
                logger.info(
                    "Skipping prospects_update scheduling: %s pending",
                    pending_count,
                )
                return
            await conn.execute(
                """
                INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
                VALUES ('prospects_update', $1, $2, NOW())
                """,
                json.dumps({"symbols": symbols}),
                source,
            )
        logger.info(
            "Scheduled prospects_update from %s for %s symbols: %s",
            source,
            len(symbols),
            ", ".join(symbols),
        )

    async def _catch_up_prospects(self) -> None:
        """Re-arm the daily clock after engine recycle; run leftover tasks."""
        if not self._pool:
            return
        async with self._pool.acquire() as conn:
            try:
                due = await conn.fetchval("SELECT meta.should_run_prospects_check()")
            except Exception as e:
                logger.warning("prospects cooldown function missing: %s", e)
                due = False
            if due:
                await conn.execute(
                    """
                    INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
                    SELECT 'prospects_check', '{}'::jsonb, 'engine-catchup', NOW()
                    WHERE NOT EXISTS (
                        SELECT 1 FROM scheduled_tasks
                        WHERE task_type = 'prospects_check'
                          AND picked_up_at IS NULL
                          AND completed_at IS NULL
                    )
                    """
                )
            pending = await conn.fetch(
                """
                SELECT id FROM scheduled_tasks
                WHERE task_type IN ('prospects_check', 'prospects_update')
                  AND picked_up_at IS NULL
                  AND completed_at IS NULL
                ORDER BY id
                """
            )
        for row in pending:
            logger.info("prospects catch-up executing task %s", row["id"])
            await self._execute_task(row["id"])

    async def _catch_up_board_reindex(self) -> None:
        """Arm the board clock after recycle so the UI is never an empty cache."""
        if not self._pool:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
                SELECT 'board_reindex', '{}'::jsonb, 'engine-catchup', NOW()
                WHERE NOT EXISTS (
                    SELECT 1 FROM scheduled_tasks
                    WHERE task_type = 'board_reindex'
                      AND picked_up_at IS NULL
                      AND completed_at IS NULL
                )
                """
            )
            pending = await conn.fetch(
                """
                SELECT id FROM scheduled_tasks
                WHERE task_type = 'board_reindex'
                  AND picked_up_at IS NULL
                  AND completed_at IS NULL
                ORDER BY id
                """
            )
        for row in pending:
            logger.info("board_reindex catch-up executing task %s", row["id"])
            await self._execute_task(row["id"])

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

                # Keep alive; pick tasks whose scheduled_for has arrived.
                due_ticks = 0
                while self._running and not self._connection.is_closed():
                    await asyncio.sleep(1)
                    due_ticks += 1
                    if due_ticks >= 15:
                        due_ticks = 0
                        await self._pickup_due()

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

    async def _pickup_due(self) -> None:
        """Run tasks whose scheduled_for is due (NOTIFY fires at INSERT)."""
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id FROM scheduled_tasks
                 WHERE picked_up_at IS NULL
                   AND scheduled_for <= NOW()
                 ORDER BY scheduled_for
                 LIMIT 4
                """
            )
        for r in rows:
            await self._execute_task(int(r["id"]))

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
                WHERE id = $1
                  AND picked_up_at IS NULL
                  AND scheduled_for <= NOW()
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
