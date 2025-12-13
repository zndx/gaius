"""Model merging algorithms for evolution.

Implements TIES, DARE, SLERP, and Task Arithmetic for merging
LoRA adapters and model weights. Uses out-of-core processing
for memory efficiency on resource-constrained systems.

These algorithms are re-implemented from academic papers and are
Apache 2.0 licensed (not derived from LGPL mergekit).

References:
- TIES-Merging: https://arxiv.org/abs/2306.01708
- DARE: https://arxiv.org/abs/2311.03099
- Task Arithmetic: https://arxiv.org/abs/2212.04089
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

import numpy as np

logger = logging.getLogger(__name__)


class MergeMethod(Enum):
    """Available model merging methods."""

    LINEAR = "linear"  # Simple weighted average
    SLERP = "slerp"  # Spherical linear interpolation (2 models only)
    TASK_ARITHMETIC = "task_arithmetic"  # Add task vectors to base
    TIES = "ties"  # Trim, Elect Sign, Merge
    DARE = "dare"  # Drop And REscale
    DARE_TIES = "dare_ties"  # DARE with TIES sign election


@dataclass
class ModelSource:
    """Source model for merging."""

    model_id: str  # HuggingFace ID or local path
    weight: float = 1.0  # Contribution weight for this model
    is_base: bool = False  # True if this is the base model for task vectors
    eval_score: float | None = None  # Optional eval score (for weighted merging)
    version_id: str | None = None  # Agent version ID if from evolution

    def __post_init__(self):
        if self.weight < 0:
            raise ValueError("Weight must be non-negative")


@dataclass
class MergeConfig:
    """Configuration for a merge operation."""

    method: MergeMethod
    sources: list[ModelSource]

    # Method-specific parameters
    normalize_weights: bool = True  # Normalize weights to sum to 1
    interpolation_t: float = 0.5  # For SLERP: interpolation parameter

    # TIES parameters
    ties_density: float = 0.2  # Keep top k% of parameters (k = density)
    ties_lambda: float = 1.0  # Scaling factor for merged task vector

    # DARE parameters
    dare_drop_rate: float = 0.9  # Fraction of parameters to drop
    dare_rescale: bool = True  # Whether to rescale after dropping

    # Output configuration
    output_path: str | None = None  # Where to save merged model
    output_format: str = "safetensors"  # "safetensors" or "pytorch"

    def validate(self) -> list[str]:
        """Validate configuration, return list of errors."""
        errors = []

        if not self.sources:
            errors.append("At least one source model required")

        if self.method == MergeMethod.SLERP and len(self.sources) != 2:
            errors.append("SLERP requires exactly 2 source models")

        if self.method in (MergeMethod.TASK_ARITHMETIC, MergeMethod.TIES, MergeMethod.DARE, MergeMethod.DARE_TIES):
            base_count = sum(1 for s in self.sources if s.is_base)
            if base_count != 1:
                errors.append(f"Task vector methods require exactly 1 base model, found {base_count}")

        if not 0 < self.ties_density <= 1:
            errors.append("ties_density must be in (0, 1]")

        if not 0 <= self.dare_drop_rate < 1:
            errors.append("dare_drop_rate must be in [0, 1)")

        return errors


@dataclass
class MergeResult:
    """Result of a merge operation."""

    success: bool
    merge_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    method: MergeMethod | None = None
    source_models: list[str] = field(default_factory=list)
    output_path: str | None = None

    # Metrics
    duration_ms: int = 0
    layers_processed: int = 0
    total_parameters: int = 0
    peak_memory_mb: float = 0

    # Lineage
    parent_versions: list[str] = field(default_factory=list)  # Agent version IDs
    created_at: datetime = field(default_factory=datetime.utcnow)

    # Error handling
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "success": self.success,
            "merge_id": self.merge_id,
            "method": self.method.value if self.method else None,
            "source_models": self.source_models,
            "output_path": self.output_path,
            "duration_ms": self.duration_ms,
            "layers_processed": self.layers_processed,
            "total_parameters": self.total_parameters,
            "peak_memory_mb": self.peak_memory_mb,
            "parent_versions": self.parent_versions,
            "created_at": self.created_at.isoformat(),
            "error": self.error,
            "warnings": self.warnings,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Core Merging Algorithms
# ═══════════════════════════════════════════════════════════════════════════════


def slerp(v0: np.ndarray, v1: np.ndarray, t: float) -> np.ndarray:
    """Spherical linear interpolation between two vectors.

    Interpolates along the shortest path on a hypersphere rather than
    linearly, preserving geometric properties.

    Args:
        v0: First vector
        v1: Second vector
        t: Interpolation parameter [0, 1]

    Returns:
        Interpolated vector
    """
    # Flatten for dot product
    v0_flat = v0.flatten()
    v1_flat = v1.flatten()

    # Normalize
    v0_norm = np.linalg.norm(v0_flat)
    v1_norm = np.linalg.norm(v1_flat)

    if v0_norm < 1e-10 or v1_norm < 1e-10:
        # One vector is near zero, fall back to linear
        return (1 - t) * v0 + t * v1

    v0_unit = v0_flat / v0_norm
    v1_unit = v1_flat / v1_norm

    # Compute angle
    dot = np.clip(np.dot(v0_unit, v1_unit), -1.0, 1.0)

    # If vectors are nearly parallel, use linear interpolation
    if abs(dot) > 0.9995:
        result = (1 - t) * v0 + t * v1
        return result

    theta_0 = np.arccos(dot)
    sin_theta_0 = np.sin(theta_0)

    theta_t = theta_0 * t
    sin_theta_t = np.sin(theta_t)

    s0 = np.sin(theta_0 - theta_t) / sin_theta_0
    s1 = sin_theta_t / sin_theta_0

    # Interpolate and restore original scale
    scale = (1 - t) * v0_norm + t * v1_norm
    result_flat = s0 * v0_flat + s1 * v1_flat
    result_flat = result_flat / np.linalg.norm(result_flat) * scale

    return result_flat.reshape(v0.shape)


def compute_task_vector(fine_tuned: np.ndarray, base: np.ndarray) -> np.ndarray:
    """Compute task vector as difference from base model.

    Args:
        fine_tuned: Fine-tuned model weights
        base: Base model weights

    Returns:
        Task vector (delta weights)
    """
    return fine_tuned - base


def ties_merge(
    task_vectors: list[np.ndarray],
    weights: list[float],
    density: float = 0.2,
    lambda_scale: float = 1.0,
) -> np.ndarray:
    """TIES-Merging: Trim, Elect Sign, Merge.

    Addresses interference between task vectors by:
    1. Trimming to keep only top-k% parameters by magnitude
    2. Electing sign based on weighted vote
    3. Merging only aligned parameters

    Args:
        task_vectors: List of task vectors to merge
        weights: Weights for each task vector
        density: Fraction of parameters to keep (top k%)
        lambda_scale: Scaling factor for final merged vector

    Returns:
        Merged task vector
    """
    if not task_vectors:
        raise ValueError("At least one task vector required")

    shape = task_vectors[0].shape

    # Normalize weights
    total_weight = sum(weights)
    weights = [w / total_weight for w in weights]

    # Step 1: TRIM - Keep only top-k% by magnitude
    trimmed = []
    for tv in task_vectors:
        flat = tv.flatten()
        threshold = np.percentile(np.abs(flat), 100 * (1 - density))
        mask = np.abs(flat) >= threshold
        trimmed.append((flat * mask).reshape(shape))

    # Step 2: ELECT SIGN - Vote on direction for each parameter
    # Sum the signs weighted by magnitude and weight
    sign_votes = np.zeros(shape)
    for tv, w in zip(trimmed, weights):
        sign_votes += w * np.sign(tv) * np.abs(tv)
    elected_sign = np.sign(sign_votes)

    # Step 3: DISJOINT MERGE - Average only aligned parameters
    merged = np.zeros(shape)
    counts = np.zeros(shape)

    for tv, w in zip(trimmed, weights):
        # Only include if sign matches elected sign (or is zero)
        aligned = (np.sign(tv) == elected_sign) | (tv == 0)
        merged += np.where(aligned, w * tv, 0)
        counts += np.where(aligned & (tv != 0), w, 0)

    # Average where we have contributions
    with np.errstate(divide="ignore", invalid="ignore"):
        merged = np.where(counts > 0, merged / counts, 0)

    return lambda_scale * merged


def dare_sparsify(
    task_vector: np.ndarray,
    drop_rate: float = 0.9,
    rescale: bool = True,
    seed: int | None = None,
) -> np.ndarray:
    """DARE: Drop And REscale task vector.

    Randomly drops parameters and rescales remainder to maintain
    expected value. Remarkably effective even at 90-99% drop rates.

    Args:
        task_vector: Task vector to sparsify
        drop_rate: Fraction of parameters to drop
        rescale: Whether to rescale remaining parameters
        seed: Random seed for reproducibility

    Returns:
        Sparsified task vector
    """
    if seed is not None:
        np.random.seed(seed)

    # Create random mask (1 = keep, 0 = drop)
    mask = np.random.random(task_vector.shape) > drop_rate

    # Apply mask
    sparse = task_vector * mask

    # Rescale to maintain expected value
    if rescale and drop_rate < 1.0:
        sparse = sparse / (1 - drop_rate)

    return sparse


def dare_ties_merge(
    task_vectors: list[np.ndarray],
    weights: list[float],
    drop_rate: float = 0.9,
    density: float = 0.2,
    lambda_scale: float = 1.0,
    seed: int | None = None,
) -> np.ndarray:
    """DARE-TIES: Combine DARE sparsification with TIES sign election.

    Args:
        task_vectors: List of task vectors to merge
        weights: Weights for each task vector
        drop_rate: DARE drop rate
        density: TIES density parameter
        lambda_scale: Scaling factor
        seed: Random seed

    Returns:
        Merged task vector
    """
    # Apply DARE to each task vector
    sparsified = []
    for i, tv in enumerate(task_vectors):
        sparse_tv = dare_sparsify(
            tv,
            drop_rate=drop_rate,
            rescale=True,
            seed=(seed + i) if seed else None,
        )
        sparsified.append(sparse_tv)

    # Apply TIES merging to sparsified vectors
    return ties_merge(sparsified, weights, density=density, lambda_scale=lambda_scale)


def linear_merge(tensors: list[np.ndarray], weights: list[float]) -> np.ndarray:
    """Simple weighted average of tensors.

    Args:
        tensors: List of tensors to merge
        weights: Weights for each tensor

    Returns:
        Weighted average tensor
    """
    total_weight = sum(weights)
    weights = [w / total_weight for w in weights]

    result = np.zeros_like(tensors[0])
    for tensor, weight in zip(tensors, weights):
        result += weight * tensor

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Out-of-Core Processing
# ═══════════════════════════════════════════════════════════════════════════════


def iter_safetensors_layers(path: Path) -> Iterator[tuple[str, np.ndarray]]:
    """Iterate over layers in a safetensors file without loading all into memory.

    Args:
        path: Path to safetensors file

    Yields:
        Tuples of (layer_name, tensor)
    """
    try:
        from safetensors import safe_open

        with safe_open(path, framework="numpy") as f:
            for key in f.keys():
                yield key, f.get_tensor(key)
    except ImportError:
        logger.warning("safetensors not available, using torch")
        import torch

        state_dict = torch.load(path, map_location="cpu", weights_only=True)
        for key, tensor in state_dict.items():
            yield key, tensor.numpy()


def save_safetensors(tensors: dict[str, np.ndarray], path: Path) -> None:
    """Save tensors to safetensors format.

    Args:
        tensors: Dict of layer_name -> tensor
        path: Output path
    """
    try:
        from safetensors.numpy import save_file

        save_file(tensors, str(path))
    except ImportError:
        import torch

        torch_tensors = {k: torch.from_numpy(v) for k, v in tensors.items()}
        torch.save(torch_tensors, path)


# ═══════════════════════════════════════════════════════════════════════════════
# Model Merger Class
# ═══════════════════════════════════════════════════════════════════════════════


class ModelMerger:
    """Merges model weights using various algorithms.

    Supports out-of-core processing for memory efficiency.
    """

    def __init__(self, cache_dir: Path | None = None):
        """Initialize merger.

        Args:
            cache_dir: Directory for caching downloaded models
        """
        self.cache_dir = cache_dir or Path.home() / ".cache" / "gaius" / "models"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def merge(self, config: MergeConfig) -> MergeResult:
        """Execute a merge operation.

        Args:
            config: Merge configuration

        Returns:
            MergeResult with outcome
        """
        import time

        start_time = time.time()
        result = MergeResult(
            success=False,
            method=config.method,
            source_models=[s.model_id for s in config.sources],
            parent_versions=[s.version_id for s in config.sources if s.version_id],
        )

        # Validate config
        errors = config.validate()
        if errors:
            result.error = "; ".join(errors)
            return result

        try:
            # Get model paths
            model_paths = await self._resolve_model_paths(config.sources)

            # Execute merge based on method
            if config.method == MergeMethod.LINEAR:
                output = await self._merge_linear(model_paths, config)
            elif config.method == MergeMethod.SLERP:
                output = await self._merge_slerp(model_paths, config)
            elif config.method == MergeMethod.TASK_ARITHMETIC:
                output = await self._merge_task_arithmetic(model_paths, config)
            elif config.method == MergeMethod.TIES:
                output = await self._merge_ties(model_paths, config)
            elif config.method == MergeMethod.DARE:
                output = await self._merge_dare(model_paths, config)
            elif config.method == MergeMethod.DARE_TIES:
                output = await self._merge_dare_ties(model_paths, config)
            else:
                result.error = f"Unknown merge method: {config.method}"
                return result

            # Save output
            if config.output_path:
                output_path = Path(config.output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                save_safetensors(output, output_path)
                result.output_path = str(output_path)

            result.success = True
            result.layers_processed = len(output)
            result.total_parameters = sum(t.size for t in output.values())

        except Exception as e:
            logger.exception(f"Merge failed: {e}")
            result.error = str(e)

        result.duration_ms = int((time.time() - start_time) * 1000)
        return result

    async def _resolve_model_paths(
        self, sources: list[ModelSource]
    ) -> list[tuple[ModelSource, Path]]:
        """Resolve model IDs to local paths, downloading if needed.

        Args:
            sources: Model sources

        Returns:
            List of (source, path) tuples
        """
        resolved = []

        for source in sources:
            # Check if it's a local path
            local_path = Path(source.model_id)
            if local_path.exists():
                resolved.append((source, local_path))
                continue

            # Try HuggingFace hub
            try:
                from huggingface_hub import hf_hub_download, snapshot_download

                # Download model files
                model_dir = Path(
                    snapshot_download(
                        source.model_id,
                        cache_dir=str(self.cache_dir),
                        local_files_only=False,
                    )
                )

                # Find safetensors or pytorch file
                safetensors = list(model_dir.glob("*.safetensors"))
                if safetensors:
                    resolved.append((source, safetensors[0]))
                else:
                    pytorch = list(model_dir.glob("*.bin")) + list(
                        model_dir.glob("*.pt")
                    )
                    if pytorch:
                        resolved.append((source, pytorch[0]))
                    else:
                        raise FileNotFoundError(
                            f"No model weights found in {model_dir}"
                        )

            except ImportError:
                raise ImportError(
                    "huggingface_hub required for downloading models"
                )

        return resolved

    async def _merge_linear(
        self, model_paths: list[tuple[ModelSource, Path]], config: MergeConfig
    ) -> dict[str, np.ndarray]:
        """Linear weighted average merge."""
        weights = [s.weight for s, _ in model_paths]
        if config.normalize_weights:
            total = sum(weights)
            weights = [w / total for w in weights]

        # Load first model to get layer structure
        result = {}
        first_source, first_path = model_paths[0]

        for layer_name, tensor in iter_safetensors_layers(first_path):
            # Collect this layer from all models
            layer_tensors = [weights[0] * tensor]

            for i, (source, path) in enumerate(model_paths[1:], 1):
                for name, t in iter_safetensors_layers(path):
                    if name == layer_name:
                        layer_tensors.append(weights[i] * t)
                        break

            # Sum weighted tensors
            result[layer_name] = sum(layer_tensors)

        return result

    async def _merge_slerp(
        self, model_paths: list[tuple[ModelSource, Path]], config: MergeConfig
    ) -> dict[str, np.ndarray]:
        """SLERP merge (2 models only)."""
        (source_a, path_a), (source_b, path_b) = model_paths
        t = config.interpolation_t

        result = {}

        for layer_name, tensor_a in iter_safetensors_layers(path_a):
            # Get corresponding layer from model B
            tensor_b = None
            for name, t_b in iter_safetensors_layers(path_b):
                if name == layer_name:
                    tensor_b = t_b
                    break

            if tensor_b is not None:
                result[layer_name] = slerp(tensor_a, tensor_b, t)
            else:
                result[layer_name] = tensor_a
                logger.warning(f"Layer {layer_name} not found in second model")

        return result

    async def _merge_task_arithmetic(
        self, model_paths: list[tuple[ModelSource, Path]], config: MergeConfig
    ) -> dict[str, np.ndarray]:
        """Task arithmetic merge: add weighted task vectors to base."""
        # Find base model
        base_source, base_path = next(
            (s, p) for s, p in model_paths if s.is_base
        )
        fine_tuned = [(s, p) for s, p in model_paths if not s.is_base]

        result = {}

        for layer_name, base_tensor in iter_safetensors_layers(base_path):
            # Compute weighted task vectors
            merged_tv = np.zeros_like(base_tensor)

            for source, path in fine_tuned:
                for name, ft_tensor in iter_safetensors_layers(path):
                    if name == layer_name:
                        task_vector = compute_task_vector(ft_tensor, base_tensor)
                        merged_tv += source.weight * task_vector
                        break

            # Add merged task vector to base
            result[layer_name] = base_tensor + merged_tv

        return result

    async def _merge_ties(
        self, model_paths: list[tuple[ModelSource, Path]], config: MergeConfig
    ) -> dict[str, np.ndarray]:
        """TIES merge: Trim, Elect Sign, Merge."""
        # Find base model
        base_source, base_path = next(
            (s, p) for s, p in model_paths if s.is_base
        )
        fine_tuned = [(s, p) for s, p in model_paths if not s.is_base]

        result = {}

        for layer_name, base_tensor in iter_safetensors_layers(base_path):
            # Collect task vectors for this layer
            task_vectors = []
            weights = []

            for source, path in fine_tuned:
                for name, ft_tensor in iter_safetensors_layers(path):
                    if name == layer_name:
                        task_vectors.append(compute_task_vector(ft_tensor, base_tensor))
                        weights.append(source.weight)
                        break

            if task_vectors:
                merged_tv = ties_merge(
                    task_vectors,
                    weights,
                    density=config.ties_density,
                    lambda_scale=config.ties_lambda,
                )
                result[layer_name] = base_tensor + merged_tv
            else:
                result[layer_name] = base_tensor

        return result

    async def _merge_dare(
        self, model_paths: list[tuple[ModelSource, Path]], config: MergeConfig
    ) -> dict[str, np.ndarray]:
        """DARE merge: Drop And REscale."""
        # Find base model
        base_source, base_path = next(
            (s, p) for s, p in model_paths if s.is_base
        )
        fine_tuned = [(s, p) for s, p in model_paths if not s.is_base]

        result = {}

        for layer_name, base_tensor in iter_safetensors_layers(base_path):
            # Collect and sparsify task vectors
            sparse_tvs = []
            weights = []

            for i, (source, path) in enumerate(fine_tuned):
                for name, ft_tensor in iter_safetensors_layers(path):
                    if name == layer_name:
                        tv = compute_task_vector(ft_tensor, base_tensor)
                        sparse_tv = dare_sparsify(
                            tv,
                            drop_rate=config.dare_drop_rate,
                            rescale=config.dare_rescale,
                            seed=hash(layer_name) + i,  # Deterministic per layer
                        )
                        sparse_tvs.append(sparse_tv)
                        weights.append(source.weight)
                        break

            if sparse_tvs:
                merged_tv = linear_merge(sparse_tvs, weights)
                result[layer_name] = base_tensor + merged_tv
            else:
                result[layer_name] = base_tensor

        return result

    async def _merge_dare_ties(
        self, model_paths: list[tuple[ModelSource, Path]], config: MergeConfig
    ) -> dict[str, np.ndarray]:
        """DARE-TIES merge: DARE sparsification + TIES sign election."""
        # Find base model
        base_source, base_path = next(
            (s, p) for s, p in model_paths if s.is_base
        )
        fine_tuned = [(s, p) for s, p in model_paths if not s.is_base]

        result = {}

        for layer_name, base_tensor in iter_safetensors_layers(base_path):
            # Collect task vectors
            task_vectors = []
            weights = []

            for source, path in fine_tuned:
                for name, ft_tensor in iter_safetensors_layers(path):
                    if name == layer_name:
                        task_vectors.append(compute_task_vector(ft_tensor, base_tensor))
                        weights.append(source.weight)
                        break

            if task_vectors:
                merged_tv = dare_ties_merge(
                    task_vectors,
                    weights,
                    drop_rate=config.dare_drop_rate,
                    density=config.ties_density,
                    lambda_scale=config.ties_lambda,
                    seed=hash(layer_name),
                )
                result[layer_name] = base_tensor + merged_tv
            else:
                result[layer_name] = base_tensor

        return result


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level API
# ═══════════════════════════════════════════════════════════════════════════════

_merger: ModelMerger | None = None


def get_merger() -> ModelMerger:
    """Get or create the model merger singleton."""
    global _merger
    if _merger is None:
        _merger = ModelMerger()
    return _merger


async def merge_models(config: MergeConfig) -> MergeResult:
    """Convenience function to merge models.

    Args:
        config: Merge configuration

    Returns:
        MergeResult with outcome
    """
    merger = get_merger()
    return await merger.merge(config)
