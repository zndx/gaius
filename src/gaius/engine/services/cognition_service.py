"""Cognition service for engine daemon mode.

Daemon that processes scheduled cognition tasks from the database,
running cognition cycles and engine audits when triggered by pg_cron
or delta detection.

Task Types Handled:
- cognition_cycle: Run a full cognition cycle (patterns, connections, etc.)
- engine_audit: Audit engine health and record observations
- delta_check: Check for gaps and schedule remediation tasks

BDD Alignment:
- Cognition daemon monitors scheduled_tasks table
- Cognition respects rate limits
- Cognition cycle generates thoughts
- Engine audit records observations
- Delta detection schedules tasks
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class CognitionConfig:
    """Configuration for cognition daemon.

    Controls rate limits, idle detection, and task processing.
    """

    # Rate limiting
    max_cycles_per_hour: int = 4
    min_idle_seconds: int = 60  # Must be idle before running

    # Task processing
    poll_interval_seconds: float = 30.0  # How often to check for tasks
    task_timeout_seconds: int = 300  # Max time for a single task

    # Cognition parameters
    max_thoughts_per_cycle: int = 5
    enable_self_observation: bool = True
    enable_engine_audit: bool = True

    # Database connection
    database_url: str = ""


class CognitionService:
    """Cognition daemon for scheduled thought generation.

    Monitors the scheduled_tasks table and processes cognition-related
    tasks when they become due. Integrates with the CognitionAgent
    for actual thought generation.

    Lifecycle:
    1. Start daemon with start()
    2. Daemon polls scheduled_tasks table
    3. When task is due, picks it up and processes
    4. Marks task complete with result
    5. Stop daemon with stop()

    Task Types:
    - cognition_cycle: Run CognitionAgent.think()
    - engine_audit: Run CognitionAgent._audit_engine_health()
    - delta_check: Run detect_cognition_delta() SQL function
    """

    def __init__(
        self,
        config: CognitionConfig,
        get_gpu_idle: Optional[Callable[[], bool]] = None,
        db_pool: Optional[Any] = None,
    ):
        """Initialize cognition service.

        Args:
            config: Service configuration
            get_gpu_idle: Optional function to check GPU idle state
            db_pool: Optional database connection pool (asyncpg)
        """
        self.config = config
        self._get_gpu_idle = get_gpu_idle or (lambda: True)
        self._db_pool = db_pool

        # Daemon state
        self._running = False
        self._daemon_task: Optional[asyncio.Task] = None

        # Rate limiting
        self._recent_cycles: list[datetime] = []

        # Statistics
        self._cycles_completed = 0
        self._tasks_processed = 0
        self._last_cycle_at: Optional[datetime] = None
        self._current_task: Optional[dict] = None

        # Progress callbacks
        self._progress_callbacks: list[Callable[[str], None]] = []

        logger.info("CognitionService initialized")

    # ─────────────────────────────────────────────────────────────────────────
    # Daemon Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the cognition daemon.

        Begins polling the scheduled_tasks table for work.
        """
        if self._running:
            logger.warning("Cognition daemon already running")
            return

        self._running = True
        self._daemon_task = asyncio.create_task(self._daemon_loop())

        logger.info("Cognition daemon started")

    async def stop(self) -> None:
        """Stop the cognition daemon."""
        if not self._running:
            return

        self._running = False

        if self._daemon_task:
            self._daemon_task.cancel()
            try:
                await self._daemon_task
            except asyncio.CancelledError:
                pass

        logger.info("Cognition daemon stopped")

    async def _daemon_loop(self) -> None:
        """Background daemon loop.

        Polls scheduled_tasks table and processes due tasks.
        """
        while self._running:
            try:
                # Check if GPU is idle (optional)
                if not self._get_gpu_idle():
                    logger.debug("GPU busy, skipping cognition check")
                    await asyncio.sleep(self.config.poll_interval_seconds)
                    continue

                # Try to pick up a pending task
                task = await self._pick_up_task()

                if task:
                    await self._process_task(task)

            except Exception as e:
                logger.error(f"Daemon loop error: {e}")

            await asyncio.sleep(self.config.poll_interval_seconds)

    # ─────────────────────────────────────────────────────────────────────────
    # Task Management
    # ─────────────────────────────────────────────────────────────────────────

    async def _pick_up_task(self) -> Optional[dict]:
        """Pick up the next pending task from the database.

        Uses the pick_up_task() SQL function for atomic claiming.

        Returns:
            Task dict or None if no tasks available
        """
        if not self._db_pool:
            return None

        try:
            async with self._db_pool.acquire() as conn:
                # Call the atomic pick_up_task function
                row = await conn.fetchrow(
                    """
                    SELECT * FROM pick_up_task(ARRAY['cognition_cycle', 'engine_audit', 'delta_check'])
                    """
                )

                if row and row["id"]:
                    return dict(row)
                return None

        except Exception as e:
            logger.error(f"Failed to pick up task: {e}")
            return None

    async def _complete_task(
        self,
        task_id: int,
        result: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> None:
        """Mark a task as completed.

        Args:
            task_id: Task ID to complete
            result: Optional result dict
            error: Optional error message
        """
        if not self._db_pool:
            return

        try:
            import json

            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    SELECT complete_task($1, $2, $3)
                    """,
                    task_id,
                    json.dumps(result) if result else None,
                    error,
                )

        except Exception as e:
            logger.error(f"Failed to complete task {task_id}: {e}")

    async def _process_task(self, task: dict) -> None:
        """Process a single task.

        Routes to appropriate handler based on task_type.

        Args:
            task: Task dict from database
        """
        task_id = task["id"]
        task_type = task["task_type"]
        payload = task.get("payload", {})

        self._current_task = task
        self._tasks_processed += 1

        logger.info(f"Processing task {task_id}: {task_type}")
        self._notify_progress(f"Processing {task_type}")

        try:
            if task_type == "cognition_cycle":
                result = await self._run_cognition_cycle(payload)
            elif task_type == "engine_audit":
                result = await self._run_engine_audit(payload)
            elif task_type == "delta_check":
                result = await self._run_delta_check(payload)
            else:
                raise ValueError(f"Unknown task type: {task_type}")

            await self._complete_task(task_id, result=result)
            logger.info(f"Task {task_id} completed successfully")

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            await self._complete_task(task_id, error=str(e))

        finally:
            self._current_task = None

    # ─────────────────────────────────────────────────────────────────────────
    # Task Handlers
    # ─────────────────────────────────────────────────────────────────────────

    async def _run_cognition_cycle(self, payload: dict) -> dict:
        """Run a full cognition cycle.

        Args:
            payload: Task payload with optional parameters

        Returns:
            Result dict with thoughts generated
        """
        # Check rate limit
        if not self._can_run_cycle():
            return {
                "skipped": True,
                "reason": "rate_limit",
                "cycles_this_hour": len(self._recent_cycles),
            }

        # Record cycle start for rate limiting
        self._recent_cycles.append(datetime.now())

        # Get cognition agent
        from ...agents.cognition import get_cognition_agent

        agent = get_cognition_agent()

        # Extract parameters from payload
        max_thoughts = payload.get("max_thoughts", self.config.max_thoughts_per_cycle)
        trigger_reason = payload.get("trigger", "scheduled")

        # Run cognition cycle
        self._notify_progress("Running cognition cycle...")
        result = await agent.think(
            max_thoughts=max_thoughts,
            trigger_reason=trigger_reason,
        )

        # Update statistics
        self._cycles_completed += 1
        self._last_cycle_at = datetime.now()

        self._notify_progress(
            f"Generated {len(result.thoughts)} thoughts "
            f"({result.patterns_detected} patterns, "
            f"{result.connections_found} connections)"
        )

        return {
            "thoughts_generated": len(result.thoughts),
            "patterns_detected": result.patterns_detected,
            "connections_found": result.connections_found,
            "curiosities_generated": result.curiosities_generated,
            "self_observations": result.self_observations,
            "engine_audits": result.engine_audits,
            "tokens_used": result.tokens_used,
            "duration_ms": result.duration_ms,
        }

    async def _run_engine_audit(self, payload: dict) -> dict:
        """Run engine health audit and record observations.

        Args:
            payload: Task payload (may contain anomaly_count from delta detection)

        Returns:
            Result dict with audit findings
        """
        observations = []
        anomalies_found = 0

        # Collect engine metrics
        try:
            metrics = await self._collect_engine_metrics()
            observations.append({
                "source": "scheduler",
                "metrics": metrics.get("scheduler", {}),
            })
            observations.append({
                "source": "evolution",
                "metrics": metrics.get("evolution", {}),
            })
            observations.append({
                "source": "gpu",
                "metrics": metrics.get("gpu", {}),
            })

            # Detect anomalies
            anomalies = self._detect_anomalies(metrics)
            anomalies_found = len(anomalies)

            # Record observations to database
            if self._db_pool:
                await self._record_observations(observations, anomalies)

        except Exception as e:
            logger.error(f"Engine audit error: {e}")
            return {"error": str(e)}

        # If anomalies found, generate a thought about them
        if anomalies_found > 0 and self.config.enable_engine_audit:
            from ...agents.cognition import get_cognition_agent

            agent = get_cognition_agent()
            context = await agent._gather_context()
            context.engine_observations = observations

            audit_thoughts = await agent._audit_engine_health(context)
            for thought in audit_thoughts:
                await agent._save_thought(thought)

        return {
            "observations_recorded": len(observations),
            "anomalies_found": anomalies_found,
            "anomaly_details": anomalies if anomalies_found else [],
        }

    async def _run_delta_check(self, payload: dict) -> dict:
        """Run delta detection to find gaps needing remediation.

        Calls the detect_cognition_delta() SQL function which
        schedules tasks to fill gaps.

        Args:
            payload: Task payload

        Returns:
            Result dict with tasks scheduled
        """
        if not self._db_pool:
            return {"tasks_scheduled": 0, "reason": "no_database"}

        tasks_scheduled = []

        try:
            async with self._db_pool.acquire() as conn:
                # Call delta detection function
                rows = await conn.fetch(
                    """
                    SELECT task_type, reason FROM detect_cognition_delta($1)
                    """,
                    "default",  # profile
                )

                for row in rows:
                    tasks_scheduled.append({
                        "task_type": row["task_type"],
                        "reason": row["reason"],
                    })

        except Exception as e:
            logger.error(f"Delta check failed: {e}")
            return {"error": str(e)}

        return {
            "tasks_scheduled": len(tasks_scheduled),
            "tasks": tasks_scheduled,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Engine Metrics Collection
    # ─────────────────────────────────────────────────────────────────────────

    async def _collect_engine_metrics(self) -> dict:
        """Collect metrics from engine subsystems.

        Returns:
            Dict with metrics from scheduler, evolution, GPU, etc.
        """
        metrics = {}

        # Try to get scheduler metrics
        try:
            from ..services.scheduler_service import SchedulerService
            # Placeholder - would query actual scheduler
            metrics["scheduler"] = {
                "queue_depth": 0,
                "active_jobs": 0,
                "jobs_completed_hour": 0,
            }
        except Exception as e:
            logger.debug(f"Scheduler metrics unavailable: {e}")

        # Try to get evolution metrics
        try:
            from ..services.evolution_service import EvolutionService
            # Placeholder - would query actual evolution service
            metrics["evolution"] = {
                "running": False,
                "cycles_completed": 0,
                "improvement_pct": 0.0,
            }
        except Exception as e:
            logger.debug(f"Evolution metrics unavailable: {e}")

        # Try to get GPU metrics
        try:
            from ..services.health_service import HealthService
            # Placeholder - would query actual health service
            metrics["gpu"] = {
                "utilization_pct": 0.0,
                "memory_used_pct": 0.0,
                "temperature_c": 0,
            }
        except Exception as e:
            logger.debug(f"GPU metrics unavailable: {e}")

        return metrics

    def _detect_anomalies(self, metrics: dict) -> list[str]:
        """Detect anomalies in engine metrics.

        Args:
            metrics: Collected metrics dict

        Returns:
            List of anomaly descriptions
        """
        anomalies = []

        # Check scheduler
        scheduler = metrics.get("scheduler", {})
        if scheduler.get("queue_depth", 0) > 100:
            anomalies.append(f"High queue depth: {scheduler['queue_depth']}")

        # Check GPU
        gpu = metrics.get("gpu", {})
        if gpu.get("temperature_c", 0) > 80:
            anomalies.append(f"High GPU temperature: {gpu['temperature_c']}°C")
        if gpu.get("memory_used_pct", 0) > 95:
            anomalies.append(f"GPU memory nearly full: {gpu['memory_used_pct']}%")

        return anomalies

    async def _record_observations(
        self,
        observations: list[dict],
        anomalies: list[str],
    ) -> None:
        """Record observations to engine_observations table.

        Args:
            observations: List of observation dicts
            anomalies: List of detected anomalies
        """
        if not self._db_pool:
            return

        try:
            import json

            async with self._db_pool.acquire() as conn:
                for obs in observations:
                    await conn.execute(
                        """
                        INSERT INTO engine_observations (source, metrics, anomalies, notes)
                        VALUES ($1, $2, $3, $4)
                        """,
                        obs.get("source", "unknown"),
                        json.dumps(obs.get("metrics", {})),
                        anomalies if anomalies else [],
                        obs.get("notes"),
                    )

        except Exception as e:
            logger.error(f"Failed to record observations: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Rate Limiting
    # ─────────────────────────────────────────────────────────────────────────

    def _can_run_cycle(self) -> bool:
        """Check if another cognition cycle can run.

        Returns:
            True if within rate limits
        """
        # Clean up old cycle timestamps
        cutoff = datetime.now() - timedelta(hours=1)
        self._recent_cycles = [t for t in self._recent_cycles if t > cutoff]

        return len(self._recent_cycles) < self.config.max_cycles_per_hour

    # ─────────────────────────────────────────────────────────────────────────
    # Manual Trigger
    # ─────────────────────────────────────────────────────────────────────────

    async def trigger(
        self,
        task_type: str = "cognition_cycle",
        payload: Optional[dict] = None,
    ) -> dict:
        """Manually trigger a cognition task.

        Bypasses the scheduled_tasks table and runs immediately.

        Args:
            task_type: Type of task to run
            payload: Optional task payload

        Returns:
            Task result
        """
        payload = payload or {}

        logger.info(f"Manual trigger: {task_type}")

        if task_type == "cognition_cycle":
            payload.setdefault("trigger", "manual")
            return await self._run_cognition_cycle(payload)
        elif task_type == "engine_audit":
            return await self._run_engine_audit(payload)
        elif task_type == "delta_check":
            return await self._run_delta_check(payload)
        else:
            raise ValueError(f"Unknown task type: {task_type}")

    # ─────────────────────────────────────────────────────────────────────────
    # Progress Notification
    # ─────────────────────────────────────────────────────────────────────────

    def subscribe_progress(self, callback: Callable[[str], None]) -> None:
        """Subscribe to progress updates."""
        self._progress_callbacks.append(callback)

    def unsubscribe_progress(self, callback: Callable) -> None:
        """Unsubscribe from progress updates."""
        if callback in self._progress_callbacks:
            self._progress_callbacks.remove(callback)

    def _notify_progress(self, message: str) -> None:
        """Notify subscribers of progress."""
        for callback in self._progress_callbacks:
            try:
                callback(message)
            except Exception as e:
                logger.error(f"Progress callback error: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Status
    # ─────────────────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Get cognition daemon status.

        Returns:
            Status dict with running state, statistics, etc.
        """
        return {
            "running": self._running,
            "status": "RUNNING" if self._running else "STOPPED",
            "cycles_completed": self._cycles_completed,
            "tasks_processed": self._tasks_processed,
            "last_cycle_at": (
                self._last_cycle_at.isoformat() if self._last_cycle_at else None
            ),
            "cycles_this_hour": len(self._recent_cycles),
            "max_cycles_per_hour": self.config.max_cycles_per_hour,
            "current_task": self._current_task,
            "config": {
                "poll_interval_seconds": self.config.poll_interval_seconds,
                "max_thoughts_per_cycle": self.config.max_thoughts_per_cycle,
                "enable_self_observation": self.config.enable_self_observation,
                "enable_engine_audit": self.config.enable_engine_audit,
            },
        }

    async def get_pending_tasks(self, limit: int = 10) -> list[dict]:
        """Get pending scheduled tasks.

        Args:
            limit: Maximum tasks to return

        Returns:
            List of pending task dicts
        """
        if not self._db_pool:
            return []

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, task_type, priority, scheduled_for, source, payload
                    FROM scheduled_tasks
                    WHERE picked_up_at IS NULL
                    ORDER BY
                        CASE priority
                            WHEN 'critical' THEN 0
                            WHEN 'high' THEN 1
                            WHEN 'normal' THEN 2
                            WHEN 'low' THEN 3
                            ELSE 4
                        END,
                        scheduled_for
                    LIMIT $1
                    """,
                    limit,
                )
                return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Failed to get pending tasks: {e}")
            return []

    async def get_recent_completed(self, limit: int = 10) -> list[dict]:
        """Get recently completed tasks.

        Args:
            limit: Maximum tasks to return

        Returns:
            List of completed task dicts
        """
        if not self._db_pool:
            return []

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, task_type, completed_at, result, error
                    FROM scheduled_tasks
                    WHERE completed_at IS NOT NULL
                    ORDER BY completed_at DESC
                    LIMIT $1
                    """,
                    limit,
                )
                return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Failed to get completed tasks: {e}")
            return []

    @property
    def is_running(self) -> bool:
        """Whether daemon is running."""
        return self._running
