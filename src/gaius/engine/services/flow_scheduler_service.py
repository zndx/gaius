"""Flow Scheduler Service for autonomous Metaflow pipeline execution.

Monitors for new content items and triggers appropriate flows:
- ArxivDoclingFlow for new arxiv papers
- Future: Other flows for RSS, BioRxiv, etc.

Design:
- Polls content_items table for unprocessed items
- Runs flows via subprocess (same as CLI)
- Tracks processed items to avoid duplicates
- GPU-aware: integrates with OrchestratorService for endpoint eviction/recovery

Transient Workload Coordination:
- Flow workloads (docling) can request GPU resources via OrchestratorService
- Idle vLLM endpoints may be evicted to make room for transient workloads
- After flow completion, evicted endpoints are automatically restored
- Uses Yunikorn-style workload management for fair resource sharing
"""

import asyncio
import logging
import os
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

import asyncpg

if TYPE_CHECKING:
    from .orchestrator_service import OrchestratorService

logger = logging.getLogger(__name__)


class FlowType(str, Enum):
    """Types of flows that can be scheduled."""

    ARXIV_DOCLING = "arxiv_docling"
    TOPIC_MODELING = "topic_modeling"


@dataclass
class FlowConfig:
    """Configuration for flow scheduler."""

    enabled: bool = True
    poll_interval_seconds: float = 60.0  # How often to check for new items
    max_concurrent_flows: int = 2  # Max parallel flow runs
    batch_size: int = 5  # Max items per poll
    gpu_index: str = "4,5"  # GPUs to use for flows (avoid vLLM GPUs 0-3)

    # Flow-specific settings
    enable_topics: bool = True
    topic_model_type: str = "bertopic"
    enable_scoring: bool = False  # Disable by default to avoid LLM costs

    # Database
    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "GAIUS_DATABASE_URL",
            "postgres://localhost:5438/zndx_gaius?sslmode=disable"
        )
    )

    # KB paths
    kb_root: str = field(
        default_factory=lambda: os.environ.get("GAIUS_KB_ROOT", "build/dev")
    )

    # GPU resource management (transient workload coordination)
    use_orchestrator: bool = True  # Use OrchestratorService for resource management
    docling_gpu_memory_mb: int = 16000  # GPU memory required for docling (16GB)
    docling_estimated_duration_s: int = 300  # 5 minutes estimated per paper
    restore_endpoints_after_flow: bool = True  # Restore evicted endpoints after flow


@dataclass
class FlowRun:
    """Tracks a running flow instance."""

    flow_type: FlowType
    content_id: str
    arxiv_id: str
    started_at: datetime
    process: Optional[subprocess.Popen] = None
    completed: bool = False
    success: bool = False
    error: Optional[str] = None
    # Workload tracking for GPU resource management
    workload_id: Optional[str] = None  # ID for orchestrator tracking
    evicted_endpoints: list[str] = field(default_factory=list)  # Endpoints to restore


