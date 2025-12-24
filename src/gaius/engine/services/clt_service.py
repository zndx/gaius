"""Cross-Layer Transcoder (CLT) service for the Engine.

Manages CLT model lifecycle and provides interpretable sparse feature
extraction for agent collaboration.

All CLT operations run in the engine - clients (CLI/TUI/MCP) receive
extracted features, projections, and traces via gRPC.

Key responsibilities:
- Load/unload CLT model on appropriate GPU via subprocess worker
- Extract sparse features from agent responses
- Project features to ColNomic embedding space for grid visualization
- Maintain exploration traces for time-delay dynamics
- Compute feature consensus across agents

Architecture:
    Client → gRPC → Engine → CLTService → CLTWorker (subprocess) → GPU
                          ↓
              Features/Projections/Traces
                          ↓
                    Client (display only)

GPU Isolation:
    CLT runs in a subprocess with CUDA_VISIBLE_DEVICES=4 to isolate from
    vLLM endpoints on GPUs 0-3. This avoids CUDA memory fragmentation and
    allows the engine to manage GPU allocation discretely.
"""

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from gaius.models.clt import (
    CLTSpec,
    CLT_MODELS,
    SparseFeature,
)

logger = logging.getLogger(__name__)


# Projection dimensions
CLT_FEATURE_DIM = 20_480  # Sparse feature dimension per layer
COLNOMIC_DIM = 128  # ColNomic embedding dimension


@dataclass
class AgentCLTState:
    """CLT state for a single agent.

    Tracks features, embeddings, and exploration trace.
    """

    role: str
    sparse_features: dict[int, float] = field(default_factory=dict)  # feature_idx -> activation
    embedding: np.ndarray | None = None  # 128-dim ColNomic-compatible
    trace_history: list[np.ndarray] = field(default_factory=list)  # Time-delay embeddings
    grid_position: tuple[int, int] = (9, 9)  # Default center

    def push_to_trace(self, embedding: np.ndarray, max_history: int = 4) -> None:
        """Add current embedding to trace history."""
        self.trace_history.insert(0, embedding)
        if len(self.trace_history) > max_history:
            self.trace_history = self.trace_history[:max_history]


@dataclass
class SwarmCLTResult:
    """CLT-enhanced swarm result.

    Contains all CLT-specific data alongside standard swarm outputs.
    """

    domain: str
    agent_states: dict[str, AgentCLTState] = field(default_factory=dict)
    consensus_features: dict[int, float] = field(default_factory=dict)  # Shared features
    feature_overlap: dict[tuple[str, str], float] = field(default_factory=dict)  # Agent alignment


class CLTProjectionBridge:
    """Projects CLT sparse features into ColNomic embedding space.

    Uses sparse random projection (Johnson-Lindenstrauss) to map
    20,480-dim sparse features to 128-dim embeddings compatible
    with KB document embeddings.
    """

    def __init__(self, seed: int = 42):
        """Initialize projection matrix."""
        rng = np.random.RandomState(seed)
        self._projection = self._create_sparse_projection(
            CLT_FEATURE_DIM, COLNOMIC_DIM, rng
        )

    def _create_sparse_projection(
        self,
        input_dim: int,
        output_dim: int,
        rng: np.random.RandomState,
        density: float = 0.1,
    ) -> np.ndarray:
        """Create sparse random projection matrix.

        Uses ternary random projection: {-1, 0, +1} with sparsity.
        More efficient than dense Gaussian for sparse inputs.
        """
        matrix = np.zeros((output_dim, input_dim), dtype=np.float32)
        nnz_per_row = int(input_dim * density)

        for i in range(output_dim):
            indices = rng.choice(input_dim, nnz_per_row, replace=False)
            signs = rng.choice([-1, 1], nnz_per_row)
            matrix[i, indices] = signs / np.sqrt(nnz_per_row)

        return matrix

    def project(self, sparse_features: dict[int, float]) -> np.ndarray:
        """Project sparse features to ColNomic-compatible embedding.

        Args:
            sparse_features: Dict mapping feature_idx to activation

        Returns:
            128-dim L2-normalized embedding
        """
        output = np.zeros(COLNOMIC_DIM, dtype=np.float32)

        for feature_idx, activation in sparse_features.items():
            if 0 <= feature_idx < CLT_FEATURE_DIM:
                output += self._projection[:, feature_idx] * activation

        # L2 normalize for compatibility with KB embeddings
        norm = np.linalg.norm(output)
        if norm > 0:
            output = output / norm

        return output


