"""Test minigrid loading from Postgres cache via textual pilot."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import numpy as np

from textual.app import App, ComposeResult
from textual.widgets import Static

from gaius.core.state import AppState
from gaius.widgets.minigrid import MiniGrid


class MinigridTestApp(App):
    """Minimal app for testing minigrid loading."""

    CSS = """
    MiniGrid {
        width: 19;
        height: 10;
    }
    """

    def __init__(self):
        super().__init__()
        self.state = AppState()
        # Track if _load_minigrid_data was called
        self.minigrid_load_called = False
        # Mock grid data for testing
        self._mock_grid_data = None

    def compose(self) -> ComposeResult:
        yield MiniGrid("Embed", id="minigrid-top", classes="right")
        yield MiniGrid("Iso", id="minigrid-bottom", classes="bottom-right")

    async def on_mount(self) -> None:
        """Load minigrid data after mount."""
        await self._load_minigrid_data()

    async def _load_minigrid_data(self) -> None:
        """Test version of minigrid data loading."""
        self.minigrid_load_called = True

        if self._mock_grid_data is not None:
            # Update minigrids with mock data
            from gaius.core.minigrids import get_real_minigrid_data

            data = get_real_minigrid_data(
                grid_data=self._mock_grid_data,
                curvatures=None,
                cursor_x=9,
                cursor_y=9,
                iso_mode=self.state.iso_mode,
                iso_features=None,
            )

            if "right" in data and data["right"]:
                self.query_one("#minigrid-top", MiniGrid).update_data(data["right"])
            if "top" in data and data["top"]:
                self.query_one("#minigrid-bottom", MiniGrid).update_data(data["top"])


def make_mock_grid_data():
    """Create mock GridData with embeddings for testing."""
    from gaius.core.projection import GridData, GridPoint

    # Create some test embeddings
    n_docs = 10
    embeddings = np.random.randn(n_docs, 768)
    # Normalize embeddings
    embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)

    # Create points at various grid positions
    points = []
    embedding_to_grid = {}
    grid_to_embedding = {}
    document_positions = set()

    for i in range(n_docs):
        x = 5 + (i % 5)
        y = 7 + (i // 5)
        point = GridPoint(
            x=x, y=y,
            path=f"/test/doc{i}.md",
            title=f"Test Document {i}",
            embedding_id=f"emb_{i}",
            cluster_id=0,
        )
        points.append(point)
        embedding_to_grid[i] = (x, y)
        grid_to_embedding[(x, y)] = i
        document_positions.add((x, y))

    return GridData(
        document_positions=document_positions,
        cluster_centers=set(),
        allocations=[[0] * 19 for _ in range(19)],
        points=points,
        method="umap",
        n_documents=n_docs,
        coverage=n_docs / (19 * 19),
        raw_embeddings=embeddings,
        embedding_to_grid=embedding_to_grid,
        grid_to_embedding=grid_to_embedding,
    )


@pytest.mark.asyncio
async def test_minigrid_data_method_called():
    """Test that _load_minigrid_data is called on mount."""
    app = MinigridTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.minigrid_load_called


@pytest.mark.asyncio
async def test_minigrid_renders_with_mock_data():
    """Test that minigrids render data when GridData is provided."""
    app = MinigridTestApp()
    app._mock_grid_data = make_mock_grid_data()

    async with app.run_test() as pilot:
        await pilot.pause()

        # Get minigrids
        embed_grid = app.query_one("#minigrid-top", MiniGrid)
        iso_grid = app.query_one("#minigrid-bottom", MiniGrid)

        assert embed_grid is not None
        assert iso_grid is not None

        # Check that grids have data (not all zeros)
        embed_has_data = any(v > 0 for row in embed_grid._data for v in row)
        iso_has_data = any(v > 0 for row in iso_grid._data for v in row)

        assert embed_has_data, "Embed grid should have non-zero data"
        assert iso_has_data, "Iso grid should have non-zero data"


@pytest.mark.asyncio
async def test_minigrid_empty_without_data():
    """Test that minigrids are empty when no GridData is provided."""
    app = MinigridTestApp()
    # Don't set _mock_grid_data

    async with app.run_test() as pilot:
        await pilot.pause()

        embed_grid = app.query_one("#minigrid-top", MiniGrid)
        iso_grid = app.query_one("#minigrid-bottom", MiniGrid)

        # Check that grids are all zeros (default)
        embed_has_data = any(v > 0 for row in embed_grid._data for v in row)
        iso_has_data = any(v > 0 for row in iso_grid._data for v in row)

        assert not embed_has_data, "Embed grid should be empty without data"
        assert not iso_has_data, "Iso grid should be empty without data"


@pytest.mark.asyncio
async def test_load_from_postgres_cache():
    """Test loading minigrid data from Postgres cache (mocked)."""
    from gaius.storage.grid_state import CurrentState

    # Create mock CurrentState
    mock_cached_state = CurrentState(
        kb_root="build/dev",
        snapshot_id=1,
        generation=1,
        updated_at=None,
        documents=[
            {"x": 9, "y": 9, "path": "/test/center.md", "title": "Center"},
            {"x": 10, "y": 9, "path": "/test/right.md", "title": "Right"},
        ],
        clusters=[],
        allocations=[[0] * 19 for _ in range(19)],
        n_documents=2,
    )

    # Create mock embeddings
    mock_embeddings = np.random.randn(2, 768)
    mock_embeddings = mock_embeddings / np.linalg.norm(mock_embeddings, axis=1, keepdims=True)

    with patch("gaius.storage.grid_state.load_current_state_fast") as mock_load_fast, \
         patch("gaius.storage.grid_state.load_embeddings_for_snapshot") as mock_load_emb:

        mock_load_fast.return_value = mock_cached_state
        mock_load_emb.return_value = (
            mock_embeddings,
            {0: (9, 9), 1: (10, 9)},
            {(9, 9): 0, (10, 9): 1},
        )

        from gaius.storage.grid_state import load_full_grid_data_for_minigrids

        grid_data = await load_full_grid_data_for_minigrids("build/dev")

        assert grid_data is not None
        assert grid_data.n_documents == 2
        assert grid_data.raw_embeddings is not None
        assert len(grid_data.grid_to_embedding) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
