"""Embedding backend controller.

Manages embedding model lifecycle with GPU allocation integration.
Unlike vLLM (subprocess), embedding models run in-engine but are
managed by the orchestrator for resource coordination.

GPU Resource Coordination:
    The embedding controller uses CUDA device placement to ensure
    embeddings run on specific GPUs. Unlike vLLM subprocess isolation,
    this uses CUDA_VISIBLE_DEVICES to restrict the in-process model
    to specific GPUs allocated by the resource manager.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

    from ..resources import ResourceManager
    from ...models.registry import ModelSpec

logger = logging.getLogger(__name__)


class EmbeddingStatus(Enum):
    """Embedding endpoint status."""

    STOPPED = "stopped"
    LOADING = "loading"
    READY = "ready"
    STOPPING = "stopping"
    FAILED = "failed"


@dataclass
class EmbeddingEndpoint:
    """State of a loaded embedding model."""

    name: str  # Endpoint name (e.g., "embedding-default")
    model_name: str  # HuggingFace model name
    gpu_ids: list[int]  # Allocated GPU IDs
    embedding_dim: int = 0  # Populated after load

    # Model state
    model: Optional["SentenceTransformer"] = field(default=None, repr=False)
    status: EmbeddingStatus = EmbeddingStatus.STOPPED
    loaded_at: Optional[datetime] = None
    error: Optional[str] = None

    # Metrics
    requests_served: int = 0
    total_texts_embedded: int = 0
    total_latency_ms: int = 0

    @property
    def avg_latency_ms(self) -> float:
        """Average latency per request."""
        if self.requests_served == 0:
            return 0.0
        return self.total_latency_ms / self.requests_served


@dataclass
class EmbeddingRequest:
    """Request for text embeddings."""

    texts: list[str]
    model: str = ""  # Empty = use default
    batch_size: int = 32


@dataclass
class EmbeddingResponse:
    """Response containing embeddings."""

    embeddings: list[list[float]]
    model_used: str
    latency_ms: int
    texts_processed: int
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """Whether request succeeded."""
        return self.error is None


class EmbeddingController:
    """Controller for embedding model endpoints.

    Manages in-process embedding models with GPU allocation.
    Models are loaded lazily on first request and can be unloaded
    to free GPU memory for higher-priority workloads.

    Thread Safety:
        All operations are async-safe via an asyncio lock.
        The SentenceTransformer model itself is thread-safe for encoding.

    GPU Placement:
        The controller sets CUDA_VISIBLE_DEVICES during model loading
        to place the model on specific GPUs. This provides process-level
        GPU isolation without subprocess overhead.
    """

    # Default embedding model
    DEFAULT_MODEL = "all-MiniLM-L6-v2"

    # Model security settings
    DEFAULT_TRUST_REMOTE_CODE = False
    DEFAULT_USE_SAFETENSORS = True

    def __init__(
        self,
        resource_manager: "ResourceManager | None" = None,
        default_model: str = DEFAULT_MODEL,
    ):
        """Initialize embedding controller.

        Args:
            resource_manager: Resource manager for GPU allocation tracking
            default_model: Default embedding model name
        """
        self.resource_manager = resource_manager
        self.default_model = default_model

        # Endpoint tracking
        self._endpoints: dict[str, EmbeddingEndpoint] = {}
        self._lock = asyncio.Lock()

        # Model security settings
        self._trust_remote_code = self.DEFAULT_TRUST_REMOTE_CODE
        self._use_safetensors = self.DEFAULT_USE_SAFETENSORS

        logger.info(f"EmbeddingController initialized: default_model={default_model}")

    async def start(self) -> None:
        """Start the controller (no-op for now, models loaded on demand)."""
        logger.info("EmbeddingController started")

    async def stop(self) -> None:
        """Stop the controller and unload all models."""
        async with self._lock:
            for name in list(self._endpoints.keys()):
                await self._unload_model(name)
        logger.info("EmbeddingController stopped")

    async def start_embedding_endpoint(
        self,
        model_spec: "ModelSpec",
        gpu_ids: list[int],
        endpoint_name: str | None = None,
    ) -> EmbeddingEndpoint:
        """Load an embedding model on specified GPUs.

        Args:
            model_spec: Model specification with HF model ID
            gpu_ids: GPU IDs to place the model on
            endpoint_name: Optional endpoint name (defaults to model alias)

        Returns:
            EmbeddingEndpoint with model state

        Raises:
            RuntimeError: If model fails to load
        """
        async with self._lock:
            # Support both old (huggingface_id) and new (model_id) field names
            hf_id = getattr(model_spec, "huggingface_id", None) or getattr(model_spec, "model_id", None)
            alias = getattr(model_spec, "alias", None) or getattr(model_spec, "name", None)
            name = endpoint_name or alias or hf_id
            model_name = hf_id

            # Check if already loaded
            if name in self._endpoints and self._endpoints[name].status == EmbeddingStatus.READY:
                logger.info(f"Embedding endpoint {name} already loaded")
                return self._endpoints[name]

            # Create endpoint record
            endpoint = EmbeddingEndpoint(
                name=name,
                model_name=model_name,
                gpu_ids=gpu_ids,
                status=EmbeddingStatus.LOADING,
            )
            self._endpoints[name] = endpoint

            # Load model in thread pool to avoid blocking
            try:
                model = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._load_model_sync(model_name, gpu_ids),
                )
                endpoint.model = model
                endpoint.embedding_dim = model.get_sentence_embedding_dimension()
                endpoint.status = EmbeddingStatus.READY
                endpoint.loaded_at = datetime.now()
                logger.info(
                    f"Embedding endpoint {name} ready: model={model_name}, "
                    f"dim={endpoint.embedding_dim}, gpus={gpu_ids}"
                )
                return endpoint

            except Exception as e:
                endpoint.status = EmbeddingStatus.FAILED
                endpoint.error = str(e)
                logger.error(f"Failed to load embedding endpoint {name}: {e}")
                raise RuntimeError(f"Failed to load embedding model: {e}") from e

    def _load_model_sync(
        self,
        model_name: str,
        gpu_ids: list[int],
    ) -> "SentenceTransformer":
        """Synchronously load a SentenceTransformer model.

        This runs in a thread pool to avoid blocking the event loop.
        GPU placement is controlled via CUDA_VISIBLE_DEVICES.

        Args:
            model_name: HuggingFace model name
            gpu_ids: GPUs to place model on

        Returns:
            Loaded SentenceTransformer model
        """
        from sentence_transformers import SentenceTransformer

        # Set GPU visibility for this model
        # Note: This affects the current process, so models are pinned to GPUs
        if gpu_ids:
            os.environ["CUDA_VISIBLE_DEVICES"] = ",".join(str(g) for g in gpu_ids)
            device = "cuda"
        else:
            device = "cpu"

        # Enable safetensors if configured
        if self._use_safetensors:
            os.environ["SAFETENSORS_FAST_GPU"] = "1"

        logger.debug(f"Loading embedding model {model_name} on {device}")
        model = SentenceTransformer(
            model_name,
            trust_remote_code=self._trust_remote_code,
            device=device,
        )
        return model

    async def stop_embedding_endpoint(self, name: str) -> None:
        """Unload an embedding model and free GPU memory.

        Args:
            name: Endpoint name to stop
        """
        async with self._lock:
            await self._unload_model(name)

    async def _unload_model(self, name: str) -> None:
        """Internal: unload model (caller holds lock)."""
        if name not in self._endpoints:
            return

        endpoint = self._endpoints[name]
        endpoint.status = EmbeddingStatus.STOPPING

        # Clear model reference and force garbage collection
        if endpoint.model is not None:
            endpoint.model = None

            # Force CUDA memory release
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

        endpoint.status = EmbeddingStatus.STOPPED
        del self._endpoints[name]
        logger.info(f"Embedding endpoint {name} unloaded")

    async def embed_texts(
        self,
        request: EmbeddingRequest,
    ) -> EmbeddingResponse:
        """Generate embeddings for texts.

        Args:
            request: Embedding request with texts and optional model

        Returns:
            EmbeddingResponse with embeddings or error
        """
        start_time = time.time()

        # Find or create endpoint
        endpoint = await self._get_or_create_endpoint(request.model)
        if endpoint is None or endpoint.model is None:
            return EmbeddingResponse(
                embeddings=[],
                model_used=request.model or self.default_model,
                latency_ms=int((time.time() - start_time) * 1000),
                texts_processed=0,
                error="No embedding model available",
            )

        # Generate embeddings in thread pool
        try:
            embeddings = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: endpoint.model.encode(
                    request.texts,
                    batch_size=request.batch_size,
                    show_progress_bar=False,
                ).tolist(),
            )

            latency_ms = int((time.time() - start_time) * 1000)

            # Update metrics
            endpoint.requests_served += 1
            endpoint.total_texts_embedded += len(request.texts)
            endpoint.total_latency_ms += latency_ms

            return EmbeddingResponse(
                embeddings=embeddings,
                model_used=endpoint.model_name,
                latency_ms=latency_ms,
                texts_processed=len(request.texts),
            )

        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            return EmbeddingResponse(
                embeddings=[],
                model_used=endpoint.model_name,
                latency_ms=int((time.time() - start_time) * 1000),
                texts_processed=0,
                error=str(e),
            )

    async def _get_or_create_endpoint(
        self,
        model_name: str = "",
    ) -> Optional[EmbeddingEndpoint]:
        """Get existing endpoint or create with default model.

        Args:
            model_name: Requested model (empty = default)

        Returns:
            EmbeddingEndpoint if available, None otherwise
        """
        target_model = model_name or self.default_model

        async with self._lock:
            # Check for existing endpoint with this model
            for endpoint in self._endpoints.values():
                if endpoint.model_name == target_model and endpoint.status == EmbeddingStatus.READY:
                    return endpoint

            # If specific model not found, return any ready embedding endpoint
            # This allows the engine's configured embedding model to serve all requests
            for endpoint in self._endpoints.values():
                if endpoint.status == EmbeddingStatus.READY:
                    logger.info(f"Using available endpoint {endpoint.name} ({endpoint.model_name}) instead of {target_model}")
                    return endpoint

            # No existing endpoint - create one with default GPU allocation
            # In production, this should go through orchestrator.ensure_capability()
            # For now, we create a CPU fallback endpoint
            try:
                from ...models.registry import get_registry

                registry = get_registry()
                model_spec = registry.get_model(target_model)
                if model_spec is None:
                    # Create ad-hoc spec for unknown model
                    from ...models.registry import ModelSpec

                    model_spec = ModelSpec(
                        huggingface_id=target_model,
                        alias=target_model,
                    )

                # Load on CPU as fallback (engine orchestrator handles GPU allocation)
                endpoint = EmbeddingEndpoint(
                    name=f"embedding-{target_model}",
                    model_name=target_model,
                    gpu_ids=[],  # CPU
                    status=EmbeddingStatus.LOADING,
                )
                self._endpoints[endpoint.name] = endpoint

                # Load in thread pool
                model = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._load_model_sync(target_model, []),
                )
                endpoint.model = model
                endpoint.embedding_dim = model.get_sentence_embedding_dimension()
                endpoint.status = EmbeddingStatus.READY
                endpoint.loaded_at = datetime.now()
                return endpoint

            except Exception as e:
                logger.error(f"Failed to create embedding endpoint: {e}")
                return None

    def get_endpoint_info(self, name: str) -> Optional[dict]:
        """Get information about an endpoint.

        Args:
            name: Endpoint name

        Returns:
            Endpoint info dict or None
        """
        if name not in self._endpoints:
            return None

        endpoint = self._endpoints[name]
        return {
            "name": endpoint.name,
            "model": endpoint.model_name,
            "status": endpoint.status.value,
            "gpu_ids": endpoint.gpu_ids,
            "embedding_dim": endpoint.embedding_dim,
            "loaded_at": endpoint.loaded_at.isoformat() if endpoint.loaded_at else None,
            "requests_served": endpoint.requests_served,
            "avg_latency_ms": endpoint.avg_latency_ms,
        }

    def list_endpoints(self) -> list[dict]:
        """List all embedding endpoints.

        Returns:
            List of endpoint info dicts
        """
        return [
            self.get_endpoint_info(name)
            for name in self._endpoints
            if self.get_endpoint_info(name) is not None
        ]


# Module-level singleton
_embedding_controller: Optional[EmbeddingController] = None


def get_embedding_controller() -> EmbeddingController:
    """Get or create embedding controller singleton."""
    global _embedding_controller
    if _embedding_controller is None:
        _embedding_controller = EmbeddingController()
    return _embedding_controller
