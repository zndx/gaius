"""Vector search service with orchestrator GPU coordination.

Wraps VectorSearchMulti with workload-based GPU allocation and
LRU-style caching to balance responsiveness with resource efficiency.

Usage:
    from gaius.engine.services import VectorSearchService

    # Create service (wired by engine server)
    service = VectorSearchService(orchestrator=orchestrator_service)

    # Search (automatically allocates GPU via workload system)
    results = await service.search(query="attention mechanism", top_k=10)

Design Philosophy:
    - Uses begin_workload()/complete_workload() for GPU allocation
    - LRU-style caching: model stays loaded until idle timeout
    - Graceful queuing when GPU unavailable
    - Fail-fast: no silent degradation to CPU

Yunikorn-style dynamic scheduling:
    User: /ask "analyze" → Orchestrator evicts ColNomic, deploys reasoning
    User: /search "transformer" → Orchestrator evicts reasoning, deploys ColNomic
    Idle 5 min → ColNomic unloaded, GPU freed
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

if TYPE_CHECKING:
    from .orchestrator_service import OrchestratorService


class SearchPhase(Enum):
    """Progress phases for streaming semantic search."""

    REQUESTING_GPU = "requesting_gpu"
    EVICTING_ENDPOINTS = "evicting_endpoints"
    LOADING_MODEL = "loading_model"
    SEARCHING = "searching"
    INDEXING = "indexing"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class SearchProgressEvent:
    """Progress event for streaming semantic search."""

    phase: SearchPhase
    message: str
    progress_pct: int = 0  # 0-100
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    results: list = field(default_factory=list)
    error: Optional[str] = None
    guru_code: Optional[str] = None

logger = logging.getLogger(__name__)


@dataclass
class VectorSearchConfig:
    """Configuration for vector search service."""

    idle_timeout_s: int = 300  # Unload after 5 minutes idle
    max_queue_wait_s: int = 60  # Max time to wait for GPU
    model_name: str = "nomic-ai/colnomic-embed-multimodal-7b"
    # ColNomic 7B in bf16 requires ~15GB VRAM (7B params * 2 bytes = 14GB + overhead)
    memory_mb: int = 15000  # GPU memory estimate (bf16)

    @classmethod
    def from_env(cls) -> "VectorSearchConfig":
        """Create config from environment variables."""
        return cls(
            idle_timeout_s=int(os.getenv("GAIUS_VECTOR_SEARCH_IDLE_TIMEOUT", "300")),
            max_queue_wait_s=int(os.getenv("GAIUS_VECTOR_SEARCH_MAX_WAIT", "60")),
            memory_mb=int(os.getenv("GAIUS_VECTOR_SEARCH_MEMORY_MB", "15000")),
        )


class VectorSearchService:
    """Manages ColNomic embedding model with orchestrator GPU coordination.

    Key features:
    - Uses begin_workload()/complete_workload() for GPU allocation
    - LRU-style caching: model stays loaded until idle timeout
    - Graceful queuing when GPU unavailable
    - Fail-fast: no silent degradation to CPU
    """

    def __init__(
        self,
        orchestrator: "OrchestratorService",
        config: Optional[VectorSearchConfig] = None,
    ):
        """Initialize vector search service.

        Args:
            orchestrator: OrchestratorService for GPU allocation
            config: Optional configuration (defaults from env)
        """
        self._orchestrator = orchestrator
        self._config = config or VectorSearchConfig.from_env()
        self._lock = asyncio.Lock()

        # State
        self._vector_search_multi: Any = None
        self._allocated_gpu: Optional[int] = None
        self._workload_id: Optional[str] = None
        self._loaded_at: Optional[datetime] = None
        self._idle_task: Optional[asyncio.Task] = None

        # Metrics
        self._requests_served = 0
        self._total_latency_ms = 0

        logger.info(
            f"VectorSearchService initialized "
            f"(idle_timeout={self._config.idle_timeout_s}s, "
            f"memory={self._config.memory_mb}MB)"
        )

    @property
    def is_loaded(self) -> bool:
        """Check if model is currently loaded."""
        return self._vector_search_multi is not None

    async def search(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.0,
        use_maxsim: bool = True,
        content_type: Optional[str] = None,
    ) -> list:
        """Execute semantic search with automatic GPU coordination.

        Args:
            query: Search query text
            top_k: Maximum results to return
            min_score: Minimum similarity score threshold
            use_maxsim: Use MaxSim late-interaction scoring
            content_type: Filter by "text" or "image"

        Returns:
            List of SearchResult objects

        Raises:
            RuntimeError: If GPU cannot be allocated (fail-fast)
        """
        start_time = time.time()

        async with self._lock:
            await self._ensure_loaded()
            self._cancel_idle_timer()

        try:
            results = self._vector_search_multi.search(
                query=query,
                top_k=top_k,
                min_score=min_score,
                use_maxsim=use_maxsim,
                content_type=content_type,
            )

            latency_ms = int((time.time() - start_time) * 1000)
            self._requests_served += 1
            self._total_latency_ms += latency_ms

            logger.debug(
                f"VectorSearch completed: {len(results)} results in {latency_ms}ms"
            )

            return results
        finally:
            self._schedule_idle_unload()

    async def search_stream(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.0,
        use_maxsim: bool = True,
        content_type: Optional[str] = None,
    ) -> AsyncIterator[SearchProgressEvent]:
        """Execute semantic search with streaming progress events.

        Yields SearchProgressEvent objects for each phase of the search:
        1. REQUESTING_GPU - Requesting GPU allocation via orchestrator
        2. EVICTING_ENDPOINTS - Evicting vLLM endpoints if needed
        3. LOADING_MODEL - Loading ColNomic model onto GPU
        4. SEARCHING - Executing MaxSim search on Qdrant
        5. COMPLETE - Search done, results included
        6. ERROR - Error occurred (with guru code)

        This allows the TUI to display progress during the 10-20s cold start.
        """
        start_time = time.time()

        try:
            # Phase 1: Check if already loaded (fast path)
            if self._vector_search_multi is not None:
                yield SearchProgressEvent(
                    phase=SearchPhase.SEARCHING,
                    message="ColNomic already loaded, executing search...",
                    progress_pct=50,
                )
            else:
                # Cold path: need to load model
                async for event in self._ensure_loaded_stream():
                    yield event

            # Cancel idle timer while we're using the model
            self._cancel_idle_timer()

            # Phase 4: Execute search
            yield SearchProgressEvent(
                phase=SearchPhase.SEARCHING,
                message=f"Searching '{query[:50]}...' with MaxSim" if len(query) > 50 else f"Searching '{query}' with MaxSim",
                progress_pct=80,
            )

            results = self._vector_search_multi.search(
                query=query,
                top_k=top_k,
                min_score=min_score,
                use_maxsim=use_maxsim,
                content_type=content_type,
            )

            latency_ms = int((time.time() - start_time) * 1000)
            self._requests_served += 1
            self._total_latency_ms += latency_ms

            # Phase 5: Complete
            yield SearchProgressEvent(
                phase=SearchPhase.COMPLETE,
                message=f"Found {len(results)} results in {latency_ms}ms",
                progress_pct=100,
                results=results,
            )

        except RuntimeError as e:
            # VectorSearchService raises RuntimeError with Guru codes
            error_str = str(e)
            guru_code = None
            if "Guru Meditation:" in error_str:
                # Extract Guru code from error message
                for line in error_str.split("\n"):
                    if "Guru Meditation:" in line:
                        guru_code = line.split("Guru Meditation:")[1].strip()
                        break

            yield SearchProgressEvent(
                phase=SearchPhase.ERROR,
                message=error_str.split("\n")[0],  # First line only
                progress_pct=0,
                error=error_str,
                guru_code=guru_code,
            )

        except Exception as e:
            logger.error(f"VectorSearch stream failed: {e}")
            yield SearchProgressEvent(
                phase=SearchPhase.ERROR,
                message=str(e),
                progress_pct=0,
                error=str(e),
                guru_code="#VS.00000099.UNKNOWN",
            )

        finally:
            self._schedule_idle_unload()

    async def index_kb(
        self,
        kb_root: str = "build/dev",
    ) -> int:
        """Index KB documents into Qdrant with GPU coordination.

        Uses the orchestrator's workload system to allocate a GPU for
        ColNomic embedding, then indexes all KB documents.

        Args:
            kb_root: Root directory of the knowledge base

        Returns:
            Number of chunks indexed

        Raises:
            RuntimeError: If GPU cannot be allocated (fail-fast)
        """
        from pathlib import Path

        async with self._lock:
            await self._ensure_loaded()
            self._cancel_idle_timer()

        try:
            # Set kb_root on the managed VectorSearchMulti
            self._vector_search_multi.kb_root = Path(kb_root)

            # Run indexing in executor (it's CPU+GPU bound)
            loop = asyncio.get_event_loop()
            count = await loop.run_in_executor(
                None, self._vector_search_multi.index_kb
            )

            logger.info(f"VectorSearch indexed {count} chunks from {kb_root}")
            return count
        finally:
            self._schedule_idle_unload()

    async def index_kb_stream(
        self,
        kb_root: str = "build/dev",
    ) -> AsyncIterator[SearchProgressEvent]:
        """Index KB documents with streaming progress events.

        Yields SearchProgressEvent objects for each phase:
        1. REQUESTING_GPU - Requesting GPU allocation via orchestrator
        2. EVICTING_ENDPOINTS - Evicting vLLM endpoints if needed
        3. LOADING_MODEL - Loading ColNomic model onto GPU
        4. INDEXING - Indexing KB documents into Qdrant
        5. COMPLETE - Indexing done
        6. ERROR - Error occurred (with guru code)
        """
        from pathlib import Path

        try:
            # Phase 1-3: Ensure model loaded (GPU allocation)
            if self._vector_search_multi is not None:
                yield SearchProgressEvent(
                    phase=SearchPhase.INDEXING,
                    message="ColNomic already loaded, starting indexing...",
                    progress_pct=40,
                )
            else:
                async for event in self._ensure_loaded_stream():
                    yield event

            self._cancel_idle_timer()

            # Phase 4: Index KB
            yield SearchProgressEvent(
                phase=SearchPhase.INDEXING,
                message=f"Indexing KB documents from {kb_root}...",
                progress_pct=50,
            )

            self._vector_search_multi.kb_root = Path(kb_root)

            loop = asyncio.get_event_loop()
            count = await loop.run_in_executor(
                None, self._vector_search_multi.index_kb
            )

            # Phase 5: Complete
            yield SearchProgressEvent(
                phase=SearchPhase.COMPLETE,
                message=f"Indexed {count} chunks from {kb_root}",
                progress_pct=100,
            )

        except RuntimeError as e:
            error_str = str(e)
            guru_code = None
            if "Guru Meditation:" in error_str:
                for line in error_str.split("\n"):
                    if "Guru Meditation:" in line:
                        guru_code = line.split("Guru Meditation:")[1].strip()
                        break

            yield SearchProgressEvent(
                phase=SearchPhase.ERROR,
                message=error_str.split("\n")[0],
                progress_pct=0,
                error=error_str,
                guru_code=guru_code,
            )

        except Exception as e:
            logger.error(f"VectorSearch index_kb_stream failed: {e}")
            yield SearchProgressEvent(
                phase=SearchPhase.ERROR,
                message=str(e),
                progress_pct=0,
                error=str(e),
                guru_code="#VS.00000004.INDEXFAIL",
            )

        finally:
            self._schedule_idle_unload()

    async def _ensure_loaded_stream(self) -> AsyncIterator[SearchProgressEvent]:
        """Ensure ColNomic model is loaded, yielding progress events.

        This is the streaming version of _ensure_loaded() that yields
        progress events during GPU allocation and model loading.
        """
        async with self._lock:
            if self._vector_search_multi is not None:
                return

            from ..workloads import WorkloadRequest, WorkloadType
            from ..services.scheduler_service import JobPriority

            self._workload_id = f"vector-search-{int(time.time())}"

            # Phase 1: Request GPU
            yield SearchProgressEvent(
                phase=SearchPhase.REQUESTING_GPU,
                message=f"Requesting {self._config.memory_mb}MB GPU memory...",
                progress_pct=10,
            )

            request = WorkloadRequest(
                workload_id=self._workload_id,
                workload_type=WorkloadType.EMBEDDING,
                required_capabilities=[],
                priority=JobPriority.NORMAL,
                estimated_duration_s=self._config.idle_timeout_s,
                estimated_memory_mb=self._config.memory_mb,
                preemptible=True,
                metadata={"allow_baseline_eviction": True},
            )

            try:
                result = await asyncio.wait_for(
                    self._orchestrator.begin_workload(request),
                    timeout=self._config.max_queue_wait_s,
                )
            except asyncio.TimeoutError:
                raise RuntimeError(
                    f"GPU allocation timeout ({self._config.max_queue_wait_s}s) for vector search.\n"
                    f"  Guru Meditation: #VS.00000003.TIMEOUT\n"
                    f"  Check: /gpu status"
                )

            if not result.success:
                raise RuntimeError(
                    f"Failed to allocate GPU for vector search: {result.error}\n"
                    f"  Guru Meditation: #VS.00000001.GPUALLOC\n"
                    f"  Try: /health fix endpoints"
                )

            # Check if eviction was performed
            if result.evicted_endpoints:
                yield SearchProgressEvent(
                    phase=SearchPhase.EVICTING_ENDPOINTS,
                    message=f"Evicted {len(result.evicted_endpoints)} endpoints for GPU memory",
                    progress_pct=20,
                )

            # Phase 3: Find GPU and load model
            self._allocated_gpu = await self._find_available_gpu()
            device = f"cuda:{self._allocated_gpu}"

            yield SearchProgressEvent(
                phase=SearchPhase.LOADING_MODEL,
                message=f"Loading ColNomic on GPU {self._allocated_gpu}...",
                progress_pct=30,
            )

            try:
                from gaius.inference.search.vector_multi import VectorSearchMulti

                self._vector_search_multi = VectorSearchMulti(device=device)

                yield SearchProgressEvent(
                    phase=SearchPhase.LOADING_MODEL,
                    message="Initializing ColNomic embedder...",
                    progress_pct=50,
                )

                _ = self._vector_search_multi.embedder  # Force load

                self._loaded_at = datetime.now()
                logger.info(f"VectorSearch ready on GPU {self._allocated_gpu}")

                yield SearchProgressEvent(
                    phase=SearchPhase.LOADING_MODEL,
                    message=f"ColNomic ready on GPU {self._allocated_gpu}",
                    progress_pct=70,
                )

            except Exception as e:
                await self._complete_workload()
                raise RuntimeError(
                    f"Failed to load ColNomic model: {e}\n"
                    f"  Guru Meditation: #VS.00000002.LOADFAIL\n"
                    f"  Check GPU memory with nvidia-smi"
                )

    async def _ensure_loaded(self) -> None:
        """Ensure ColNomic model is loaded on an allocated GPU.

        Uses the orchestrator's workload system to:
        1. Request GPU memory (may evict lower-priority endpoints)
        2. Load ColNomic model on allocated GPU
        3. Track workload for resource accounting
        """
        if self._vector_search_multi is not None:
            return

        from ..workloads import WorkloadRequest, WorkloadType
        from ..services.scheduler_service import JobPriority

        self._workload_id = f"vector-search-{int(time.time())}"

        # Create workload request for GPU memory (not capability-based)
        # Uses Yunikorn-style dynamic scheduling where ColNomic can evict
        # baseline endpoints (orchestrator, instruct) for user-interactive search
        request = WorkloadRequest(
            workload_id=self._workload_id,
            workload_type=WorkloadType.EMBEDDING,
            required_capabilities=[],  # Empty = GPU memory workload, not vLLM endpoint
            priority=JobPriority.NORMAL,
            estimated_duration_s=self._config.idle_timeout_s,
            estimated_memory_mb=self._config.memory_mb,
            preemptible=True,
            metadata={
                # Allow evicting baseline endpoints for user-requested search
                # This enables Yunikorn-style dynamic scheduling where ColNomic
                # and reasoning endpoints can evict each other based on demand
                "allow_baseline_eviction": True,
            },
        )

        logger.info(
            f"Requesting GPU for vector search "
            f"(workload_id={self._workload_id}, memory={self._config.memory_mb}MB)"
        )

        try:
            result = await asyncio.wait_for(
                self._orchestrator.begin_workload(request),
                timeout=self._config.max_queue_wait_s,
            )
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"GPU allocation timeout ({self._config.max_queue_wait_s}s) for vector search.\n"
                f"  Guru Meditation: #VS.00000003.TIMEOUT\n"
                f"  Check: /gpu status"
            )

        if not result.success:
            raise RuntimeError(
                f"Failed to allocate GPU for vector search: {result.error}\n"
                f"  Guru Meditation: #VS.00000001.GPUALLOC\n"
                f"  Try: /health fix endpoints"
            )

        # For GPU memory workloads, we get eviction info but not port allocations
        # We need to find a GPU to use
        self._allocated_gpu = await self._find_available_gpu()
        device = f"cuda:{self._allocated_gpu}"

        logger.info(f"Loading ColNomic on {device}")

        # Load model
        try:
            from gaius.inference.search.vector_multi import VectorSearchMulti

            self._vector_search_multi = VectorSearchMulti(device=device)
            _ = self._vector_search_multi.embedder  # Force load

            self._loaded_at = datetime.now()
            logger.info(f"VectorSearch ready on GPU {self._allocated_gpu}")
        except Exception as e:
            # Clean up workload on failure
            await self._complete_workload()
            raise RuntimeError(
                f"Failed to load ColNomic model: {e}\n"
                f"  Guru Meditation: #VS.00000002.LOADFAIL\n"
                f"  Check GPU memory with nvidia-smi"
            )

    async def _find_available_gpu(self) -> int:
        """Find a GPU with sufficient free memory.

        Returns:
            GPU ID to use for ColNomic
        """
        from ..resources.gpu_monitor import get_gpu_memory_free

        try:
            gpu_free = await get_gpu_memory_free()
            required_gb = self._config.memory_mb / 1024

            # Find first GPU with enough memory
            for gpu_id, free_gb in sorted(gpu_free.items(), reverse=True):
                if free_gb >= required_gb:
                    logger.debug(
                        f"Selected GPU {gpu_id} with {free_gb:.1f}GB free "
                        f"(need {required_gb:.1f}GB)"
                    )
                    return gpu_id

            # Fallback to highest-numbered GPU (assumes vLLM uses 0-3)
            logger.warning(
                f"No GPU with {required_gb}GB free, using highest available"
            )
            return max(gpu_free.keys()) if gpu_free else 4
        except Exception as e:
            logger.warning(f"GPU query failed, defaulting to GPU 4: {e}")
            return 4

    async def _unload(self) -> None:
        """Unload model and release GPU."""
        async with self._lock:
            await self._unload_internal()

    async def _unload_internal(self) -> None:
        """Unload model (caller holds lock)."""
        if self._vector_search_multi is None:
            return

        logger.info("Unloading VectorSearch model")

        # Clear model reference
        if hasattr(self._vector_search_multi, "_embedder"):
            self._vector_search_multi._embedder = None
        self._vector_search_multi = None

        # Release CUDA memory
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

        # Complete workload to release GPU tracking
        await self._complete_workload()

        self._allocated_gpu = None
        logger.info("VectorSearch unloaded, GPU released")

    async def _complete_workload(self) -> None:
        """Complete workload to release GPU tracking."""
        if self._workload_id:
            try:
                await self._orchestrator.complete_workload(self._workload_id)
            except Exception as e:
                logger.warning(f"Failed to complete workload: {e}")
            self._workload_id = None

    def _schedule_idle_unload(self) -> None:
        """Schedule model unload after idle timeout."""
        self._cancel_idle_timer()

        async def _idle_unload():
            await asyncio.sleep(self._config.idle_timeout_s)
            logger.info(
                f"VectorSearch idle for {self._config.idle_timeout_s}s, unloading"
            )
            await self._unload()

        self._idle_task = asyncio.create_task(_idle_unload())

    def _cancel_idle_timer(self) -> None:
        """Cancel pending idle unload."""
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
            self._idle_task = None

    @property
    def collection_name(self) -> str:
        """Get Qdrant collection name."""
        if self._vector_search_multi:
            return self._vector_search_multi.collection_name
        return "gaius_kb_colnomic"

    def get_status(self) -> dict:
        """Get service status for diagnostics."""
        return {
            "loaded": self.is_loaded,
            "gpu_id": self._allocated_gpu,
            "model": self._config.model_name,
            "loaded_at": self._loaded_at.isoformat() if self._loaded_at else None,
            "requests_served": self._requests_served,
            "avg_latency_ms": (
                self._total_latency_ms / max(1, self._requests_served)
            ),
            "idle_timeout_s": self._config.idle_timeout_s,
            "workload_id": self._workload_id,
        }

    async def shutdown(self) -> None:
        """Gracefully shutdown the service."""
        self._cancel_idle_timer()
        await self._unload()
        logger.info("VectorSearchService shutdown complete")
