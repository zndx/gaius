"""ColPali embedding backend controller.

Manages ColQwen2.5 multi-vector embedding model lifecycle with GPU allocation.
Unlike standard embedding models, ColPali produces multi-vector embeddings
(one 128-dim vector per token for colnomic) for late-interaction retrieval.

Key Differences from EmbeddingController:
    - Multi-vector output: [batch, num_tokens, 128] instead of [batch, dim]
    - Uses ColQwen2.5 from colpali-engine instead of SentenceTransformer
    - Supports both text and image embeddings (multimodal)
    - Designed for late-interaction similarity (MaxSim) scoring
    - colnomic projects from 3584 hidden dim to 128 embedding dim

GPU Resource Coordination:
    Similar to EmbeddingController, uses CUDA device placement via
    device_map parameter for ColQwen2.5 model loading.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional, Union

if TYPE_CHECKING:
    from colpali_engine.models import ColQwen2_5, ColQwen2_5_Processor
    import torch

    from ..resources import ResourceManager
    from ...models.registry import ModelSpec

logger = logging.getLogger(__name__)


class ColPaliStatus(Enum):
    """ColPali endpoint status."""

    STOPPED = "stopped"
    LOADING = "loading"
    READY = "ready"
    STOPPING = "stopping"
    FAILED = "failed"


@dataclass
class ColPaliEndpoint:
    """State of a loaded ColPali model."""

    name: str  # Endpoint name (e.g., "colpali-default")
    model_name: str  # HuggingFace model name
    gpu_ids: list[int]  # Allocated GPU IDs
    embedding_dim: int = 128  # ColPali embedding dimension (colnomic projects to 128)

    # Model and processor
    model: Optional["ColQwen2_5"] = field(default=None, repr=False)
    processor: Optional["ColQwen2_5_Processor"] = field(default=None, repr=False)
    status: ColPaliStatus = ColPaliStatus.STOPPED
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
class ColPaliRequest:
    """Request for ColPali embeddings."""

    texts: list[str]
    model: str = ""  # Empty = use default
    # Note: ColPali also supports images, but we focus on text for now


@dataclass
class ColPaliResponse:
    """Response containing multi-vector embeddings.

    Each text produces a list of vectors (one per token).
    Shape: [num_texts][num_tokens][128]
    """

    embeddings: list[list[list[float]]]  # [text_idx][token_idx][128]
    model_used: str
    latency_ms: int
    texts_processed: int
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """Whether request succeeded."""
        return self.error is None


class ColPaliController:
    """Controller for ColPali multi-vector embedding endpoints.

    Manages ColQwen2/ColQwen2_5 models with GPU allocation for late-interaction
    retrieval. Unlike single-vector embeddings, ColPali produces
    multiple vectors per document/query for fine-grained matching.

    Supported models:
    - vidore/colqwen2-v0.1: 2B model, works with colpali-engine 0.3.2
    - nomic-ai/colnomic-embed-multimodal-7b: 7B model, requires colpali-engine 0.3.5+

    Thread Safety:
        All operations are async-safe via an asyncio lock.

    GPU Placement:
        Uses device_map for model loading to place on specific GPUs.
    """

    # Default ColPali model - ColNomic multimodal embeddings
    DEFAULT_MODEL = "nomic-ai/colnomic-embed-multimodal-7b"

    def __init__(
        self,
        resource_manager: "ResourceManager | None" = None,
        default_model: str = DEFAULT_MODEL,
    ):
        """Initialize ColPali controller.

        Args:
            resource_manager: Resource manager for GPU allocation tracking
            default_model: Default ColPali model name
        """
        self.resource_manager = resource_manager
        self.default_model = default_model

        # Endpoint tracking
        self._endpoints: dict[str, ColPaliEndpoint] = {}
        self._lock = asyncio.Lock()

        logger.info(f"ColPaliController initialized: default_model={default_model}")

    async def start(self) -> None:
        """Start the controller (no-op for now, models loaded on demand)."""
        logger.info("ColPaliController started")

    async def stop(self) -> None:
        """Stop the controller and unload all models."""
        async with self._lock:
            for name in list(self._endpoints.keys()):
                await self._unload_model(name)
        logger.info("ColPaliController stopped")

    async def start_colpali_endpoint(
        self,
        model_spec: "ModelSpec",
        gpu_ids: list[int],
        endpoint_name: str | None = None,
    ) -> ColPaliEndpoint:
        """Load a ColPali model on specified GPUs.

        Args:
            model_spec: Model specification with HF model ID
            gpu_ids: GPU IDs to place the model on
            endpoint_name: Optional endpoint name (defaults to model alias)

        Returns:
            ColPaliEndpoint with model state

        Raises:
            RuntimeError: If model fails to load
        """
        async with self._lock:
            # Support both old (huggingface_id) and new (model_id) field names
            hf_id = getattr(model_spec, "huggingface_id", None) or getattr(model_spec, "model_id", None)
            alias = getattr(model_spec, "alias", None) or getattr(model_spec, "name", None)
            name = endpoint_name or alias or hf_id
            model_name = hf_id

            # Fail-fast if we couldn't determine required fields
            if name is None or model_name is None:
                raise RuntimeError(
                    f"Cannot determine endpoint name or model: name={name}, model_name={model_name}.\n"
                    "  Guru Meditation: #COLPALI.00000001.MISSING_MODEL_ID\n"
                    "  Ensure model_spec has huggingface_id or model_id field."
                )

            # Check if already loaded
            if name in self._endpoints and self._endpoints[name].status == ColPaliStatus.READY:
                logger.info(f"ColPali endpoint {name} already loaded")
                return self._endpoints[name]

            # Create endpoint record
            endpoint = ColPaliEndpoint(
                name=name,
                model_name=model_name,
                gpu_ids=gpu_ids,
                status=ColPaliStatus.LOADING,
            )
            self._endpoints[name] = endpoint

            # Load model in thread pool to avoid blocking
            try:
                model, processor = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._load_model_sync(model_name, gpu_ids),
                )
                endpoint.model = model
                endpoint.processor = processor
                endpoint.status = ColPaliStatus.READY
                endpoint.loaded_at = datetime.now()
                logger.info(
                    f"ColPali endpoint {name} ready: model={model_name}, "
                    f"dim={endpoint.embedding_dim}, gpus={gpu_ids}"
                )
                return endpoint

            except Exception as e:
                endpoint.status = ColPaliStatus.FAILED
                endpoint.error = str(e)
                logger.error(f"Failed to load ColPali endpoint {name}: {e}")
                raise RuntimeError(f"Failed to load ColPali model: {e}") from e

    def _load_model_sync(
        self,
        model_name: str,
        gpu_ids: list[int],
    ) -> tuple["ColQwen2_5", "ColQwen2_5_Processor"]:
        """Synchronously load a ColQwen2/ColQwen2_5 model and processor.

        This runs in a thread pool to avoid blocking the event loop.
        Dynamically selects ColQwen2 or ColQwen2_5 based on model name.

        Args:
            model_name: HuggingFace model name
            gpu_ids: GPUs to place model on

        Returns:
            Tuple of (model, processor)
        """
        import torch

        # Determine device map
        if gpu_ids:
            device_map = f"cuda:{gpu_ids[0]}"
        else:
            device_map = "cpu"

        logger.debug(f"Loading ColPali model {model_name} on {device_map}")

        # Dynamically select model class based on model name
        # ColQwen2_5 models require colpali-engine>=0.3.5
        is_qwen25_model = "qwen2.5" in model_name.lower() or "colnomic" in model_name.lower()

        if is_qwen25_model:
            try:
                from colpali_engine.models import ColQwen2_5, ColQwen2_5_Processor
                model_class = ColQwen2_5
                processor_class = ColQwen2_5_Processor
            except ImportError:
                raise ImportError(
                    f"Model {model_name} requires ColQwen2_5 from colpali-engine>=0.3.5. "
                    f"Use 'vidore/colqwen2-v0.1' instead (compatible with 0.3.2)."
                )
        else:
            from colpali_engine.models import ColQwen2, ColQwen2Processor
            model_class = ColQwen2
            processor_class = ColQwen2Processor

        # Load processor first (lightweight)
        processor = processor_class.from_pretrained(model_name)

        # Load model with bfloat16 for memory efficiency
        model = model_class.from_pretrained(
            model_name,
            torch_dtype=torch.bfloat16,
            device_map=device_map,
        ).eval()

        return model, processor

    async def stop_colpali_endpoint(self, name: str) -> None:
        """Unload a ColPali model and free GPU memory.

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
        endpoint.status = ColPaliStatus.STOPPING

        # Clear model and processor references
        if endpoint.model is not None:
            endpoint.model = None
        if endpoint.processor is not None:
            endpoint.processor = None

        # Force CUDA memory release
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

        endpoint.status = ColPaliStatus.STOPPED
        del self._endpoints[name]
        logger.info(f"ColPali endpoint {name} unloaded")

    async def embed_texts(
        self,
        request: ColPaliRequest,
    ) -> ColPaliResponse:
        """Generate multi-vector embeddings for texts.

        Args:
            request: ColPali request with texts

        Returns:
            ColPaliResponse with multi-vector embeddings
        """
        start_time = time.time()

        # Find or create endpoint
        endpoint = await self._get_or_create_endpoint(request.model)
        if endpoint is None or endpoint.model is None:
            return ColPaliResponse(
                embeddings=[],
                model_used=request.model or self.default_model,
                latency_ms=int((time.time() - start_time) * 1000),
                texts_processed=0,
                error="No ColPali model available",
            )

        # Generate embeddings in thread pool
        try:
            embeddings = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._embed_texts_sync(endpoint, request.texts),
            )

            latency_ms = int((time.time() - start_time) * 1000)

            # Update metrics
            endpoint.requests_served += 1
            endpoint.total_texts_embedded += len(request.texts)
            endpoint.total_latency_ms += latency_ms

            return ColPaliResponse(
                embeddings=embeddings,
                model_used=endpoint.model_name,
                latency_ms=latency_ms,
                texts_processed=len(request.texts),
            )

        except Exception as e:
            logger.error(f"ColPali embedding failed: {e}")
            return ColPaliResponse(
                embeddings=[],
                model_used=endpoint.model_name,
                latency_ms=int((time.time() - start_time) * 1000),
                texts_processed=0,
                error=str(e),
            )

    def _embed_texts_sync(
        self,
        endpoint: ColPaliEndpoint,
        texts: list[str],
    ) -> list[list[list[float]]]:
        """Synchronously generate multi-vector embeddings.

        Args:
            endpoint: ColPali endpoint with loaded model
            texts: List of texts to embed

        Returns:
            Multi-vector embeddings: [text_idx][token_idx][128]
        """
        import torch

        if endpoint.model is None or endpoint.processor is None:
            raise RuntimeError(
                f"ColPali endpoint {endpoint.name} model/processor not loaded. "
                f"Status: {endpoint.status}"
            )

        model = endpoint.model
        processor = endpoint.processor

        # Process texts as queries
        batch = processor.process_queries(texts)
        batch = {k: v.to(model.device) for k, v in batch.items()}

        # Generate embeddings
        with torch.no_grad():
            embeddings = model(**batch)  # Shape: [batch, num_tokens, 768]

        # Convert to nested list format
        # embeddings shape: [batch_size, seq_len, hidden_dim]
        result = []
        for i in range(embeddings.shape[0]):
            text_embeddings = embeddings[i].cpu().float().numpy().tolist()
            result.append(text_embeddings)

        return result

    async def _get_or_create_endpoint(
        self,
        model_name: str = "",
    ) -> Optional[ColPaliEndpoint]:
        """Get existing endpoint or create with default model.

        Args:
            model_name: Requested model (empty = default)

        Returns:
            ColPaliEndpoint if available, None otherwise
        """
        target_model = model_name or self.default_model

        async with self._lock:
            # Check for existing endpoint with this model
            for endpoint in self._endpoints.values():
                if endpoint.model_name == target_model and endpoint.status == ColPaliStatus.READY:
                    return endpoint

            # If specific model not found, return any ready ColPali endpoint
            for endpoint in self._endpoints.values():
                if endpoint.status == ColPaliStatus.READY:
                    logger.info(f"Using available endpoint {endpoint.name} ({endpoint.model_name}) instead of {target_model}")
                    return endpoint

            # No existing endpoint - create one
            try:
                from ...models.registry import get_model_registry, ModelSpec

                registry = get_model_registry()
                model_spec = registry.get(target_model)
                if model_spec is None:
                    # Create ad-hoc spec for unknown model
                    model_spec = ModelSpec(
                        model_id=target_model,
                        name=target_model,
                        provider="colpali",
                    )

                # Find a free GPU by checking nvidia-smi
                # Prefer GPU with least memory usage
                gpu_id = self._find_free_gpu()
                logger.info(f"ColPali: selected GPU {gpu_id} for {target_model}")

                endpoint = ColPaliEndpoint(
                    name=f"colpali-{target_model.split('/')[-1]}",
                    model_name=target_model,
                    gpu_ids=[gpu_id],
                    status=ColPaliStatus.LOADING,
                )
                self._endpoints[endpoint.name] = endpoint

                # Load in thread pool
                model, processor = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._load_model_sync(target_model, [gpu_id]),
                )
                endpoint.model = model
                endpoint.processor = processor
                endpoint.status = ColPaliStatus.READY
                endpoint.loaded_at = datetime.now()
                return endpoint

            except Exception as e:
                logger.error(f"Failed to create ColPali endpoint: {e}")
                return None

    def _find_free_gpu(self) -> int:
        """Find GPU with least memory usage.

        Returns:
            GPU index with most free memory, or 0 if unable to determine
        """
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,memory.free", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                # Parse output: "0, 1234\n1, 5678\n..."
                best_gpu = 0
                best_free = 0
                for line in result.stdout.strip().split("\n"):
                    parts = line.split(",")
                    if len(parts) == 2:
                        gpu_idx = int(parts[0].strip())
                        free_mb = int(parts[1].strip())
                        if free_mb > best_free:
                            best_free = free_mb
                            best_gpu = gpu_idx
                logger.debug(f"Found GPU {best_gpu} with {best_free}MB free")
                return best_gpu
        except Exception as e:
            logger.warning(f"Failed to query nvidia-smi: {e}")
        return 0  # Default to GPU 0

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
        """List all ColPali endpoints.

        Returns:
            List of endpoint info dicts
        """
        result: list[dict] = []
        for name in self._endpoints:
            info = self.get_endpoint_info(name)
            if info is not None:
                result.append(info)
        return result


# Module-level singleton
_colpali_controller: Optional[ColPaliController] = None


def get_colpali_controller() -> ColPaliController:
    """Get or create ColPali controller singleton."""
    global _colpali_controller
    if _colpali_controller is None:
        _colpali_controller = ColPaliController()
    return _colpali_controller