class FlowSchedulerService:
    """Service for scheduling and running Metaflow pipelines autonomously.

    Monitors content_items table for new arxiv papers and triggers
    ArxivDoclingFlow for each one, handling PDF conversion, topic
    extraction, and zettelkasten note creation.

    Transient Workload Coordination:
    - Integrates with OrchestratorService for GPU resource management
    - Can evict idle vLLM endpoints to make room for GPU-intensive flows
    - Automatically restores evicted endpoints after flow completion
    """

    def __init__(
        self,
        config: FlowConfig,
        get_gpu_idle: Optional[Callable[[], bool]] = None,
        orchestrator: Optional["OrchestratorService"] = None,
    ):
        self.config = config
        self.get_gpu_idle = get_gpu_idle or (lambda: True)
        self._orchestrator = orchestrator

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._active_runs: dict[str, FlowRun] = {}
        self._processed_ids: set[str] = set()  # Track processed items
        self._pool: Optional[asyncpg.Pool] = None

        # Metrics
        self._flows_started = 0
        self._flows_completed = 0
        self._flows_failed = 0
        self._last_poll_at: Optional[datetime] = None
        self._endpoints_evicted = 0
        self._endpoints_restored = 0

    async def start(self) -> None:
        """Start the flow scheduler daemon."""
        if self._running:
            return

        logger.info("Starting FlowSchedulerService...")

        # Connect to database
        try:
            self._pool = await asyncpg.create_pool(
                self.config.database_url,
                min_size=1,
                max_size=3,
            )
        except Exception as e:
            logger.warning(f"Database not available, skipping flow scheduler: {e}")
            return

        # Load already processed items from KB
        await self._load_processed_items()

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"FlowSchedulerService started (poll every {self.config.poll_interval_seconds}s)")

    async def stop(self) -> None:
        """Stop the flow scheduler daemon."""
        if not self._running:
            return

        logger.info("Stopping FlowSchedulerService...")
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Wait for active flows to complete
        if self._active_runs:
            logger.info(f"Waiting for {len(self._active_runs)} active flows to complete...")
            await self._wait_for_flows(timeout=30)

        if self._pool:
            await self._pool.close()

        logger.info("FlowSchedulerService stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> dict:
        """Get current service status."""
        return {
            "running": self._running,
            "active_flows": len(self._active_runs),
            "flows_started": self._flows_started,
            "flows_completed": self._flows_completed,
            "flows_failed": self._flows_failed,
            "processed_count": len(self._processed_ids),
            "last_poll_at": self._last_poll_at.isoformat() if self._last_poll_at else None,
            "gpu_index": self.config.gpu_index,
            "poll_interval": self.config.poll_interval_seconds,
            # Transient workload coordination metrics
            "use_orchestrator": self.config.use_orchestrator and self._orchestrator is not None,
            "endpoints_evicted": self._endpoints_evicted,
            "endpoints_restored": self._endpoints_restored,
        }

    async def _run_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                await self._poll_and_process()
                self._last_poll_at = datetime.now()
            except Exception as e:
                logger.error(f"FlowScheduler poll error: {e}")

            await asyncio.sleep(self.config.poll_interval_seconds)

    async def _poll_and_process(self) -> None:
        """Poll for new items and start flows."""
        # Check if we can start more flows
        if len(self._active_runs) >= self.config.max_concurrent_flows:
            logger.debug("Max concurrent flows reached, skipping poll")
            return

        # Check GPU availability (optional)
        if not self.get_gpu_idle():
            logger.debug("GPUs busy, skipping flow scheduling")
            return

        # First, check completed flows
        await self._check_completed_flows()

        # Query for new arxiv papers
        slots_available = self.config.max_concurrent_flows - len(self._active_runs)
        new_items = await self._get_unprocessed_arxiv(limit=min(slots_available, self.config.batch_size))

        if not new_items:
            return

        logger.info(f"Found {len(new_items)} new arxiv papers to process")

        for item in new_items:
            arxiv_id = item.get("arxiv_id") or item.get("external_id", "")
            if not arxiv_id:
                continue

            # Skip if already processing
            if arxiv_id in self._active_runs:
                continue

            # Start the flow
            await self._start_arxiv_flow(arxiv_id, item.get("id"))

    async def _get_unprocessed_arxiv(self, limit: int = 5) -> list[dict]:
        """Get arxiv papers that haven't been processed yet."""
        if not self._pool:
            return []

        async with self._pool.acquire() as conn:
            # Query content_items for arxiv papers not yet processed
            # Use fetched_at (when we got it) rather than published_at
            rows = await conn.fetch(
                """
                SELECT id, external_id, title, url,
                       metadata::json->>'arxiv_id' as arxiv_id,
                       metadata::json->>'pdf_url' as pdf_url
                FROM content_items
                WHERE source_id IN (
                    SELECT id FROM feed_sources WHERE source_type = 'arxiv'
                )
                AND fetched_at > NOW() - INTERVAL '7 days'
                ORDER BY fetched_at DESC
                LIMIT $1
                """,
                limit * 3,  # Fetch more to filter
            )

            # Filter out already processed
            items = []
            for row in rows:
                arxiv_id = row["arxiv_id"] or row["external_id"]
                if arxiv_id and arxiv_id not in self._processed_ids:
                    items.append(dict(row))
                    if len(items) >= limit:
                        break

            return items

    async def _start_arxiv_flow(self, arxiv_id: str, content_id: str = None) -> bool:
        """Start ArxivDoclingFlow for a paper.

        Integrates with OrchestratorService for GPU resource management:
        1. Requests GPU resources via begin_workload()
        2. May evict idle vLLM endpoints to make room
        3. Tracks workload_id for later cleanup/restoration
        """
        arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"
        workload_id: str | None = None
        evicted_endpoints: list[str] = []

        logger.info(f"Starting ArxivDoclingFlow for {arxiv_id}")

        # Request GPU resources via orchestrator if available
        if self.config.use_orchestrator and self._orchestrator:
            workload_id = f"flow-docling-{arxiv_id}-{uuid.uuid4().hex[:8]}"
            workload_result = await self._request_flow_resources(workload_id, arxiv_id)

            if not workload_result.get("success", False):
                logger.warning(
                    f"Failed to allocate GPU resources for {arxiv_id}: "
                    f"{workload_result.get('error', 'unknown error')}"
                )
                # Continue anyway - flow will use CUDA_VISIBLE_DEVICES
            else:
                evicted_endpoints = workload_result.get("evicted_endpoints", [])
                if evicted_endpoints:
                    logger.info(
                        f"Evicted {len(evicted_endpoints)} endpoints for flow: "
                        f"{evicted_endpoints}"
                    )
                    self._endpoints_evicted += len(evicted_endpoints)

        # Build command
        cmd = [
            "uv", "run", "python", "-m", "gaius.flows.docling.flow", "run",
            "--arxiv_url", arxiv_url,
            "--topic_model_type", self.config.topic_model_type,
            "--enable_topics", str(self.config.enable_topics),
            "--enable_scoring", str(self.config.enable_scoring),
        ]

        # Set environment
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = self.config.gpu_index
        env["GAIUS_KB_ROOT"] = self.config.kb_root
        env["MINIO_ENDPOINT"] = os.environ.get("MINIO_ENDPOINT", "localhost:9010")
        env["MINIO_ACCESS_KEY"] = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
        env["MINIO_SECRET_KEY"] = os.environ.get("MINIO_SECRET_KEY", "minioadmin")

        try:
            # Start process in background
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                cwd=str(Path(__file__).parent.parent.parent.parent.parent),  # Project root
            )

            run = FlowRun(
                flow_type=FlowType.ARXIV_DOCLING,
                content_id=content_id or arxiv_id,
                arxiv_id=arxiv_id,
                started_at=datetime.now(),
                process=process,
                workload_id=workload_id,
                evicted_endpoints=evicted_endpoints,
            )

            self._active_runs[arxiv_id] = run
            self._flows_started += 1

            logger.info(f"Started ArxivDoclingFlow for {arxiv_id} (pid={process.pid})")
            return True

        except Exception as e:
            logger.error(f"Failed to start flow for {arxiv_id}: {e}")
            self._flows_failed += 1
            # Release workload resources on failure
            if workload_id and self._orchestrator:
                await self._release_flow_resources(workload_id, evicted_endpoints)
            return False

    async def _request_flow_resources(
        self, workload_id: str, arxiv_id: str
    ) -> dict:
        """Request GPU resources for a flow workload.

        Uses OrchestratorService's Yunikorn-style workload management to:
        1. Check if GPUs are available
        2. Evict idle endpoints if needed
        3. Track the workload for later cleanup

        Args:
            workload_id: Unique workload identifier
            arxiv_id: ArXiv paper ID (for logging)

        Returns:
            Dict with success status and evicted endpoints
        """
        if not self._orchestrator:
            return {"success": False, "error": "No orchestrator available"}

        try:
            from ..workloads import WorkloadRequest, WorkloadType
            from .scheduler_service import JobPriority

            # Parse target GPUs from config (e.g., "0" or "4,5")
            target_gpus = [int(g.strip()) for g in self.config.gpu_index.split(",") if g.strip()]

            # Create workload request for docling flow
            request = WorkloadRequest(
                workload_id=workload_id,
                workload_type=WorkloadType.FLOW,
                required_capabilities=[],  # Docling uses raw CUDA, not vLLM endpoints
                priority=JobPriority.NORMAL,  # Normal priority - can be preempted
                estimated_duration_s=self.config.docling_estimated_duration_s,
                estimated_memory_mb=self.config.docling_gpu_memory_mb,
                preemptible=False,  # Don't preempt running flows
                metadata={
                    "arxiv_id": arxiv_id,
                    "flow_type": "docling",
                    "target_gpus": target_gpus,  # GPUs the flow will use
                },
            )

            # Request resources - this may evict idle endpoints
            result = await self._orchestrator.begin_workload(request)

            return {
                "success": result.success,
                "workload_id": workload_id,
                "evicted_endpoints": result.evicted_endpoints,
                "restore_plan": result.restore_plan,
                "error": result.error,
            }

        except Exception as e:
            logger.error(f"Failed to request flow resources: {e}")
            return {"success": False, "error": str(e)}

    async def _release_flow_resources(
        self, workload_id: str, evicted_endpoints: list[str]
    ) -> None:
        """Release GPU resources and restore evicted endpoints.

        Called after a flow completes (success or failure) to:
        1. Notify orchestrator that workload is done
        2. Restore previously evicted endpoints

        Args:
            workload_id: Workload ID to complete
            evicted_endpoints: Endpoints that were evicted (for metrics)
        """
        if not self._orchestrator:
            return

        try:
            await self._orchestrator.complete_workload(workload_id)

            # Update metrics
            if evicted_endpoints and self.config.restore_endpoints_after_flow:
                self._endpoints_restored += len(evicted_endpoints)
                logger.info(
                    f"Completed workload {workload_id}, "
                    f"restored {len(evicted_endpoints)} endpoints"
                )

        except Exception as e:
            logger.error(f"Failed to release flow resources: {e}")

    async def _check_completed_flows(self) -> None:
        """Check for completed flows and update state.

        Also handles GPU resource cleanup:
        - Releases workload via orchestrator
        - Restores previously evicted endpoints
        """
        completed = []
        workloads_to_release: list[tuple[str, list[str]]] = []

        for arxiv_id, run in self._active_runs.items():
            if run.process is None:
                continue

            # Check if process completed
            retcode = run.process.poll()
            if retcode is not None:
                run.completed = True
                run.success = (retcode == 0)

                if run.success:
                    self._flows_completed += 1
                    self._processed_ids.add(arxiv_id)
                    logger.info(f"ArxivDoclingFlow completed successfully for {arxiv_id}")
                else:
                    self._flows_failed += 1
                    # Read error output
                    try:
                        output = run.process.stdout.read().decode("utf-8")[-2000:]
                        run.error = output
                        logger.warning(f"ArxivDoclingFlow failed for {arxiv_id}: exit code {retcode}")
                    except Exception:
                        pass

                completed.append(arxiv_id)

                # Track workload for resource release
                if run.workload_id:
                    workloads_to_release.append((run.workload_id, run.evicted_endpoints))

        # Remove completed runs
        for arxiv_id in completed:
            del self._active_runs[arxiv_id]

        # Release GPU resources and restore evicted endpoints
        for workload_id, evicted_endpoints in workloads_to_release:
            await self._release_flow_resources(workload_id, evicted_endpoints)

    async def _wait_for_flows(self, timeout: float = 30) -> None:
        """Wait for active flows to complete."""
        start = datetime.now()
        while self._active_runs and (datetime.now() - start).total_seconds() < timeout:
            await self._check_completed_flows()
            if self._active_runs:
                await asyncio.sleep(1)

    async def _load_processed_items(self) -> None:
        """Load already processed arxiv IDs from KB scratch folder."""
        kb_root = Path(self.config.kb_root)
        scratch_dir = kb_root / "scratch"

        if not scratch_dir.exists():
            return

        # Find all arxiv zettelkasten notes
        for md_file in scratch_dir.rglob("*arxiv*.md"):
            # Extract arxiv ID from filename
            # Pattern: HHMMSS_arxiv_<title>.md
            name = md_file.stem
            if "arxiv" in name.lower():
                # Try to extract arxiv ID from file content
                try:
                    content = md_file.read_text()
                    # Look for arxiv ID in frontmatter or content
                    for line in content.split("\n")[:30]:
                        if "arxiv" in line.lower() and any(c.isdigit() for c in line):
                            # Extract YYMM.NNNNN pattern
                            import re
                            match = re.search(r"(\d{4}\.\d{4,5})", line)
                            if match:
                                self._processed_ids.add(match.group(1))
                                break
                except Exception:
                    pass

        logger.info(f"Loaded {len(self._processed_ids)} already-processed arxiv IDs")

    async def trigger_flow(self, flow_type: FlowType, arxiv_id: str) -> dict:
        """Manually trigger a flow run."""
        if flow_type == FlowType.ARXIV_DOCLING:
            success = await self._start_arxiv_flow(arxiv_id)
            return {
                "triggered": success,
                "flow_type": flow_type.value,
                "arxiv_id": arxiv_id,
            }

        return {
            "triggered": False,
            "error": f"Unknown flow type: {flow_type}",
        }
