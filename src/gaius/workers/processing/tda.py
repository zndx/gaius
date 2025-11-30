"""Background TDA computation worker.

Periodically computes TDA features from KB embeddings and caches results.
Runs on a configurable schedule (default: hourly).

Usage:
    from gaius.workers.processing.tda import TDAWorker

    worker = TDAWorker()
    await worker.run_once()  # Manual trigger
    await worker.run_scheduled()  # Start scheduled loop
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from gaius.core.config import get_config
from gaius.core.projection import get_grid_manager, GridData
from gaius.core.tda import get_tda_manager, TDAFeatures


class TDAWorker:
    """Background worker for TDA computation.

    Computes topological features periodically to avoid
    blocking the UI during expensive computations.
    """

    def __init__(
        self,
        kb_root: Path | str | None = None,
        interval_minutes: int | None = None,
    ):
        """Initialize TDA worker.

        Args:
            kb_root: KB root directory
            interval_minutes: Computation interval (default: from config)
        """
        config = get_config()
        self.kb_root = Path(kb_root) if kb_root else Path(config.kb.root)

        # Get interval from config if not specified
        if interval_minutes is None:
            interval_minutes = config.tda.compute_interval_minutes
        self.interval_minutes = interval_minutes

        self._running = False
        self._last_run: datetime | None = None
        self._last_result: dict[str, Any] | None = None

    async def run_once(self) -> dict[str, Any]:
        """Run TDA computation once.

        Returns:
            Dict with grid_data and tda_features
        """
        result = {
            "timestamp": datetime.now().isoformat(),
            "grid_data": None,
            "tda_features": None,
            "error": None,
        }

        try:
            # Get grid manager (handles embedding projection)
            grid_manager = get_grid_manager(
                method=get_config().tda.projection_method,
                kb_root=str(self.kb_root),
            )

            # Project embeddings to grid
            grid_data = grid_manager.get_grid_data(force_refresh=True)
            result["grid_data"] = {
                "n_documents": grid_data.n_documents,
                "coverage": grid_data.coverage,
                "method": grid_data.method,
            }

            # Compute TDA if we have grid data
            if grid_data.points:
                import numpy as np

                # Get embeddings and grid coords for TDA
                # Note: We use the grid coordinates for TDA visualization
                grid_coords = np.array(
                    [(p.x, p.y) for p in grid_data.points]
                )

                # Get TDA manager
                tda_manager = get_tda_manager()

                # For TDA computation, we'd ideally use the original embeddings
                # but we can also compute on grid coordinates for visualization
                features = tda_manager.compute_features(
                    grid_coords,  # Using 2D coords for visualization-focused TDA
                    grid_coords,
                    force_refresh=True,
                )

                result["tda_features"] = features.to_dict()

            self._last_run = datetime.now()
            self._last_result = result

        except Exception as e:
            result["error"] = str(e)

        return result

    async def run_scheduled(self) -> None:
        """Run TDA computation on schedule.

        Runs continuously until stopped.
        """
        self._running = True

        while self._running:
            try:
                await self.run_once()
            except Exception:
                pass  # Log error but continue

            # Wait for next interval
            await asyncio.sleep(self.interval_minutes * 60)

    def stop(self) -> None:
        """Stop scheduled computation."""
        self._running = False

    @property
    def last_run(self) -> datetime | None:
        """Get timestamp of last computation."""
        return self._last_run

    @property
    def last_result(self) -> dict[str, Any] | None:
        """Get results from last computation."""
        return self._last_result

    def get_cached_grid_data(self) -> GridData | None:
        """Get cached grid data from last computation."""
        grid_manager = get_grid_manager()
        return grid_manager._cached_data

    def get_cached_tda_features(self) -> TDAFeatures | None:
        """Get cached TDA features from last computation."""
        tda_manager = get_tda_manager()
        return tda_manager._cached_features


# Module-level singleton
_tda_worker: TDAWorker | None = None


def get_tda_worker(
    kb_root: Path | str | None = None,
    interval_minutes: int | None = None,
) -> TDAWorker:
    """Get or create TDA worker singleton."""
    global _tda_worker
    if _tda_worker is None:
        _tda_worker = TDAWorker(kb_root, interval_minutes)
    return _tda_worker


async def run_tda_computation() -> dict[str, Any]:
    """Convenience function to run TDA computation once."""
    worker = get_tda_worker()
    return await worker.run_once()
