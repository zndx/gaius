"""Dataset Service for NiFi SoM/ToM generation via gRPC.

Implements the DatasetService from the gaius_service.proto with:
- Priority job queue for generation requests
- Progress streaming via AsyncIterator
- Fail-fast backend checks with /health fix suggestions
- OpenLineage capture for full data provenance

Key Principles:
- All execution in engine (no standalone mode)
- Fail-fast behavior - no fallbacks for missing backends
- OpenLineage events for START/COMPLETE/FAIL
- Calibration is optional (default off)
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Optional
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from ..backends import BackendRouter
    from .orchestrator_service import OrchestratorService
    from gaius.hx.lineage.emitter import LineageEmitter

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Exceptions with Remediation Hints
# ═══════════════════════════════════════════════════════════════════════════


class DatasetServiceError(Exception):
    """Base exception for dataset service errors."""

    pass


class BackendNotAvailableError(DatasetServiceError):
    """Raised when required backend unavailable. Includes remediation hints."""

    def __init__(
        self,
        backend: str,
        health_fix: str,
        manual_action: str,
        detail: str = "",
    ):
        msg = f"{backend} not available."
        if detail:
            msg += f" ({detail})"
        msg += f"\n  Try: {health_fix}"
        msg += f"\n  Or:  {manual_action}"
        super().__init__(msg)
        self.backend = backend
        self.health_fix = health_fix
        self.manual_action = manual_action
        self.detail = detail


class GenerationError(DatasetServiceError):
    """Generation failed - includes context for debugging."""

    def __init__(self, message: str, phase: str, example_id: str = ""):
        super().__init__(message)
        self.phase = phase
        self.example_id = example_id


# ═══════════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════════


class JobStatus(str, Enum):
    """Status of a dataset generation job."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobPhase(str, Enum):
    """Current phase of a generation job."""

    QUEUED = "queued"
    BACKEND_CHECK = "backend_check"
    CAPTURE = "capture"
    ANNOTATE = "annotate"
    GENERATE = "generate"
    CALIBRATE = "calibrate"
    EXPORT = "export"
    COMPLETE = "complete"


class ProgressEventType(int, Enum):
    """Progress event types matching proto DatasetProgressEvent.Type."""

    QUEUED = 0
    STARTED = 1
    PHASE_STARTED = 2
    EXAMPLE_STARTED = 3
    EXAMPLE_COMPLETED = 4
    EXAMPLE_REJECTED = 5
    PHASE_COMPLETED = 6
    CALIBRATION_STARTED = 7
    CALIBRATION_COMPLETED = 8
    EXPORT_STARTED = 9
    COMPLETED = 10
    FAILED = 11


@dataclass
class DatasetJobConfig:
    """Configuration for a dataset generation job.

    Maps from DatasetGenerationRequest proto message.
    """

    flow_name: str = "TestFlow"
    steps: list[str] = field(default_factory=lambda: ["start", "process", "end"])
    mode: str = "som"  # "som" or "tom"
    dataset_id: str = "nifi-som-v1"
    variants_per_action: int = 5
    min_quality_score: float = 0.6
    enable_calibration: bool = False  # Off by default
    calibration_sample_rate: float = 0.1
    export_calibration: bool = False
    storage_backend: str = "minio"


@dataclass
class DatasetJob:
    """A dataset generation job.

    Tracks the full lifecycle from submission to completion.
    """

    id: str
    config: DatasetJobConfig
    status: JobStatus = JobStatus.QUEUED
    run_id: UUID = field(default_factory=uuid4)
    submitted_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: float = 0.0
    current_phase: JobPhase = JobPhase.QUEUED
    examples_total: int = 0
    examples_completed: int = 0
    examples_accepted: int = 0
    examples_rejected: int = 0
    error: Optional[str] = None

    # Results
    output_paths: list[str] = field(default_factory=list)

    def to_status_dict(self) -> dict[str, Any]:
        """Convert to status dict for gRPC response."""
        return {
            "job_id": self.id,
            "status": self.status.value,
            "total_examples": self.examples_total,
            "completed_examples": self.examples_completed,
            "accepted_examples": self.examples_accepted,
            "rejected_examples": self.examples_rejected,
            "progress": self.progress,
            "current_phase": self.current_phase.value,
            "error": self.error or "",
        }


