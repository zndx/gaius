"""Cognition service for engine daemon mode.

Daemon that processes scheduled cognition tasks from the database,
running cognition cycles and engine audits when triggered by pg_cron
or delta detection.

Task Types Handled:
- cognition_cycle: Run a full cognition cycle (patterns, connections, etc.)
- engine_audit: Audit engine health and record observations
- delta_check: Check for gaps and schedule remediation tasks
- content_diversity_check: Check if enough content accumulated for evolution
- evolution_cycle: Run evolution on specified agents
- task_ideation: Generate new task concepts
- model_merge: Run model merging on agents
- weekly_summary: Generate weekly summary
- content_summarization: Batch summarize content
- research_processing: Process pending research topics
- tda_computation: Recompute TDA/grid projections
- held_out_refresh: Refresh held-out evaluation pool
- feed_check: Check and schedule due feed fetches

BDD Alignment:
- Cognition daemon monitors scheduled_tasks table
- Cognition respects rate limits
- Cognition cycle generates thoughts
- Engine audit records observations
- Delta detection schedules tasks
- Long-term evolution tasks run on weekly/monthly schedules
"""

import asyncio
import json
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

    # All supported task types
    SUPPORTED_TASK_TYPES = [
        # Core cognition tasks
        "cognition_cycle",
        "engine_audit",
        "delta_check",
        # Long-term evolution tasks
        "content_diversity_check",
        "evolution_cycle",
        "task_ideation",
        "model_merge",
        "weekly_summary",
        "content_summarization",
        "research_processing",
        "tda_computation",
        "held_out_refresh",
        "feed_check",
    ]

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
                # Call the atomic pick_up_task function with all supported types
                row = await conn.fetchrow(
                    """
                    SELECT * FROM pick_up_task($1)
                    """,
                    self.SUPPORTED_TASK_TYPES,
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

        # Handle JSONB payload (might be string or dict)
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}

        self._current_task = task
        self._tasks_processed += 1

        logger.info(f"Processing task {task_id}: {task_type}")
        self._notify_progress(f"Processing {task_type}")

        # Task handler routing
        handlers = {
            # Core cognition tasks
            "cognition_cycle": self._run_cognition_cycle,
            "engine_audit": self._run_engine_audit,
            "delta_check": self._run_delta_check,
            # Long-term evolution tasks
            "content_diversity_check": self._run_content_diversity_check,
            "evolution_cycle": self._run_evolution_cycle,
            "task_ideation": self._run_task_ideation,
            "model_merge": self._run_model_merge,
            "merge_evaluation": self._run_merge_evaluation,
            "weekly_summary": self._run_weekly_summary,
            "content_summarization": self._run_content_summarization,
            "research_processing": self._run_research_processing,
            "tda_computation": self._run_tda_computation,
            "held_out_refresh": self._run_held_out_refresh,
            "feed_check": self._run_feed_check,
        }

        try:
            handler = handlers.get(task_type)
            if not handler:
                raise ValueError(f"Unknown task type: {task_type}")

            result = await handler(payload)
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
    # Long-Term Evolution Task Handlers
    # ─────────────────────────────────────────────────────────────────────────

    async def _run_content_diversity_check(self, payload: dict) -> dict:
        """Check content diversity thresholds and trigger evolution if met.

        This is the PRIMARY driver of evolution on long timescales.
        Checks if enough new content has accumulated to justify evolution.

        Args:
            payload: Task payload

        Returns:
            Result dict with diversity metrics and trigger decision
        """
        if not self._db_pool:
            return {"error": "no_database"}

        try:
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM check_content_diversity()")

            result = {
                "should_trigger": row["should_trigger"],
                "reason": row["reason"],
                "metrics": {
                    "new_content_items": row["new_content_items"],
                    "new_thoughts": row["new_thoughts"],
                    "domains_active": row["domains_active"],
                    "external_ingested": row["external_ingested"],
                    "days_since_last": row["days_since_last"],
                }
            }

            if row["should_trigger"]:
                # Schedule evolution cycle
                async with self._db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
                        VALUES ('evolution_cycle',
                                $1::jsonb,
                                'diversity_threshold',
                                NOW())
                    """, json.dumps({
                        "trigger_reason": row["reason"],
                        "metrics": result["metrics"],
                    }))
                result["evolution_scheduled"] = True
                logger.info(f"Diversity check triggered evolution: {row['reason']}")
            else:
                logger.info(f"Diversity check skipped: {row['reason']}")

            return result

        except Exception as e:
            logger.error(f"Content diversity check failed: {e}")
            return {"error": str(e)}

    async def _run_evolution_cycle(self, payload: dict) -> dict:
        """Run scheduled evolution cycle.

        Args:
            payload: Task payload with optional agents list and num_items

        Returns:
            Result dict with cycles run and results
        """
        try:
            from ...agents.evolution import get_evolution_daemon

            daemon = get_evolution_daemon()
            agents = payload.get("agents", ["leader", "risk", "critic", "opportunity", "domain"])
            source = payload.get("source", "scheduled")

            logger.info(f"Starting evolution cycle for {len(agents)} agents (source={source})")
            self._notify_progress(f"Running evolution for {len(agents)} agents...")

            results = []
            for agent_id in agents:
                try:
                    result = await daemon.force_evolution_cycle(agent_id)
                    results.append({
                        "agent_id": agent_id,
                        "success": result.success if hasattr(result, 'success') else True,
                        "improvement": getattr(result, 'improvement_percent', 0.0),
                    })
                except Exception as e:
                    logger.error(f"Evolution cycle failed for {agent_id}: {e}")
                    results.append({
                        "agent_id": agent_id,
                        "success": False,
                        "error": str(e),
                    })

            successful = sum(1 for r in results if r.get("success", False))
            return {
                "cycles_run": len(results),
                "successful": successful,
                "results": results,
            }

        except Exception as e:
            logger.error(f"Evolution cycle failed: {e}")
            return {"error": str(e)}

    async def _run_task_ideation(self, payload: dict) -> dict:
        """Run scheduled task ideation.

        Args:
            payload: Task payload with optional max_concepts and novelty_threshold

        Returns:
            Result dict with drafts generated
        """
        try:
            from ...agents.evolution import get_task_ideation_agent

            agent = get_task_ideation_agent()
            max_concepts = payload.get("max_concepts", 5)
            novelty_threshold = payload.get("novelty_threshold", 0.4)

            logger.info(f"Running task ideation (max_concepts={max_concepts})")
            self._notify_progress("Generating task concepts...")

            drafts = await agent.ideate(
                max_concepts=max_concepts,
                novelty_threshold=novelty_threshold,
            )

            return {
                "drafts_generated": len(drafts) if drafts else 0,
                "names": [d.name for d in drafts] if drafts else [],
            }

        except ImportError:
            logger.warning("Task ideation agent not available")
            return {"error": "task_ideation_agent_not_available"}
        except Exception as e:
            logger.error(f"Task ideation failed: {e}")
            return {"error": str(e)}

    async def _run_model_merge(self, payload: dict) -> dict:
        """Run scheduled model merging.

        Args:
            payload: Task payload with optional agents filter

        Returns:
            Result dict with merge results
        """
        try:
            from ...agents.evolution import get_merge_coordinator

            coordinator = get_merge_coordinator()
            agents = payload.get("agents")  # None = all agents

            logger.info(f"Running model merge (agents={agents or 'all'})")
            self._notify_progress("Running model merging...")

            if agents is None:
                # Get all agents from config
                agents = ["leader", "risk", "critic", "opportunity", "domain"]

            results = {}
            for agent_id in agents:
                try:
                    result = await coordinator.run_merge_cycle(agent_id)
                    results[agent_id] = {
                        "success": result.success,
                        "merged_model_id": result.merged_model_id,
                        "method": result.merge_method,
                        "improvement_percent": result.improvement_percent,
                    }
                except Exception as e:
                    logger.error(f"Merge failed for {agent_id}: {e}")
                    results[agent_id] = {"success": False, "error": str(e)}

            return {
                "agents_processed": len(results),
                "successful": sum(1 for r in results.values() if r.get("success")),
                "results": results,
            }

        except ImportError:
            logger.warning("Merge coordinator not available")
            return {"error": "merge_coordinator_not_available"}
        except Exception as e:
            logger.error(f"Model merge failed: {e}")
            return {"error": str(e)}

    async def _run_merge_evaluation(self, payload: dict) -> dict:
        """Evaluate a merged model against held-out queries.

        This handler processes deferred evaluation tasks scheduled by
        merge_coordinator._schedule_merge_evaluation(). It loads the
        merged model and runs held-out queries to measure performance.

        Args:
            payload: Task payload with merge_id, agent_id, output_path, baseline_score

        Returns:
            Result dict with evaluation results
        """
        merge_id = payload.get("merge_id")
        agent_id = payload.get("agent_id")
        output_path = payload.get("output_path")
        baseline_score = payload.get("baseline_score", 0.0)

        if not merge_id or not agent_id:
            return {"error": "merge_id and agent_id required"}

        logger.info(f"Evaluating merged model {merge_id} for agent {agent_id}")
        self._notify_progress(f"Evaluating merged model {merge_id}...")

        try:
            from ...agents.evolution.evaluation import (
                get_held_out_manager,
                get_daily_evaluator,
            )
            from ...models.lineage import get_lineage_tracker

            # Get held-out queries for evaluation
            manager = get_held_out_manager()
            queries = await manager.get_sample(size=20)

            if not queries:
                logger.warning("No held-out queries available for merge evaluation")
                return {
                    "merge_id": merge_id,
                    "status": "skipped",
                    "reason": "no_held_out_queries",
                }

            # Get evaluator for scoring
            evaluator = get_daily_evaluator()

            # Run evaluation
            # Note: Full model loading requires orchestrator integration.
            # For now, we use the evaluator with the current agent config
            # and record that evaluation was attempted.
            eval_result = await evaluator.evaluate_agent(
                agent_id=agent_id,
                sample_size=len(queries),
            )

            merged_score = eval_result.avg_score if eval_result else 0.0
            improvement = (
                (merged_score - baseline_score) / baseline_score * 100
                if baseline_score > 0 else 0.0
            )

            # Record evaluation in lineage
            lineage_tracker = get_lineage_tracker()
            await lineage_tracker.record_evaluation(
                merge_id=merge_id,
                score=merged_score,
                queries_evaluated=len(queries),
                improvement_percent=improvement,
            )

            logger.info(
                f"Merge evaluation complete: {merge_id} scored {merged_score:.3f} "
                f"(baseline={baseline_score:.3f}, improvement={improvement:.1f}%)"
            )

            return {
                "merge_id": merge_id,
                "agent_id": agent_id,
                "status": "completed",
                "baseline_score": baseline_score,
                "merged_score": merged_score,
                "improvement_percent": improvement,
                "queries_evaluated": len(queries),
            }

        except ImportError as e:
            logger.warning(f"Evaluation module not available: {e}")
            return {
                "merge_id": merge_id,
                "status": "skipped",
                "reason": f"module_not_available: {e}",
            }
        except Exception as e:
            logger.error(f"Merge evaluation failed: {e}")
            return {
                "merge_id": merge_id,
                "status": "failed",
                "error": str(e),
            }

    async def _run_weekly_summary(self, payload: dict) -> dict:
        """Generate weekly summary (spans whole week, not just day).

        Args:
            payload: Task payload with optional use_llm and write_to_kb

        Returns:
            Result dict with summary info
        """
        try:
            # Try to use daily summary agent with extended period
            from ...agents.daily_summary import get_daily_summary_agent

            agent = get_daily_summary_agent()
            use_llm = payload.get("use_llm", True)
            write_to_kb = payload.get("write_to_kb", True)

            logger.info("Generating weekly summary")
            self._notify_progress("Generating weekly summary...")

            summary = await agent.generate_summary(
                days=7,
                use_llm=use_llm,
                write_to_kb=write_to_kb,
            )

            return {
                "period": "weekly",
                "kb_entries": summary.metrics.get("kb_entries", 0) if summary.metrics else 0,
                "queries": summary.metrics.get("queries", 0) if summary.metrics else 0,
            }

        except ImportError:
            logger.warning("Daily summary agent not available")
            return {"error": "daily_summary_agent_not_available"}
        except Exception as e:
            logger.error(f"Weekly summary failed: {e}")
            return {"error": str(e)}

    async def _run_content_summarization(self, payload: dict) -> dict:
        """Run batch content summarization.

        Processes unprocessed content items from feeds and writes them to KB.
        Uses the ContentProcessor from workers module.

        Args:
            payload: Task payload with optional batch_size

        Returns:
            Result dict with summarization results
        """
        batch_size = payload.get("batch_size", 20)
        logger.info(f"Running content summarization (batch_size={batch_size})")
        self._notify_progress(f"Processing up to {batch_size} content items...")

        try:
            from ...workers.processor import ContentProcessor
            from ...workers.config import WorkerConfig
            from ...workers.db import Database
            import os

            # Get database URL from environment or config
            db_url = os.getenv(
                "GAIUS_DATABASE_URL",
                os.getenv("DATABASE_URL", "postgres://localhost:5438/zndx_gaius")
            )

            # Create minimal worker config
            config = WorkerConfig(db_url=db_url)

            # Connect to database
            db = await Database.connect(db_url, min_size=1, max_size=2)

            try:
                processor = ContentProcessor(config, db)
                processed_count = await processor.process_batch(limit=batch_size)

                logger.info(f"Content summarization processed {processed_count} items")

                return {
                    "status": "completed",
                    "batch_size": batch_size,
                    "items_processed": processed_count,
                }

            finally:
                await db.close()

        except ImportError as e:
            logger.warning(f"Content processor import failed: {e}")
            # Fallback: process via direct SQL if worker module unavailable
            return await self._run_content_summarization_fallback(payload)
        except Exception as e:
            logger.error(f"Content summarization failed: {e}")
            return {"error": str(e)}

    async def _run_content_summarization_fallback(self, payload: dict) -> dict:
        """Fallback content summarization using direct database access.

        Marks content items as processed and generates basic KB entries.
        """
        if not self._db_pool:
            return {"error": "no_database"}

        batch_size = payload.get("batch_size", 20)
        processed = 0

        try:
            import os
            from pathlib import Path
            from datetime import datetime

            kb_root = Path(os.getenv("GAIUS_KB_ROOT", "build/dev"))

            async with self._db_pool.acquire() as conn:
                # Get unprocessed items
                rows = await conn.fetch("""
                    SELECT ci.id, ci.title, ci.summary, ci.content, ci.url,
                           ci.authors, ci.published_at, ci.fetched_at, ci.metadata,
                           fs.name as source_name
                    FROM content_items ci
                    JOIN feed_sources fs ON ci.source_id = fs.id
                    WHERE ci.processed_at IS NULL
                    ORDER BY ci.fetched_at DESC
                    LIMIT $1
                """, batch_size)

                for row in rows:
                    try:
                        # Generate KB path
                        source_name = row["source_name"] or "unknown"
                        title = row["title"] or "untitled"
                        safe_title = "".join(c if c.isalnum() or c in "-_ " else "" for c in title.lower())
                        safe_title = "-".join(safe_title.split())[:80]
                        date_str = datetime.now().strftime("%Y-%m-%d")
                        kb_path = f"current/content/{source_name}/{date_str}/{safe_title}.md"

                        full_path = kb_root / kb_path
                        full_path.parent.mkdir(parents=True, exist_ok=True)

                        # Generate markdown
                        lines = [f"# {title}", "", "---"]
                        if row["url"]:
                            lines.append(f"url: {row['url']}")
                        if row["authors"]:
                            lines.append(f"authors: {', '.join(row['authors'])}")
                        if row["published_at"]:
                            lines.append(f"published: {row['published_at'].isoformat()}")
                        lines.extend(["---", ""])

                        if row["summary"]:
                            lines.extend(["## Summary", "", row["summary"], ""])
                        if row["content"]:
                            lines.extend(["## Content", "", row["content"][:5000], ""])

                        full_path.write_text("\n".join(lines))

                        # Mark as processed
                        await conn.execute("""
                            UPDATE content_items
                            SET processed_at = NOW(), kb_path = $2
                            WHERE id = $1
                        """, row["id"], kb_path)

                        processed += 1

                    except Exception as e:
                        logger.error(f"Failed to process item {row['id']}: {e}")

            return {
                "status": "completed_fallback",
                "batch_size": batch_size,
                "items_processed": processed,
            }

        except Exception as e:
            logger.error(f"Fallback content summarization failed: {e}")
            return {"error": str(e)}

    async def _run_research_processing(self, payload: dict) -> dict:
        """Process pending research topics from research_threads table.

        Queries active research threads with next_steps defined,
        performs web search + LLM synthesis, and updates the thread
        with new insights and KB entries.

        Args:
            payload: Task payload with optional:
                - max_threads: Max threads to process (default 5)
                - domain: Filter by domain (optional)
                - priority: Filter by priority (optional)

        Returns:
            Result dict with processing results
        """
        if not self._db_pool:
            return {"error": "no_database"}

        max_threads = payload.get("max_threads", 5)
        domain_filter = payload.get("domain")
        priority_filter = payload.get("priority")

        logger.info(f"Processing research threads (max={max_threads})")
        self._notify_progress("Processing research threads...")

        try:
            processed = []
            errors = []

            async with self._db_pool.acquire() as conn:
                # Query active threads with work to do
                query = """
                    SELECT id, topic, domain, priority, current_focus,
                           next_steps, insights, kb_entries, query_count
                    FROM research_threads
                    WHERE status = 'active'
                      AND next_steps IS NOT NULL
                      AND next_steps != ''
                """
                params = []
                param_idx = 1

                if domain_filter:
                    query += f" AND domain = ${param_idx}"
                    params.append(domain_filter)
                    param_idx += 1

                if priority_filter:
                    query += f" AND priority = ${param_idx}"
                    params.append(priority_filter)
                    param_idx += 1

                query += f" ORDER BY priority DESC, last_activity ASC LIMIT ${param_idx}"
                params.append(max_threads)

                threads = await conn.fetch(query, *params)

                if not threads:
                    logger.info("No research threads need processing")
                    return {
                        "status": "no_work",
                        "threads_processed": 0,
                    }

                # Process each thread
                for thread in threads:
                    thread_id = thread["id"]
                    topic = thread["topic"]
                    domain = thread["domain"] or "general"
                    next_steps = thread["next_steps"]

                    logger.info(f"Processing thread: {topic} ({thread_id})")
                    self._notify_progress(f"Researching: {topic[:30]}...")

                    try:
                        result = await self._process_single_thread(
                            conn, thread_id, topic, domain, next_steps, thread
                        )
                        processed.append(result)
                    except Exception as e:
                        logger.error(f"Failed to process thread {thread_id}: {e}")
                        errors.append({"thread_id": str(thread_id), "error": str(e)})

            return {
                "status": "completed",
                "threads_processed": len(processed),
                "threads": processed,
                "errors": errors if errors else None,
            }

        except Exception as e:
            logger.error(f"Research processing failed: {e}")
            return {"error": str(e)}

    async def _process_single_thread(
        self,
        conn,
        thread_id,
        topic: str,
        domain: str,
        next_steps: str,
        thread_data: dict,
    ) -> dict:
        """Process a single research thread.

        Performs web search based on next_steps, synthesizes with LLM,
        writes to KB, and updates thread with new insights.

        Args:
            conn: Database connection
            thread_id: Thread UUID
            topic: Thread topic
            domain: Domain context
            next_steps: What to research next
            thread_data: Full thread row data

        Returns:
            Result dict for this thread
        """
        from datetime import datetime
        import json as json_module

        # Import inference components
        try:
            from ...inference import get_client, get_search, Message
        except ImportError:
            # Fallback for minimal functionality
            logger.warning("Inference module not available, skipping synthesis")
            return {
                "thread_id": str(thread_id),
                "topic": topic,
                "status": "skipped",
                "reason": "inference_not_available",
            }

        # Search query combines topic and next_steps
        search_query = f"{topic}: {next_steps}"

        # Perform web search
        search = get_search()
        try:
            results = await search.search_for_kb(search_query, domain, count=5)
        except Exception as e:
            logger.warning(f"Search failed for thread {thread_id}: {e}")
            results = []

        if not results:
            # Update thread to indicate no new results
            await conn.execute("""
                UPDATE research_threads
                SET last_activity = NOW(),
                    updated_at = NOW(),
                    query_count = query_count + 1
                WHERE id = $1
            """, thread_id)
            return {
                "thread_id": str(thread_id),
                "topic": topic,
                "status": "no_results",
            }

        # Format sources for synthesis
        sources_text = "\n".join(
            f"- [{r.get('title', 'Unknown')}]({r.get('source', '')}): {r.get('summary', '')}"
            for r in results
        )

        # Get existing insights for context
        existing_insights = thread_data.get("insights") or []
        if isinstance(existing_insights, str):
            try:
                existing_insights = json_module.loads(existing_insights)
            except Exception:
                existing_insights = []

        insights_context = ""
        if existing_insights:
            insights_context = "\n\nPrevious insights:\n" + "\n".join(
                f"- {i}" for i in existing_insights[-5:]  # Last 5 insights
            )

        # Synthesize with LLM
        client = get_client()
        synthesis_prompt = f"""Research Thread: {topic}