class CLTService:
    """CLT service for the Gaius Engine.

    Manages CLT model subprocess and provides feature extraction, projection,
    and trace tracking for swarm agents.

    Uses a subprocess worker with isolated GPU to avoid CUDA memory conflicts
    with vLLM endpoints. GPU is allocated by the orchestrator via the workload
    system - CLTService does NOT manage its own GPU allocation.

    Fail-Fast Design:
        - Requires explicit gpu_index from caller (orchestrator)
        - No fallback GPU detection or dynamic allocation
        - If no GPU provided, fails loudly with guidance
    """

    def __init__(
        self,
        model_name: str = "qwen3-1.7b",
        gpu_index: int | None = None,
    ):
        """Initialize CLT service.

        Args:
            model_name: Key in CLT_MODELS registry
            gpu_index: GPU index to use (REQUIRED - allocated by orchestrator)

        Raises:
            ValueError: If model_name is unknown
            RuntimeError: If gpu_index not provided (fail-fast)
        """
        if model_name not in CLT_MODELS:
            raise ValueError(
                f"Unknown CLT model: {model_name}. "
                f"Available: {list(CLT_MODELS.keys())}"
            )

        if gpu_index is None:
            # Fail-fast: GPU must be provided by orchestrator
            raise RuntimeError(
                "CLTService requires explicit gpu_index from orchestrator.\n"
                "  The workload system should allocate GPU before creating CLTService.\n"
                "  Guru Meditation: #CLT.00000001.NOGPU\n"
                "  Fix: Use /swarm clt to run CLT via the workload scheduler"
            )

        self.spec = CLT_MODELS[model_name]
        self.gpu_index = gpu_index
        self._worker: subprocess.Popen | None = None
        self._bridge = CLTProjectionBridge()
        self._agent_states: dict[str, AgentCLTState] = {}
        self._loaded = False

    def ensure_loaded(self) -> None:
        """Ensure CLT worker subprocess is running.

        Uses the gpu_index provided at construction (from orchestrator).
        """
        if self._loaded and self._worker is not None and self._worker.poll() is None:
            return

        # Use orchestrator-assigned GPU (validated in __init__)
        # Spawn worker subprocess with isolated GPU
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = str(self.gpu_index)
        env["HF_HOME"] = os.environ.get("HF_HOME", "/raid/cache/huggingface")

        logger.info(f"Starting CLT worker on GPU {self.gpu_index}")

        self._worker = subprocess.Popen(
            [sys.executable, "-m", "gaius.engine.services.clt_worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1,  # Line buffered
        )

        # Send load command and wait for response
        response = self._send_command({"method": "load"})
        if response.get("result") == "ok":
            self._loaded = True
            logger.info("CLT worker ready")
        else:
            error = response.get("error", {}).get("message", "Unknown error")
            raise RuntimeError(f"CLT worker failed to load: {error}")

    def _send_command(self, cmd: dict, timeout: float = 120.0) -> dict:
        """Send command to worker and get response.

        Args:
            cmd: Command dict with method and params
            timeout: Timeout in seconds (default 120s for model loading)

        Returns:
            Response dict from worker
        """
        if self._worker is None or self._worker.poll() is not None:
            raise RuntimeError("CLT worker not running")

        assert self._worker.stdin is not None
        assert self._worker.stdout is not None

        # Send command
        self._worker.stdin.write(json.dumps(cmd) + "\n")
        self._worker.stdin.flush()

        # Read response (with timeout via select would be better, but for simplicity...)
        import select
        import time

        start = time.time()
        while True:
            if time.time() - start > timeout:
                raise TimeoutError(f"CLT worker timeout after {timeout}s")

            # Check if worker has output ready
            ready, _, _ = select.select([self._worker.stdout], [], [], 1.0)
            if ready:
                line = self._worker.stdout.readline()
                if line:
                    return json.loads(line)

            # Check if worker died
            if self._worker.poll() is not None:
                stderr = self._worker.stderr.read() if self._worker.stderr else ""
                raise RuntimeError(f"CLT worker died: {stderr}")

    def unload(self) -> None:
        """Stop CLT worker subprocess."""
        if self._worker is not None:
            try:
                self._send_command({"method": "shutdown"}, timeout=5.0)
            except Exception:
                pass
            self._worker.terminate()
            self._worker.wait(timeout=5.0)
            self._worker = None
            self._loaded = False
            logger.info("CLT worker stopped")

    @property
    def is_loaded(self) -> bool:
        """Check if CLT worker is running."""
        return self._loaded and self._worker is not None and self._worker.poll() is None

    def extract_features(self, text: str, role: str) -> AgentCLTState:
        """Extract CLT features from agent response and update state.

        Args:
            text: Agent response text
            role: Agent role name

        Returns:
            Updated AgentCLTState with features, embedding, and position
        """
        self.ensure_loaded()

        # Call worker to extract features
        response = self._send_command({
            "method": "extract",
            "params": {"text": text, "top_k": 115}
        })

        if "error" in response:
            raise RuntimeError(f"CLT extraction failed: {response['error']}")

        # Aggregate features across positions (sum activations)
        sparse_dict: dict[int, float] = {}
        for feature in response["result"]["features"]:
            idx = feature["feature_idx"]
            sparse_dict[idx] = sparse_dict.get(idx, 0) + feature["activation"]

        # Project to ColNomic space
        embedding = self._bridge.project(sparse_dict)

        # Get or create agent state
        if role not in self._agent_states:
            self._agent_states[role] = AgentCLTState(role=role)

        state = self._agent_states[role]
        state.sparse_features = sparse_dict
        state.embedding = embedding
        state.push_to_trace(embedding)

        return state

    def update_grid_positions(self, projector: Any | None = None) -> None:
        """Update grid positions for all agents using UMAP projector.

        Args:
            projector: KB grid projector with fitted UMAP (optional)
        """
        for role, state in self._agent_states.items():
            if state.embedding is None:
                continue

            if projector is not None and hasattr(projector, '_projector'):
                try:
                    coords_2d = projector._projector.transform([state.embedding])
                    grid_coords = projector._normalize_to_grid(coords_2d)
                    x, y = int(grid_coords[0, 0]), int(grid_coords[0, 1])
                    state.grid_position = (max(0, min(18, x)), max(0, min(18, y)))
                except Exception as e:
                    logger.warning(f"Grid projection failed for {role}: {e}")
            else:
                # Random fallback (shouldn't happen in production)
                import random
                state.grid_position = (random.randint(0, 18), random.randint(0, 18))

    def compute_consensus(self) -> dict[int, float]:
        """Compute feature consensus across all agents.

        Returns features that appear in multiple agents' outputs.
        """
        feature_counts: dict[int, list[float]] = {}

        for state in self._agent_states.values():
            for idx, activation in state.sparse_features.items():
                if idx not in feature_counts:
                    feature_counts[idx] = []
                feature_counts[idx].append(activation)

        # Consensus = features appearing in 2+ agents, weighted by mean activation
        consensus: dict[int, float] = {}
        for idx, activations in feature_counts.items():
            if len(activations) >= 2:
                consensus[idx] = float(np.mean(activations))

        return consensus

    def compute_overlap(self) -> dict[tuple[str, str], float]:
        """Compute pairwise feature overlap between agents.

        Returns cosine similarity of feature vectors.
        """
        overlap: dict[tuple[str, str], float] = {}
        roles = list(self._agent_states.keys())

        for i, r1 in enumerate(roles):
            for r2 in roles[i + 1:]:
                s1 = self._agent_states[r1]
                s2 = self._agent_states[r2]

                if s1.embedding is None or s2.embedding is None:
                    continue

                # Cosine similarity
                dot = float(np.dot(s1.embedding, s2.embedding))
                overlap[(r1, r2)] = dot

        return overlap

    def get_agent_positions(self) -> list[tuple[str, int, int, str]]:
        """Get agent positions for grid visualization.

        Returns:
            List of (role, x, y, color) tuples
        """
        from gaius.agents.roles import get_role_colors

        role_colors = get_role_colors()
        positions = []
        for role, state in self._agent_states.items():
            x, y = state.grid_position
            color = role_colors.get(role, "white")
            positions.append((role, x, y, color))

        return positions

    def get_agent_traces(self) -> dict[str, list[tuple[int, int]]]:
        """Get exploration traces for grid visualization.

        Returns:
            Dict mapping role to list of (x, y) positions
        """
        traces: dict[str, list[tuple[int, int]]] = {}

        for role, state in self._agent_states.items():
            # Current position plus historical positions
            trace_positions = [state.grid_position]
            # Note: Full trace projection would require storing historical grid positions
            # For now, we just return the current position
            traces[role] = trace_positions

        return traces

    def get_swarm_result(self, domain: str) -> SwarmCLTResult:
        """Get complete CLT swarm result.

        Args:
            domain: Analysis domain

        Returns:
            SwarmCLTResult with all agent states and consensus
        """
        return SwarmCLTResult(
            domain=domain,
            agent_states=self._agent_states.copy(),
            consensus_features=self.compute_consensus(),
            feature_overlap=self.compute_overlap(),
        )

    def clear_states(self) -> None:
        """Clear all agent states (between swarm runs)."""
        self._agent_states.clear()

    def get_status(self) -> dict[str, Any]:
        """Get service status."""
        worker_pid = None
        if self._worker is not None and self._worker.poll() is None:
            worker_pid = self._worker.pid

        return {
            "loaded": self.is_loaded,
            "model": self.spec.base_model if self._loaded else None,
            "transcoder": self.spec.transcoder_name if self._loaded else None,
            "gpu_index": self.gpu_index,  # GPU assigned by orchestrator
            "worker_pid": worker_pid,
            "agents": list(self._agent_states.keys()),
            "feature_dim": CLT_FEATURE_DIM,
            "projection_dim": COLNOMIC_DIM,
        }


# Note: get_clt_service() is DEPRECATED for direct use.
# CLT should be accessed via the orchestrator's workload system.
# The orchestrator creates CLTService instances with allocated GPUs.
