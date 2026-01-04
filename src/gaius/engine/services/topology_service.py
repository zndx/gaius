"""Topology Service for temporal dynamics tracking.

Captures the evolution of semantic space over time, enabling:
1. Drift detection: How consensus positions change
2. Well depth: Entrenchment measurement (1/variance)
3. NG-RC integration: Forward dynamics prediction
4. Non-autonomous dynamics: dx/dt = f(x, KB(t))

Design Principles:
- Every swarm run is a snapshot of a living topology
- KB growth raises the floor of old potential wells
- Productive instability prevents ossification

Key Concepts:
- Swarm Snapshot: Point-in-time capture of agent positions and embeddings
- Topology Drift: Rate of change of consensus position (dx/dt)
- Well Depth: 1/variance - measures entrenchment (high = stable but stuck)
- Attractor: Named stable state in semantic space that can drift over time
- NG-RC: Reservoir computing model that learns flow field for prediction
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class SwarmSnapshot:
    """Point-in-time capture of swarm state."""

    run_id: uuid.UUID
    domain: str
    captured_at: datetime
    kb_version: Optional[str] = None
    kb_document_count: Optional[int] = None
    consensus_embedding: Optional[np.ndarray] = None
    consensus_variance: float = 0.0
    consensus_grid_x: int = 9
    consensus_grid_y: int = 9
    h0_count: int = 1  # Connected components
    h1_count: int = 0  # Loops
    position_entropy: float = 0.0
    feature_entropy: float = 0.0
    n_agents: int = 0
    query_text: Optional[str] = None


@dataclass
class AgentPosition:
    """Agent position within a snapshot."""

    agent_role: str
    embedding: Optional[np.ndarray] = None
    grid_x: int = 9
    grid_y: int = 9
    top_features: dict[int, float] = field(default_factory=dict)
    distance_from_consensus: float = 0.0
    trace_history: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class DriftMetrics:
    """Computed drift metrics for a domain."""

    domain: str
    computed_at: datetime
    time_window_hours: int = 24
    n_snapshots: int = 0
    drift_magnitude: float = 0.0
    drift_direction: tuple[float, float] = (0.0, 0.0)
    well_depth: float = 0.0
    lyapunov_exponent: float = 0.0
    mean_variance: float = 0.0
    variance_trend: float = 0.0
    kb_growth_rate: float = 0.0
    is_bifurcation: bool = False


@dataclass
class SemanticAttractor:
    """Named stable state in semantic space."""

    name: str
    domain: str
    current_embedding: Optional[np.ndarray] = None
    current_grid_x: int = 9
    current_grid_y: int = 9
    mean_well_depth: float = 0.0
    total_drift_distance: float = 0.0
    first_observed: Optional[datetime] = None
    last_observed: Optional[datetime] = None
    is_active: bool = True


class TopologyService:
    """Service for temporal topology tracking and drift analysis.

    Persists swarm snapshots, computes drift metrics, and manages
    semantic attractors. Provides integration points for NG-RC
    forward dynamics prediction.

    Usage:
        # In swarm execution:
        snapshot = await topology_service.save_snapshot(swarm_result, domain)

        # In CLI commands:
        drift = await topology_service.compute_drift("pension", hours=24)
        well_depth = drift.well_depth

        # In TUI visualization:
        history = await topology_service.get_snapshot_history("pension", limit=50)
    """

    def __init__(self, db_pool: Optional[Any] = None):
        """Initialize topology service.

        Args:
            db_pool: asyncpg connection pool for database operations
        """
        self._db_pool = db_pool
        logger.info("TopologyService initialized")

    async def save_snapshot(
        self,
        domain: str,
        run_id: uuid.UUID,
        agent_states: dict[str, Any],
        consensus_embedding: Optional[np.ndarray] = None,
        kb_version: Optional[str] = None,
        kb_document_count: Optional[int] = None,
        query_text: Optional[str] = None,
    ) -> int:
        """Persist a swarm snapshot to the database.

        Args:
            domain: Domain context (e.g., 'pension', 'kudu')
            run_id: Unique ID for this swarm run
            agent_states: Dict mapping role to AgentCLTState
            consensus_embedding: Computed consensus embedding
            kb_version: Git hash or timestamp of KB state
            kb_document_count: Number of KB docs at time of snapshot
            query_text: Original query that triggered the swarm

        Returns:
            snapshot_id of the created record
        """
        if self._db_pool is None:
            logger.warning("TopologyService: No database pool, skipping snapshot persistence")
            return -1

        # Compute consensus metrics
        embeddings = []
        grid_positions = []

        for role, state in agent_states.items():
            if hasattr(state, 'embedding') and state.embedding is not None:
                embeddings.append(state.embedding)
            if hasattr(state, 'grid_position'):
                grid_positions.append(state.grid_position)

        # Compute consensus
        if consensus_embedding is None and embeddings:
            consensus_embedding = np.mean(embeddings, axis=0)

        # Compute variance around consensus
        consensus_variance = 0.0
        if consensus_embedding is not None and embeddings:
            distances = [np.linalg.norm(e - consensus_embedding) for e in embeddings]
            consensus_variance = float(np.var(distances))

        # Compute grid centroid
        consensus_grid_x = 9
        consensus_grid_y = 9
        if grid_positions:
            consensus_grid_x = int(np.mean([p[0] for p in grid_positions]))
            consensus_grid_y = int(np.mean([p[1] for p in grid_positions]))

        # Compute position entropy
        position_entropy = 0.0
        if grid_positions:
            position_entropy = self._compute_position_entropy(grid_positions)

        async with self._db_pool.acquire() as conn:
            # Insert snapshot
            snapshot_id = await conn.fetchval(
                """
                INSERT INTO meta.swarm_snapshots (
                    run_id, domain, kb_version, kb_document_count,
                    consensus_embedding, consensus_variance,
                    consensus_grid_x, consensus_grid_y,
                    h0_count, h1_count, position_entropy, feature_entropy,
                    n_agents, query_text
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                RETURNING snapshot_id
                """,
                str(run_id),
                domain,
                kb_version,
                kb_document_count,
                consensus_embedding.tolist() if consensus_embedding is not None else None,
                consensus_variance,
                consensus_grid_x,
                consensus_grid_y,
                self._compute_h0(grid_positions) if grid_positions else 1,
                self._compute_h1(grid_positions) if grid_positions else 0,
                position_entropy,
                0.0,  # feature_entropy - TODO
                len(agent_states),
                query_text,
            )

            # Insert agent positions
            for role, state in agent_states.items():
                embedding = None
                grid_x, grid_y = 9, 9
                top_features = {}
                distance = 0.0

                if hasattr(state, 'embedding') and state.embedding is not None:
                    embedding = state.embedding
                    if consensus_embedding is not None:
                        distance = float(np.linalg.norm(embedding - consensus_embedding))

                if hasattr(state, 'grid_position'):
                    grid_x, grid_y = state.grid_position

                if hasattr(state, 'sparse_features'):
                    # Take top 20 features by activation
                    features = sorted(
                        state.sparse_features.items(),
                        key=lambda x: x[1],
                        reverse=True
                    )[:20]
                    top_features = dict(features)

                trace_history = []
                if hasattr(state, 'trace_history') and state.trace_history:
                    # Convert embeddings to grid positions (simplified)
                    trace_history = [(grid_x, grid_y)]

                await conn.execute(
                    """
                    INSERT INTO meta.swarm_agent_positions (
                        snapshot_id, agent_role, embedding, grid_x, grid_y,
                        top_features, distance_from_consensus, trace_history
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    snapshot_id,
                    role,
                    embedding.tolist() if embedding is not None else None,
                    grid_x,
                    grid_y,
                    json.dumps([{"idx": k, "activation": v} for k, v in top_features.items()]),
                    distance,
                    json.dumps(trace_history),
                )

            logger.info(f"Saved swarm snapshot {snapshot_id} for domain '{domain}' with {len(agent_states)} agents")
            return snapshot_id

    async def compute_drift(
        self,
        domain: str,
        hours: int = 24,
    ) -> DriftMetrics:
        """Compute drift metrics for a domain.

        Analyzes how consensus positions have changed over the time window.

        Args:
            domain: Domain to analyze
            hours: Time window in hours

        Returns:
            DriftMetrics with drift velocity, well depth, stability
        """
        if self._db_pool is None:
            return DriftMetrics(domain=domain, computed_at=datetime.now(timezone.utc))

        async with self._db_pool.acquire() as conn:
            # Get snapshots within time window
            rows = await conn.fetch(
                """
                SELECT snapshot_id, captured_at, consensus_embedding,
                       consensus_variance, consensus_grid_x, consensus_grid_y,
                       kb_document_count, n_agents
                FROM meta.swarm_snapshots
                WHERE domain = $1
                  AND captured_at > NOW() - INTERVAL '%s hours'
                ORDER BY captured_at ASC
                """,
                domain,
                hours,
            )

            if len(rows) < 2:
                return DriftMetrics(
                    domain=domain,
                    computed_at=datetime.now(timezone.utc),
                    time_window_hours=hours,
                    n_snapshots=len(rows),
                )

            # Extract time series
            embeddings = []
            variances = []
            grid_positions = []
            timestamps = []
            kb_counts = []

            for row in rows:
                timestamps.append(row['captured_at'])
                variances.append(row['consensus_variance'] or 0.0)
                grid_positions.append((row['consensus_grid_x'], row['consensus_grid_y']))
                if row['consensus_embedding']:
                    embeddings.append(np.array(row['consensus_embedding']))
                if row['kb_document_count']:
                    kb_counts.append(row['kb_document_count'])

            # Compute drift velocity (change in consensus position over time)
            drift_magnitude = 0.0
            drift_direction = (0.0, 0.0)

            if len(embeddings) >= 2:
                # Use embeddings for accurate drift
                first = embeddings[0]
                last = embeddings[-1]
                delta = last - first
                time_delta_hours = (timestamps[-1] - timestamps[0]).total_seconds() / 3600.0

                if time_delta_hours > 0:
                    velocity = delta / time_delta_hours
                    drift_magnitude = float(np.linalg.norm(velocity))

            if len(grid_positions) >= 2:
                # Grid-space drift direction
                dx = grid_positions[-1][0] - grid_positions[0][0]
                dy = grid_positions[-1][1] - grid_positions[0][1]
                time_delta_hours = (timestamps[-1] - timestamps[0]).total_seconds() / 3600.0
                if time_delta_hours > 0:
                    drift_direction = (dx / time_delta_hours, dy / time_delta_hours)

            # Compute well depth (1/variance)
            mean_variance = float(np.mean(variances)) if variances else 0.0
            well_depth = 1.0 / (mean_variance + 1e-6)  # Avoid division by zero

            # Variance trend (positive = increasing spread, negative = converging)
            variance_trend = 0.0
            if len(variances) >= 2:
                variance_trend = (variances[-1] - variances[0]) / max(hours, 1)

            # KB growth rate
            kb_growth_rate = 0.0
            if len(kb_counts) >= 2:
                time_delta_hours = (timestamps[-1] - timestamps[0]).total_seconds() / 3600.0
                if time_delta_hours > 0:
                    kb_growth_rate = (kb_counts[-1] - kb_counts[0]) / time_delta_hours

            # Lyapunov exponent approximation (simplified)
            # Negative = stable, positive = chaotic
            lyapunov = 0.0
            if len(embeddings) >= 3:
                # Look at divergence/convergence of trajectory
                initial_distances = []
                final_distances = []
                for i in range(len(embeddings) - 1):
                    d = np.linalg.norm(embeddings[i + 1] - embeddings[i])
                    if i < len(embeddings) // 2:
                        initial_distances.append(d)
                    else:
                        final_distances.append(d)

                if initial_distances and final_distances:
                    avg_initial = np.mean(initial_distances)
                    avg_final = np.mean(final_distances)
                    if avg_initial > 0:
                        lyapunov = np.log(avg_final / avg_initial + 1e-6)

            # Detect bifurcation (sudden increase in variance or multi-modal distribution)
            is_bifurcation = False
            if len(variances) >= 3:
                recent_var = np.mean(variances[-3:])
                older_var = np.mean(variances[:-3]) if len(variances) > 3 else variances[0]
                if recent_var > 2 * older_var:
                    is_bifurcation = True

            metrics = DriftMetrics(
                domain=domain,
                computed_at=datetime.now(timezone.utc),
                time_window_hours=hours,
                n_snapshots=len(rows),
                drift_magnitude=drift_magnitude,
                drift_direction=drift_direction,
                well_depth=well_depth,
                lyapunov_exponent=lyapunov,
                mean_variance=mean_variance,
                variance_trend=variance_trend,
                kb_growth_rate=kb_growth_rate,
                is_bifurcation=is_bifurcation,
            )

            # Persist drift metrics
            await conn.execute(
                """
                INSERT INTO meta.topology_drift (
                    domain, time_window_hours, n_snapshots,
                    centroid_drift_velocity, drift_magnitude,
                    drift_direction_grid_x, drift_direction_grid_y,
                    well_depth, lyapunov_exponent, mean_variance,
                    variance_trend, kb_growth_rate, is_bifurcation
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """,
                domain,
                hours,
                len(rows),
                None,  # TODO: store full velocity vector
                drift_magnitude,
                drift_direction[0],
                drift_direction[1],
                well_depth,
                lyapunov,
                mean_variance,
                variance_trend,
                kb_growth_rate,
                is_bifurcation,
            )

            return metrics

    async def get_snapshot_history(
        self,
        domain: str,
        limit: int = 50,
    ) -> list[SwarmSnapshot]:
        """Get recent snapshots for a domain.

        Args:
            domain: Domain to query
            limit: Maximum snapshots to return

        Returns:
            List of SwarmSnapshot objects ordered by time (newest first)
        """
        if self._db_pool is None:
            return []

        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM meta.swarm_snapshots
                WHERE domain = $1
                ORDER BY captured_at DESC
                LIMIT $2
                """,
                domain,
                limit,
            )

            return [
                SwarmSnapshot(
                    run_id=uuid.UUID(row['run_id']),
                    domain=row['domain'],
                    captured_at=row['captured_at'],
                    kb_version=row['kb_version'],
                    kb_document_count=row['kb_document_count'],
                    consensus_embedding=np.array(row['consensus_embedding']) if row['consensus_embedding'] else None,
                    consensus_variance=row['consensus_variance'] or 0.0,
                    consensus_grid_x=row['consensus_grid_x'] or 9,
                    consensus_grid_y=row['consensus_grid_y'] or 9,
                    h0_count=row['h0_count'] or 1,
                    h1_count=row['h1_count'] or 0,
                    position_entropy=row['position_entropy'] or 0.0,
                    feature_entropy=row['feature_entropy'] or 0.0,
                    n_agents=row['n_agents'] or 0,
                    query_text=row['query_text'],
                )
                for row in rows
            ]

    async def get_drift_history(
        self,
        domain: str,
        days: int = 7,
    ) -> list[DriftMetrics]:
        """Get drift computation history for a domain.

        Args:
            domain: Domain to query
            days: Number of days of history

        Returns:
            List of DriftMetrics ordered by time (newest first)
        """
        if self._db_pool is None:
            return []

        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM meta.topology_drift
                WHERE domain = $1
                  AND computed_at > NOW() - INTERVAL '%s days'
                ORDER BY computed_at DESC
                """,
                domain,
                days,
            )

            return [
                DriftMetrics(
                    domain=row['domain'],
                    computed_at=row['computed_at'],
                    time_window_hours=row['time_window_hours'] or 24,
                    n_snapshots=row['n_snapshots'] or 0,
                    drift_magnitude=row['drift_magnitude'] or 0.0,
                    drift_direction=(
                        row['drift_direction_grid_x'] or 0.0,
                        row['drift_direction_grid_y'] or 0.0,
                    ),
                    well_depth=row['well_depth'] or 0.0,
                    lyapunov_exponent=row['lyapunov_exponent'] or 0.0,
                    mean_variance=row['mean_variance'] or 0.0,
                    variance_trend=row['variance_trend'] or 0.0,
                    kb_growth_rate=row['kb_growth_rate'] or 0.0,
                    is_bifurcation=row['is_bifurcation'] or False,
                )
                for row in rows
            ]

    async def register_attractor(
        self,
        name: str,
        domain: str,
        embedding: np.ndarray,
        grid_x: int,
        grid_y: int,
    ) -> int:
        """Register a named semantic attractor.

        Attractors are stable states in semantic space that can drift
        over time. Use this to track how concepts like "pension" or
        "risk tolerance" change meaning.

        Args:
            name: Unique name for the attractor
            domain: Domain context
            embedding: 128-dim position in semantic space
            grid_x: Grid X position
            grid_y: Grid Y position

        Returns:
            attractor_id
        """
        if self._db_pool is None:
            return -1

        async with self._db_pool.acquire() as conn:
            now = datetime.now(timezone.utc)
            position_history = [
                {"ts": now.isoformat(), "embedding": embedding.tolist(), "grid": [grid_x, grid_y]}
            ]

            attractor_id = await conn.fetchval(
                """
                INSERT INTO meta.semantic_attractors (
                    domain, name, current_embedding,
                    current_grid_x, current_grid_y,
                    position_history, mean_well_depth, total_drift_distance,
                    first_observed, last_observed, is_active
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                RETURNING id
                """,
                domain,
                name,
                embedding.tolist(),
                grid_x,
                grid_y,
                json.dumps(position_history),
                0.0,
                0.0,
                now,
                now,
                True,
            )

            logger.info(f"Registered attractor '{name}' at ({grid_x}, {grid_y}) for domain '{domain}'")
            return attractor_id

    async def update_attractor(
        self,
        name: str,
        domain: str,
        embedding: np.ndarray,
        grid_x: int,
        grid_y: int,
    ) -> bool:
        """Update an attractor's position and track drift.

        Adds new position to history and updates drift statistics.

        Args:
            name: Attractor name
            domain: Domain context
            embedding: New 128-dim position
            grid_x: New grid X
            grid_y: New grid Y

        Returns:
            True if updated, False if attractor not found
        """
        if self._db_pool is None:
            return False

        async with self._db_pool.acquire() as conn:
            # Get current state
            row = await conn.fetchrow(
                """
                SELECT id, current_embedding, position_history, total_drift_distance
                FROM meta.semantic_attractors
                WHERE name = $1 AND domain = $2 AND is_active = TRUE
                """,
                name,
                domain,
            )

            if not row:
                return False

            # Calculate drift from previous position
            drift_distance = 0.0
            if row['current_embedding']:
                prev_embedding = np.array(row['current_embedding'])
                drift_distance = float(np.linalg.norm(embedding - prev_embedding))

            # Update position history
            history = json.loads(row['position_history'] or '[]')
            now = datetime.now(timezone.utc)
            history.append({
                "ts": now.isoformat(),
                "embedding": embedding.tolist(),
                "grid": [grid_x, grid_y],
            })

            # Keep only last 100 positions
            if len(history) > 100:
                history = history[-100:]

            await conn.execute(
                """
                UPDATE meta.semantic_attractors
                SET current_embedding = $1,
                    current_grid_x = $2,
                    current_grid_y = $3,
                    position_history = $4,
                    total_drift_distance = total_drift_distance + $5,
                    last_observed = NOW()
                WHERE id = $6
                """,
                embedding.tolist(),
                grid_x,
                grid_y,
                json.dumps(history),
                drift_distance,
                row['id'],
            )

            logger.debug(f"Updated attractor '{name}' - drift: {drift_distance:.4f}")
            return True

    async def get_attractors(self, domain: str) -> list[SemanticAttractor]:
        """Get all active attractors for a domain.

        Args:
            domain: Domain to query

        Returns:
            List of SemanticAttractor objects
        """
        if self._db_pool is None:
            return []

        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM meta.semantic_attractors
                WHERE domain = $1 AND is_active = TRUE
                ORDER BY last_observed DESC
                """,
                domain,
            )

            return [
                SemanticAttractor(
                    name=row['name'],
                    domain=row['domain'],
                    current_embedding=np.array(row['current_embedding']) if row['current_embedding'] else None,
                    current_grid_x=row['current_grid_x'] or 9,
                    current_grid_y=row['current_grid_y'] or 9,
                    mean_well_depth=row['mean_well_depth'] or 0.0,
                    total_drift_distance=row['total_drift_distance'] or 0.0,
                    first_observed=row['first_observed'],
                    last_observed=row['last_observed'],
                    is_active=row['is_active'],
                )
                for row in rows
            ]

    # ─────────────────────────────────────────────────────────────────────────
    # NG-RC Integration Points
    # ─────────────────────────────────────────────────────────────────────────

    async def get_training_data(
        self,
        domain: str,
        min_snapshots: int = 50,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Get time series data for NG-RC training.

        Returns (X, y) where:
        - X: (N-1, 128) array of input embeddings
        - y: (N-1, 128) array of next-step embeddings

        This is the training data for learning dx/dt = f(x).

        Args:
            domain: Domain to extract data from
            min_snapshots: Minimum snapshots required

        Returns:
            Tuple of (X, y) numpy arrays

        Raises:
            ValueError: If insufficient data
        """
        if self._db_pool is None:
            raise ValueError("TopologyService: No database pool")

        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT consensus_embedding, captured_at
                FROM meta.swarm_snapshots
                WHERE domain = $1
                  AND consensus_embedding IS NOT NULL
                ORDER BY captured_at ASC
                """,
                domain,
            )

            if len(rows) < min_snapshots:
                raise ValueError(
                    f"Insufficient data for NG-RC training: {len(rows)} < {min_snapshots}"
                )

            embeddings = np.array([row['consensus_embedding'] for row in rows])

            # Create input/output pairs for next-step prediction
            X = embeddings[:-1]  # t
            y = embeddings[1:]   # t+1

            return X, y

    async def save_ngrc_model(
        self,
        domain: str,
        model_weights: bytes,
        reservoir_size: int,
        spectral_radius: float,
        validation_mse: float,
        forecast_horizon: int,
        n_training_snapshots: int,
        training_time_span_hours: float,
    ) -> int:
        """Persist trained NG-RC model.

        Args:
            domain: Domain the model was trained on
            model_weights: Serialized model parameters
            reservoir_size: Reservoir hidden state size
            spectral_radius: Spectral radius of reservoir
            validation_mse: Mean squared error on held-out data
            forecast_horizon: Reliable prediction horizon (steps)
            n_training_snapshots: Number of snapshots used for training
            training_time_span_hours: Time span of training data

        Returns:
            model_id
        """
        if self._db_pool is None:
            return -1

        async with self._db_pool.acquire() as conn:
            # Deactivate previous models for this domain
            await conn.execute(
                """
                UPDATE meta.ngrc_models
                SET is_active = FALSE
                WHERE domain = $1 AND is_active = TRUE
                """,
                domain,
            )

            # Insert new model
            model_id = await conn.fetchval(
                """
                INSERT INTO meta.ngrc_models (
                    domain, model_weights, reservoir_size, spectral_radius,
                    validation_mse, forecast_horizon_steps,
                    n_training_snapshots, training_time_span_hours, is_active
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, TRUE)
                RETURNING id
                """,
                domain,
                model_weights,
                reservoir_size,
                spectral_radius,
                validation_mse,
                forecast_horizon,
                n_training_snapshots,
                training_time_span_hours,
            )

            logger.info(
                f"Saved NG-RC model for domain '{domain}' - "
                f"MSE: {validation_mse:.6f}, horizon: {forecast_horizon} steps"
            )
            return model_id

    async def load_ngrc_model(self, domain: str) -> Optional[bytes]:
        """Load active NG-RC model weights for a domain.

        Args:
            domain: Domain to load model for

        Returns:
            Serialized model weights, or None if no model
        """
        if self._db_pool is None:
            return None

        async with self._db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT model_weights FROM meta.ngrc_models
                WHERE domain = $1 AND is_active = TRUE
                """,
                domain,
            )

            return row['model_weights'] if row else None

    # ─────────────────────────────────────────────────────────────────────────
    # Helper Methods
    # ─────────────────────────────────────────────────────────────────────────

    def _compute_position_entropy(self, positions: list[tuple[int, int]]) -> float:
        """Compute entropy of grid positions.

        Higher entropy = more spread out.
        Lower entropy = more clustered.
        """
        if not positions:
            return 0.0

        # Create 19x19 histogram
        histogram = np.zeros((19, 19))
        for x, y in positions:
            if 0 <= x <= 18 and 0 <= y <= 18:
                histogram[x, y] += 1

        # Normalize to probability
        total = histogram.sum()
        if total == 0:
            return 0.0

        probabilities = histogram.flatten() / total
        probabilities = probabilities[probabilities > 0]

        # Shannon entropy
        return float(-np.sum(probabilities * np.log2(probabilities)))

    def _compute_h0(self, positions: list[tuple[int, int]]) -> int:
        """Compute H0 (connected components) of positions.

        Uses simple grid adjacency (8-connected).
        """
        if not positions:
            return 0

        # Simple connected components via flood fill
        visited = set()
        components = 0

        def neighbors(p):
            x, y = p
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = x + dx, y + dy
                    if (nx, ny) in positions and (nx, ny) not in visited:
                        yield (nx, ny)

        position_set = set(positions)

        for pos in positions:
            if pos not in visited:
                components += 1
                # BFS
                queue = [pos]
                while queue:
                    current = queue.pop(0)
                    if current in visited:
                        continue
                    visited.add(current)
                    for n in neighbors(current):
                        queue.append(n)

        return components

    def _compute_h1(self, positions: list[tuple[int, int]]) -> int:
        """Compute H1 (1-cycles/loops) of positions.

        Simplified: counts positions that form enclosed regions.
        For proper TDA, use giotto-tda.
        """
        # Placeholder - proper H1 requires persistent homology
        # This is a rough approximation based on position density
        if len(positions) < 4:
            return 0

        # Check for rough "loop" by looking at positions that enclose space
        # This is a simplification - proper implementation would use Rips complex
        return 0  # TODO: Implement with giotto-tda when available