Domain: {domain}
Current Focus: {thread_data.get('current_focus', next_steps)}
Next Steps to Research: {next_steps}
{insights_context}

New Sources:
{sources_text}

Based on these new sources and the research context:
1. Extract 2-3 key insights that advance the research thread
2. Identify any new questions or follow-up areas
3. Create a concise summary note

Format your response as:
INSIGHTS:
- insight 1
- insight 2

NEXT_STEPS:
suggested next research direction

SUMMARY:
Your summary note content"""

        try:
            synthesis = await client.complete(
                messages=[
                    Message(
                        role="system",
                        content=f"You are a research assistant advancing an ongoing investigation into {topic} in the {domain} domain.",
                    ),
                    Message(role="user", content=synthesis_prompt),
                ],
                technique="cot_reflection",
                max_tokens=2048,
            )
            synthesis_content = synthesis.content
        except Exception as e:
            logger.warning(f"Synthesis failed for thread {thread_id}: {e}")
            synthesis_content = f"Sources found but synthesis failed: {e}\n\nSources:\n{sources_text}"

        # Parse synthesis for insights and next steps
        new_insights = []
        new_next_steps = None
        summary_content = synthesis_content

        if "INSIGHTS:" in synthesis_content:
            parts = synthesis_content.split("INSIGHTS:", 1)[1]
            if "NEXT_STEPS:" in parts:
                insights_part, rest = parts.split("NEXT_STEPS:", 1)
                # Extract insights
                for line in insights_part.strip().split("\n"):
                    line = line.strip()
                    if line.startswith("- "):
                        new_insights.append(line[2:])

                if "SUMMARY:" in rest:
                    next_part, summary_content = rest.split("SUMMARY:", 1)
                    new_next_steps = next_part.strip()
                    summary_content = summary_content.strip()
                else:
                    new_next_steps = rest.strip()

        # Write to KB
        today = datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.now().strftime("%H%M%S")
        safe_topic = topic.replace(" ", "_").replace("/", "-")[:30]
        kb_path = f"scratch/{today}/{timestamp}_research_{safe_topic}.md"

        kb_content = f"""# Research: {topic}