@dataclass
class ProgressEvent:
    """Progress event for streaming updates."""

    type: ProgressEventType
    timestamp_ms: int = field(default_factory=lambda: int(datetime.now().timestamp() * 1000))
    job_id: str = ""
    progress: float = 0.0
    message: str = ""
    phase: str = ""
    example_id: str = ""
    data: bytes = b""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for proto message."""
        return {
            "type": self.type.value,
            "timestamp_ms": self.timestamp_ms,
            "job_id": self.job_id,
            "progress": self.progress,
            "message": self.message,
            "phase": self.phase,
            "example_id": self.example_id,
            "data": self.data,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Service Configuration
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class DatasetServiceConfig:
    """Configuration for the dataset service."""

    enabled: bool = True
    require_llm_endpoint: bool = True  # Fail if no LLM available
    require_nifi: bool = True  # Fail if NiFi not available
    max_concurrent_jobs: int = 2
    default_variants_per_action: int = 5
    default_min_quality: float = 0.6
    nifi_url: str = "http://localhost:8450"
    output_dir: str = "build/dev/current/datasets"


# ═══════════════════════════════════════════════════════════════════════════
# Dataset Service
# ═══════════════════════════════════════════════════════════════════════════


class DatasetService:
    """gRPC service for dataset generation.

    Follows established patterns:
    - Priority job queue (like SchedulerService)
    - Progress streaming (like SwarmStream)
    - Workload management (like FlowSchedulerService)
    - OpenLineage integration (like GaiusFlow)

    Fail-Fast Design:
    - No fallbacks for missing LLM or NiFi backends
    - Errors include actionable /health fix suggestions
    - Calibration is optional (off by default)
    """

    def __init__(
        self,
        config: DatasetServiceConfig,
        backend_router: Optional["BackendRouter"] = None,
        orchestrator_service: Optional["OrchestratorService"] = None,
        lineage_emitter: Optional["LineageEmitter"] = None,
    ):
        """Initialize the dataset service.

        Args:
            config: Service configuration
            backend_router: Backend router for LLM calls
            orchestrator_service: For endpoint health checks
            lineage_emitter: For OpenLineage events
        """
        self.config = config
        self.backend_router = backend_router
        self.orchestrator_service = orchestrator_service
        self._lineage_emitter = lineage_emitter

        # Job queue (priority sorted)
        self._queue: list[DatasetJob] = []
        self._queue_lock = asyncio.Lock()

        # Active jobs
        self._active_jobs: dict[str, DatasetJob] = {}

        # Progress subscribers
        self._progress_subscribers: dict[str, list[asyncio.Queue]] = {}

        # Processing state
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        self._job_counter = 0

        logger.info("DatasetService initialized")

    async def start(self) -> None:
        """Start the dataset service."""
        if self._running:
            return

        self._running = True
        self._worker_task = asyncio.create_task(self._process_queue())

        logger.info("DatasetService started")

    async def stop(self) -> None:
        """Stop the dataset service."""
        if not self._running:
            return

        self._running = False

        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

        logger.info("DatasetService stopped")

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    async def submit_job(self, config: DatasetJobConfig) -> DatasetJob:
        """Submit a dataset generation job.

        Performs fail-fast checks before queueing:
        - LLM endpoint available (if require_llm_endpoint=True)
        - NiFi available (if require_nifi=True)

        Args:
            config: Job configuration

        Returns:
            DatasetJob with status and job_id

        Raises:
            BackendNotAvailableError: If required backend unavailable
        """
        # Fail-fast: check backends before queueing
        await self._ensure_backends_ready()

        # Create job
        async with self._queue_lock:
            self._job_counter += 1
            job = DatasetJob(
                id=f"dataset-{self._job_counter}-{uuid4().hex[:8]}",
                config=config,
            )
            self._queue.append(job)
            self._active_jobs[job.id] = job

            # Emit queued event
            await self._emit_progress(
                job,
                ProgressEventType.QUEUED,
                "Job queued for processing",
            )

            logger.info(f"Submitted dataset job {job.id}: {config.flow_name} ({config.mode})")

        return job

    async def get_job_status(self, job_id: str) -> Optional[DatasetJob]:
        """Get status of a specific job."""
        return self._active_jobs.get(job_id)

    async def cancel_job(self, job_id: str) -> Optional[DatasetJob]:
        """Cancel a job if possible."""
        job = self._active_jobs.get(job_id)
        if job is None:
            return None

        if job.status == JobStatus.QUEUED:
            async with self._queue_lock:
                if job in self._queue:
                    self._queue.remove(job)
            job.status = JobStatus.CANCELLED
            job.completed_at = datetime.now()

            await self._emit_progress(
                job,
                ProgressEventType.FAILED,
                "Job cancelled by user",
            )

        return job

    def subscribe_progress(self, job_id: str) -> AsyncIterator[ProgressEvent]:
        """Subscribe to progress events for a job.

        Returns an async iterator that yields ProgressEvent objects.
        """
        return self._progress_iterator(job_id)

    async def _progress_iterator(self, job_id: str) -> AsyncIterator[ProgressEvent]:
        """Async iterator for progress events."""
        queue: asyncio.Queue = asyncio.Queue()

        # Register subscriber
        if job_id not in self._progress_subscribers:
            self._progress_subscribers[job_id] = []
        self._progress_subscribers[job_id].append(queue)

        try:
            while True:
                event = await queue.get()
                yield event

                # Stop on terminal events
                if event.type in (
                    ProgressEventType.COMPLETED,
                    ProgressEventType.FAILED,
                ):
                    break
        finally:
            # Unsubscribe
            if job_id in self._progress_subscribers:
                self._progress_subscribers[job_id].remove(queue)

    # ─────────────────────────────────────────────────────────────────────────
    # Backend Checks (Fail-Fast)
    # ─────────────────────────────────────────────────────────────────────────

    async def _ensure_backends_ready(self) -> None:
        """Check required backends are available. Raises with /health fix suggestion.

        Raises:
            BackendNotAvailableError: If required backend unavailable
        """
        # Check LLM endpoint
        if self.config.require_llm_endpoint:
            if not await self._check_llm_available():
                raise BackendNotAvailableError(
                    backend="LLM (vLLM/optillm)",
                    health_fix="/health fix llm",
                    manual_action="gaius-cli orchestrator start reasoning",
                    detail="No LLM endpoint running for instruction generation",
                )

        # Check NiFi
        if self.config.require_nifi:
            if not await self._check_nifi_available():
                raise BackendNotAvailableError(
                    backend="NiFi",
                    health_fix="/health fix nifi",
                    manual_action="devenv processes up nifi",
                    detail="NiFi not reachable for flow sync",
                )

    async def _check_llm_available(self) -> bool:
        """Check if any LLM endpoint is available."""
        if self.backend_router is None:
            return False

        try:
            status = self.backend_router.get_status()

            # Check vLLM endpoints
            vllm_status = status.get("vllm", {})
            vllm_running = vllm_status.get("total_running", 0)

            # Check optillm
            optillm_status = status.get("optillm", {})
            optillm_healthy = optillm_status.get("healthy", False)

            return vllm_running > 0 or optillm_healthy
        except Exception as e:
            logger.debug(f"LLM check failed: {e}")
            return False

    async def _check_nifi_available(self) -> bool:
        """Check if NiFi is available."""
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                url = f"{self.config.nifi_url}/nifi-api/flow/cluster/summary"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.debug(f"NiFi check failed: {e}")
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Job Processing
    # ─────────────────────────────────────────────────────────────────────────

    async def _process_queue(self) -> None:
        """Background queue processor."""
        while self._running:
            job = None

            async with self._queue_lock:
                if self._queue:
                    job = self._queue.pop(0)

            if job:
                await self._process_job(job)
            else:
                await asyncio.sleep(0.1)

    async def _process_job(self, job: DatasetJob) -> None:
        """Process a single job through the generation pipeline."""
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now()
        job.current_phase = JobPhase.BACKEND_CHECK

        # Emit lineage START event
        await self._emit_lineage_start(job)

        await self._emit_progress(
            job,
            ProgressEventType.STARTED,
            f"Starting {job.config.mode} generation for {job.config.flow_name}",
        )

        try:
            # Phase 1: Backend verification
            await self._emit_progress(
                job,
                ProgressEventType.PHASE_STARTED,
                "Verifying backend availability",
                phase="backend_check",
            )
            await self._ensure_backends_ready()
            await self._emit_progress(
                job,
                ProgressEventType.PHASE_COMPLETED,
                "Backends verified",
                phase="backend_check",
            )

            # Phase 2: Run generation
            examples = await self._run_generation(job)

            # Phase 3: Optional calibration
            if job.config.enable_calibration and examples:
                await self._run_calibration(job, examples)

            # Phase 4: Export
            output_paths = await self._run_export(job, examples)
            job.output_paths = output_paths

            # Complete
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now()
            job.progress = 1.0
            job.current_phase = JobPhase.COMPLETE

            await self._emit_progress(
                job,
                ProgressEventType.COMPLETED,
                f"Generated {job.examples_accepted} examples",
            )

            # Emit lineage COMPLETE event
            await self._emit_lineage_complete(job, examples)

            logger.info(
                f"Dataset job {job.id} completed: "
                f"{job.examples_accepted} accepted, {job.examples_rejected} rejected"
            )

        except BackendNotAvailableError as e:
            await self._handle_job_failure(job, str(e))
            await self._emit_lineage_fail(job, str(e))

        except GenerationError as e:
            await self._handle_job_failure(job, str(e))
            await self._emit_lineage_fail(job, str(e))

        except Exception as e:
            logger.exception(f"Unexpected error in job {job.id}")
            await self._handle_job_failure(job, f"Internal error: {e}")
            await self._emit_lineage_fail(job, str(e))

    async def _handle_job_failure(self, job: DatasetJob, error: str) -> None:
        """Handle job failure."""
        job.status = JobStatus.FAILED
        job.completed_at = datetime.now()
        job.error = error

        await self._emit_progress(
            job,
            ProgressEventType.FAILED,
            error,
        )

        logger.error(f"Dataset job {job.id} failed: {error}")

    async def _run_generation(self, job: DatasetJob) -> list:
        """Run the core generation pipeline.

        Returns list of generated examples.
        """
        job.current_phase = JobPhase.GENERATE

        await self._emit_progress(
            job,
            ProgressEventType.PHASE_STARTED,
            f"Generating {job.config.mode} examples",
            phase="generate",
        )

        # Import generator (deferred to avoid circular imports)
        from gaius.datasets.nifi_som.generator import NiFiSoMGenerator

        # Create generator with LLM enabled
        generator = NiFiSoMGenerator(
            nifi_url=self.config.nifi_url,
            output_dir=Path(self.config.output_dir) / job.config.dataset_id,
            storage_backend=job.config.storage_backend,
            dataset_id=job.config.dataset_id,
            mode=job.config.mode,
            use_llm=True,
            llm_candidates=job.config.variants_per_action,
            min_quality_score=job.config.min_quality_score,
            enable_calibration=job.config.enable_calibration,
            calibration_sample_rate=job.config.calibration_sample_rate,
            export_calibration=job.config.export_calibration,
        )

        # Generate examples
        examples = await generator.generate_from_flow(
            flow_name=job.config.flow_name,
            steps=job.config.steps,
            capture_screenshot=True,
        )

        # Update job metrics
        job.examples_total = len(examples)
        job.examples_completed = len(examples)
        job.examples_accepted = len(examples)  # All accepted if generated
        job.progress = 0.7  # 70% after generation

        await self._emit_progress(
            job,
            ProgressEventType.PHASE_COMPLETED,
            f"Generated {len(examples)} examples",
            phase="generate",
        )

        return examples

    async def _run_calibration(self, job: DatasetJob, examples: list) -> None:
        """Run optional XAI calibration on examples."""
        job.current_phase = JobPhase.CALIBRATE

        await self._emit_progress(
            job,
            ProgressEventType.CALIBRATION_STARTED,
            f"Calibrating {len(examples)} examples",
            phase="calibrate",
        )

        # Import calibration (deferred)
        try:
            from gaius.datasets.nifi_som.calibration import CalibrationOrchestrator, CalibrationConfig
            from gaius.models.tiered_evaluation import EvalBudget

            budget = EvalBudget()
            config = CalibrationConfig(inline_sample_rate=job.config.calibration_sample_rate)
            orchestrator = CalibrationOrchestrator(budget=budget, config=config)

            # Build inputs for calibration
            from gaius.datasets.nifi_som.calibration import LocalScoreInput

            local_inputs = []
            for example in examples:
                metadata = example.metadata or {}
                local_inputs.append(
                    LocalScoreInput(
                        example_id=example.id,
                        instruction=example.instruction,
                        target_name=metadata.get("target_processor", "unknown"),
                        target_type=metadata.get("processor_type", "unknown"),
                        marks=[{"id": m.id, "name": m.label, "type": m.type} for m in example.marks],
                        action_type="click",
                        clarity=metadata.get("quality_clarity", 0.5),
                        naturalness=metadata.get("quality_naturalness", 0.5),
                        specificity=metadata.get("quality_specificity", 0.5),
                        conciseness=metadata.get("quality_conciseness", 0.5),
                        overall=metadata.get("quality_overall", 0.5),
                    )
                )

            # Run calibration
            await orchestrator.calibrate_batch(local_inputs)

            await self._emit_progress(
                job,
                ProgressEventType.CALIBRATION_COMPLETED,
                f"Calibration complete: {orchestrator.get_status()}",
                phase="calibrate",
            )

        except Exception as e:
            logger.warning(f"Calibration failed (non-fatal): {e}")
            await self._emit_progress(
                job,
                ProgressEventType.CALIBRATION_COMPLETED,
                f"Calibration skipped: {e}",
                phase="calibrate",
            )

        job.progress = 0.85  # 85% after calibration

    async def _run_export(self, job: DatasetJob, examples: list) -> list[str]:
        """Export examples to storage."""
        job.current_phase = JobPhase.EXPORT

        await self._emit_progress(
            job,
            ProgressEventType.EXPORT_STARTED,
            f"Exporting {len(examples)} examples to {job.config.storage_backend}",
            phase="export",
        )

        from gaius.datasets.nifi_som.exporter import MagmaExporter

        output_dir = Path(self.config.output_dir) / job.config.dataset_id
        exporter = MagmaExporter(
            output_dir,
            storage_backend=job.config.storage_backend,
            dataset_id=job.config.dataset_id,
        )

        exporter.export(examples)

        job.progress = 0.95  # 95% after export

        # Determine output paths
        output_paths = []
        if job.config.storage_backend == "minio":
            output_paths.append(f"s3://zndx-gaius/datasets/{job.config.dataset_id}/")
            output_paths.append(str(output_dir / "manifest.json"))
        else:
            output_paths.append(str(output_dir / "annotations.json"))

        return output_paths

    # ─────────────────────────────────────────────────────────────────────────
    # Progress Events
    # ─────────────────────────────────────────────────────────────────────────

    async def _emit_progress(
        self,
        job: DatasetJob,
        event_type: ProgressEventType,
        message: str,
        phase: str = "",
        example_id: str = "",
        data: dict | None = None,
    ) -> None:
        """Emit a progress event to all subscribers."""
        event = ProgressEvent(
            type=event_type,
            job_id=job.id,
            progress=job.progress,
            message=message,
            phase=phase or job.current_phase.value,
            example_id=example_id,
            data=json.dumps(data).encode() if data else b"",
        )

        # Send to all subscribers
        subscribers = self._progress_subscribers.get(job.id, [])
        for queue in subscribers:
            try:
                await queue.put(event)
            except Exception as e:
                logger.warning(f"Failed to send progress event: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # OpenLineage Integration
    # ─────────────────────────────────────────────────────────────────────────

    async def _get_lineage_emitter(self) -> Optional["LineageEmitter"]:
        """Get or create lineage emitter."""
        if self._lineage_emitter is not None:
            return self._lineage_emitter

        try:
            from gaius.hx.lineage.emitter import get_emitter
            self._lineage_emitter = get_emitter()
            return self._lineage_emitter
        except Exception as e:
            logger.warning(f"Could not initialize lineage emitter: {e}")
            return None

    async def _emit_lineage_start(self, job: DatasetJob) -> None:
        """Emit OpenLineage START event."""
        emitter = await self._get_lineage_emitter()
        if emitter is None:
            return

        try:
            from gaius.hx.lineage.events import Dataset, Job as OLJob, Run, RunEvent

            # Create Job
            ol_job = OLJob(
                namespace="gaius.datasets",
                name=f"nifi_{job.config.mode}_generation",
            )

            # Create input Dataset (NiFi flow)
            inputs = [
                Dataset(
                    namespace="gaius.source",
                    name=f"nifi:{job.config.flow_name}",
                )
            ]

            # Create Run with job's run_id
            run = Run(run_id=job.run_id)

            # Emit START event
            start_event = RunEvent.start(ol_job, inputs, run)
            await emitter.emit(start_event)

            logger.debug(f"Emitted lineage START for job {job.id}")

        except Exception as e:
            logger.warning(f"Failed to emit lineage START: {e}")

    async def _emit_lineage_complete(self, job: DatasetJob, examples: list) -> None:
        """Emit OpenLineage COMPLETE event with output datasets."""
        emitter = await self._get_lineage_emitter()
        if emitter is None:
            return

        try:
            from gaius.hx.lineage.events import Dataset, Job as OLJob, Run, RunEvent, DatasetFacets

            # Create Job
            ol_job = OLJob(
                namespace="gaius.datasets",
                name=f"nifi_{job.config.mode}_generation",
            )

            # Input (same as START)
            inputs = [
                Dataset(
                    namespace="gaius.source",
                    name=f"nifi:{job.config.flow_name}",
                )
            ]

            # Outputs
            outputs = [
                Dataset(
                    namespace="gaius.hx",
                    name=f"datasets/{job.config.dataset_id}/magma",
                    facets=DatasetFacets(
                        custom={
                            "example_count": len(examples),
                            "accepted_count": job.examples_accepted,
                            "rejected_count": job.examples_rejected,
                        }
                    ),
                )
            ]

            # Add calibration output if enabled
            if job.config.export_calibration:
                outputs.append(
                    Dataset(
                        namespace="gaius.hx",
                        name=f"datasets/{job.config.dataset_id}/calibration",
                    )
                )

            # Create Run
            run = Run(run_id=job.run_id)

            # Emit COMPLETE event
            complete_event = RunEvent.complete(run, ol_job, inputs, outputs)
            await emitter.emit(complete_event)

            logger.debug(f"Emitted lineage COMPLETE for job {job.id}")

        except Exception as e:
            logger.warning(f"Failed to emit lineage COMPLETE: {e}")

    async def _emit_lineage_fail(self, job: DatasetJob, error: str) -> None:
        """Emit OpenLineage FAIL event."""
        emitter = await self._get_lineage_emitter()
        if emitter is None:
            return

        try:
            from gaius.hx.lineage.events import Dataset, Job as OLJob, Run, RunEvent

            # Create Job
            ol_job = OLJob(
                namespace="gaius.datasets",
                name=f"nifi_{job.config.mode}_generation",
            )

            # Input
            inputs = [
                Dataset(
                    namespace="gaius.source",
                    name=f"nifi:{job.config.flow_name}",
                )
            ]

            # Create Run
            run = Run(run_id=job.run_id)

            # Emit FAIL event
            fail_event = RunEvent.fail(run, ol_job, inputs, error)
            await emitter.emit(fail_event)

            logger.debug(f"Emitted lineage FAIL for job {job.id}")

        except Exception as e:
            logger.warning(f"Failed to emit lineage FAIL: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Lineage Query
    # ─────────────────────────────────────────────────────────────────────────

    async def get_lineage(self, dataset_id: str) -> dict:
        """Query lineage for a dataset.

        Returns nodes and edges for the lineage graph.
        """
        emitter = await self._get_lineage_emitter()
        if emitter is None:
            return {
                "dataset_id": dataset_id,
                "total_examples": 0,
                "nodes": [],
                "edges": [],
            }

        # Query from lineage_events table
        try:
            pool = await emitter._get_pool()

            async with pool.acquire() as conn:
                # Find events related to this dataset
                rows = await conn.fetch(
                    """
                    SELECT id, run_id, job_namespace, job_name, run_state,
                           inputs::text, outputs::text, event_time
                    FROM lineage_events
                    WHERE outputs::text LIKE $1
                    ORDER BY event_time DESC
                    LIMIT 100
                    """,
                    f'%{dataset_id}%',
                )

                nodes = []
                edges = []
                seen_ids = set()

                for row in rows:
                    run_id = str(row["run_id"])

                    # Add Run node
                    if run_id not in seen_ids:
                        nodes.append({
                            "id": run_id,
                            "type": "Run",
                            "namespace": row["job_namespace"],
                            "name": row["job_name"],
                            "properties": json.dumps({
                                "state": row["run_state"],
                                "time": row["event_time"].isoformat(),
                            }).encode(),
                        })
                        seen_ids.add(run_id)

                    # Add input Datasets and edges
                    inputs = json.loads(row["inputs"]) if row["inputs"] else []
                    for inp in inputs:
                        ds_id = f"{inp.get('namespace', '')}:{inp.get('name', '')}"
                        if ds_id not in seen_ids:
                            nodes.append({
                                "id": ds_id,
                                "type": "Dataset",
                                "namespace": inp.get("namespace", ""),
                                "name": inp.get("name", ""),
                                "properties": b"{}",
                            })
                            seen_ids.add(ds_id)
                        edges.append({
                            "type": "INPUT_TO",
                            "from_id": ds_id,
                            "to_id": run_id,
                        })

                    # Add output Datasets and edges
                    outputs = json.loads(row["outputs"]) if row["outputs"] else []
                    for out in outputs:
                        ds_id = f"{out.get('namespace', '')}:{out.get('name', '')}"
                        if ds_id not in seen_ids:
                            nodes.append({
                                "id": ds_id,
                                "type": "Dataset",
                                "namespace": out.get("namespace", ""),
                                "name": out.get("name", ""),
                                "properties": b"{}",
                            })
                            seen_ids.add(ds_id)
                        edges.append({
                            "type": "OUTPUTS",
                            "from_id": run_id,
                            "to_id": ds_id,
                        })

                return {
                    "dataset_id": dataset_id,
                    "total_examples": len([n for n in nodes if n["type"] == "Dataset"]),
                    "nodes": nodes,
                    "edges": edges,
                }

        except Exception as e:
            logger.error(f"Failed to query lineage: {e}")
            return {
                "dataset_id": dataset_id,
                "total_examples": 0,
                "nodes": [],
                "edges": [],
            }

    # ─────────────────────────────────────────────────────────────────────────
    # Status
    # ─────────────────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Get service status."""
        return {
            "running": self._running,
            "queue_depth": len(self._queue),
            "active_jobs": len(self._active_jobs),
            "total_jobs_submitted": self._job_counter,
        }