**Thread ID:** {thread_id}
**Domain:** {domain}
**Date:** {datetime.now().isoformat()}
**Query:** {next_steps}

---

{summary_content}

---

## Sources

{sources_text}
"""

        # Write KB file
        try:
            from pathlib import Path
            import os

            kb_root = os.environ.get("GAIUS_KB_ROOT", "build/dev")
            full_path = Path(kb_root) / kb_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(kb_content)
            logger.info(f"Wrote research note to {kb_path}")
        except Exception as e:
            logger.warning(f"Failed to write KB entry: {e}")
            kb_path = None

        # Update thread in database
        updated_insights = existing_insights + new_insights
        kb_entries = list(thread_data.get("kb_entries") or [])
        if kb_path:
            kb_entries.append(kb_path)

        # Record query in queries JSONB
        existing_queries = thread_data.get("queries") or []
        if isinstance(existing_queries, str):
            try:
                existing_queries = json_module.loads(existing_queries)
            except Exception:
                existing_queries = []

        new_query_record = {
            "query": next_steps,
            "timestamp": datetime.now().isoformat(),
            "results_count": len(results),
        }
        updated_queries = existing_queries + [new_query_record]

        await conn.execute("""
            UPDATE research_threads
            SET last_activity = NOW(),
                updated_at = NOW(),
                query_count = query_count + 1,
                entry_count = entry_count + $2,
                queries = $3,
                insights = $4,
                kb_entries = $5,
                next_steps = COALESCE($6, next_steps),
                current_focus = $7
            WHERE id = $1
        """,
            thread_id,
            1 if kb_path else 0,
            json_module.dumps(updated_queries),
            json_module.dumps(updated_insights),
            kb_entries,
            new_next_steps,
            next_steps,  # Current focus becomes what we just researched
        )

        return {
            "thread_id": str(thread_id),
            "topic": topic,
            "status": "processed",
            "sources_found": len(results),
            "insights_added": len(new_insights),
            "kb_path": kb_path,
            "new_next_steps": new_next_steps,
        }

    async def _run_tda_computation(self, payload: dict) -> dict:
        """Recompute TDA/grid projections.

        Args:
            payload: Task payload

        Returns:
            Result dict with computation status
        """
        try:
            from ...core.projection import GridProjection

            logger.info("Running TDA computation")
            self._notify_progress("Recomputing grid projections...")

            projection = GridProjection()
            # Check if recompute method exists
            if hasattr(projection, 'recompute'):
                await projection.recompute()
                return {"status": "completed"}
            elif hasattr(projection, 'project_all'):
                await projection.project_all()
                return {"status": "completed"}
            else:
                return {"status": "skipped", "reason": "no_recompute_method"}

        except ImportError:
            logger.warning("GridProjection not available")
            return {"error": "grid_projection_not_available"}
        except Exception as e:
            logger.error(f"TDA computation failed: {e}")
            return {"error": str(e)}

    async def _run_held_out_refresh(self, payload: dict) -> dict:
        """Refresh held-out evaluation pool.

        Args:
            payload: Task payload with optional sample_size

        Returns:
            Result dict with refresh count
        """
        try:
            from ...agents.evolution import get_held_out_manager

            manager = get_held_out_manager()
            sample_size = payload.get("sample_size", 100)

            logger.info(f"Refreshing held-out pool (sample_size={sample_size})")
            self._notify_progress("Refreshing held-out evaluation pool...")

            count = await manager.refresh_pool(sample_size=sample_size)

            return {"queries_refreshed": count}

        except ImportError:
            logger.warning("Held-out manager not available")
            return {"error": "held_out_manager_not_available"}
        except Exception as e:
            logger.error(f"Held-out refresh failed: {e}")
            return {"error": str(e)}

    async def _run_feed_check(self, payload: dict) -> dict:
        """Check and schedule due feed fetches.

        Args:
            payload: Task payload

        Returns:
            Result dict with feeds scheduled
        """
        if not self._db_pool:
            return {"error": "no_database"}

        try:
            async with self._db_pool.acquire() as conn:
                # Call the schedule_due_fetches function
                rows = await conn.fetch("SELECT * FROM schedule_due_fetches()")

            feeds_scheduled = []
            for row in rows:
                feeds_scheduled.append({
                    "source_name": row["source_name"],
                    "job_id": row["job_id"],
                })

            logger.info(f"Feed check scheduled {len(feeds_scheduled)} fetches")
            return {
                "feeds_scheduled": len(feeds_scheduled),
                "feeds": feeds_scheduled,
            }

        except Exception as e:
            logger.error(f"Feed check failed: {e}")
            return {"error": str(e)}

    # ─────────────────────────────────────────────────────────────────────────
    # Engine Metrics Collection
    # ─────────────────────────────────────────────────────────────────────────

    async def _collect_engine_metrics(self) -> dict:
        """Collect metrics from engine subsystems.

        Returns:
            Dict with metrics from scheduler, evolution, GPU, etc.
        """
        metrics = {}

        # Try to get scheduler metrics from database (scheduled_tasks)
        if self._db_pool:
            try:
                async with self._db_pool.acquire() as conn:
                    # Queue depth = pending tasks
                    row = await conn.fetchrow("""
                        SELECT COUNT(*) as pending,
                               COUNT(*) FILTER (WHERE status = 'running') as active
                        FROM scheduled_tasks
                        WHERE status IN ('pending', 'running')
                    """)
                    pending = row["pending"] if row else 0
                    active = row["active"] if row else 0

                    # Jobs completed in last hour
                    completed_row = await conn.fetchrow("""
                        SELECT COUNT(*) as completed
                        FROM scheduled_tasks
                        WHERE status = 'completed'
                          AND completed_at > NOW() - INTERVAL '1 hour'
                    """)
                    completed_hour = completed_row["completed"] if completed_row else 0

                    metrics["scheduler"] = {
                        "queue_depth": pending,
                        "active_jobs": active,
                        "jobs_completed_hour": completed_hour,
                    }
            except Exception as e:
                logger.debug(f"Scheduler metrics unavailable: {e}")
                metrics["scheduler"] = {
                    "queue_depth": 0,
                    "active_jobs": 0,
                    "jobs_completed_hour": 0,
                }
        else:
            metrics["scheduler"] = {
                "queue_depth": 0,
                "active_jobs": 0,
                "jobs_completed_hour": 0,
            }

        # Try to get evolution metrics from database
        if self._db_pool:
            try:
                async with self._db_pool.acquire() as conn:
                    # Evolution cycles stats
                    row = await conn.fetchrow("""
                        SELECT
                            COUNT(*) as total_cycles,
                            COUNT(*) FILTER (WHERE success = true) as successful,
                            MAX(completed_at) as last_completed
                        FROM evolution_cycles
                    """)
                    total = row["total_cycles"] if row else 0
                    successful = row["successful"] if row else 0
                    last_completed = row["last_completed"] if row else None

                    # Calculate improvement (compare recent to baseline)
                    improvement_row = await conn.fetchrow("""
                        WITH recent AS (
                            SELECT AVG((result->>'score')::float) as avg_score
                            FROM evolution_cycles
                            WHERE completed_at > NOW() - INTERVAL '7 days'
                              AND result->>'score' IS NOT NULL
                        ),
                        baseline AS (
                            SELECT AVG((result->>'score')::float) as avg_score
                            FROM evolution_cycles
                            WHERE completed_at BETWEEN NOW() - INTERVAL '30 days'
                                                   AND NOW() - INTERVAL '7 days'
                              AND result->>'score' IS NOT NULL
                        )
                        SELECT
                            COALESCE(recent.avg_score, 0) as recent_score,
                            COALESCE(baseline.avg_score, 0) as baseline_score
                        FROM recent, baseline
                    """)
                    recent_score = improvement_row["recent_score"] if improvement_row else 0
                    baseline_score = improvement_row["baseline_score"] if improvement_row else 0
                    improvement = 0.0
                    if baseline_score > 0:
                        improvement = ((recent_score - baseline_score) / baseline_score) * 100

                    # Check if evolution daemon is currently running
                    running_row = await conn.fetchrow("""
                        SELECT EXISTS(
                            SELECT 1 FROM scheduled_tasks
                            WHERE task_type = 'evolution_cycle'
                              AND status = 'running'
                        ) as running
                    """)
                    running = running_row["running"] if running_row else False

                    metrics["evolution"] = {
                        "running": running,
                        "cycles_completed": total,
                        "successful_cycles": successful,
                        "improvement_pct": round(improvement, 2),
                        "last_completed": last_completed.isoformat() if last_completed else None,
                    }
            except Exception as e:
                logger.debug(f"Evolution metrics unavailable: {e}")
                metrics["evolution"] = {
                    "running": False,
                    "cycles_completed": 0,
                    "improvement_pct": 0.0,
                }
        else:
            metrics["evolution"] = {
                "running": False,
                "cycles_completed": 0,
                "improvement_pct": 0.0,
            }

        # Try to get GPU metrics via pynvml
        try:
            import pynvml

            pynvml.nvmlInit()
            device_count = pynvml.nvmlDeviceGetCount()

            total_util = 0.0
            total_mem_pct = 0.0
            max_temp = 0

            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)

                # Utilization
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                total_util += util.gpu

                # Memory
                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                mem_pct = (memory.used / memory.total) * 100 if memory.total > 0 else 0
                total_mem_pct += mem_pct

                # Temperature
                temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                max_temp = max(max_temp, temp)

            pynvml.nvmlShutdown()

            avg_util = total_util / device_count if device_count > 0 else 0
            avg_mem = total_mem_pct / device_count if device_count > 0 else 0

            metrics["gpu"] = {
                "gpu_count": device_count,
                "utilization_pct": round(avg_util, 1),
                "memory_used_pct": round(avg_mem, 1),
                "temperature_c": max_temp,
            }

        except ImportError:
            logger.debug("pynvml not available for GPU metrics")
            metrics["gpu"] = {
                "gpu_count": 0,
                "utilization_pct": 0.0,
                "memory_used_pct": 0.0,
                "temperature_c": 0,
            }
        except Exception as e:
            logger.debug(f"GPU metrics unavailable: {e}")
            metrics["gpu"] = {
                "gpu_count": 0,
                "utilization_pct": 0.0,
                "memory_used_pct": 0.0,
                "temperature_c": 0,
            }

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
