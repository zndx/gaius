"""Test MiniGrid initialization at TUI startup."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import numpy as np

pytest_plugins = ("pytest_asyncio",)


@pytest.mark.asyncio
async def test_minigrid_data_loads_on_startup():
    """Test that minigrid data loads from Postgres and populates the GridManager."""
    from gaius.storage.grid_state import load_full_grid_data_for_minigrids
    from gaius.core.projection import get_grid_manager

    kb_root = "build/dev"

    # Load grid data
    grid_data = await load_full_grid_data_for_minigrids(kb_root)

    # Verify we got data
    assert grid_data is not None, "Grid data should load from Postgres"
    assert grid_data.raw_embeddings is not None, "Should have raw embeddings"
    assert len(grid_data.grid_to_embedding) > 0, "Should have grid-to-embedding mappings"

    # Populate the cache
    grid_manager = get_grid_manager()
    grid_manager.set_cached_data(grid_data)

    # Verify cache is valid
    assert grid_manager._cache_valid, "Cache should be valid after setting data"
    assert grid_manager._cached_data is not None, "Cached data should be set"


def test_minigrid_renders_with_data():
    """Test that MiniGrid widget renders correctly with real data."""
    from gaius.widgets.minigrid import MiniGrid

    # Create sample data (non-empty)
    data = [[0.1 * (i + j) % 1.0 for j in range(9)] for i in range(9)]

    grid = MiniGrid(title="Test View", id="test-minigrid")
    grid.update_data(data, "Updated View")

    # Verify data was set
    assert grid._data == data
    assert grid.border_title == "Updated View"


def test_get_real_minigrid_data_with_grid_data():
    """Test get_real_minigrid_data returns non-empty grids when data is available."""
    from gaius.core.minigrids import get_real_minigrid_data, MiniGridData
    from gaius.core.projection import GridData, GridPoint

    # Create mock GridData with embeddings
    embeddings = np.random.rand(10, 128).astype(np.float32)

    # Create points matching GridPoint signature
    points = [
        GridPoint(
            x=9 + i % 3,  # Around center
            y=9 + i // 3,
            path=f"/test/point{i}.md",
            title=f"Point {i}",
            embedding_id=f"emb_{i}",
            cluster_id=0,
        )
        for i in range(10)
    ]

    # Create grid-to-embedding mappings
    grid_to_embedding = {(p.x, p.y): i for i, p in enumerate(points)}

    grid_data = GridData(
        points=points,
        coverage=0.5,
        n_documents=10,
        grid_to_embedding=grid_to_embedding,
        raw_embeddings=embeddings,
    )

    # Get minigrid data at cursor position (9, 9) - center
    result = get_real_minigrid_data(
        grid_data=grid_data,
        curvatures=None,
        cursor_x=9,
        cursor_y=9,
    )

    # Verify we get non-empty results
    assert "right" in result  # Embed view
    assert "top" in result    # Iso view

    embed_data = result["right"]
    assert isinstance(embed_data, MiniGridData)
    assert embed_data.title == "Embed"

    # Grid should have some non-zero values (we have data near cursor)
    has_nonzero = any(any(v > 0 for v in row) for row in embed_data.grid)
    assert has_nonzero, "Embed grid should have non-zero values when data exists near cursor"


def test_get_real_minigrid_data_empty_when_no_data():
    """Test get_real_minigrid_data returns empty grids when no data."""
    from gaius.core.minigrids import get_real_minigrid_data, MiniGridData

    # Call with None grid_data
    result = get_real_minigrid_data(
        grid_data=None,
        curvatures=None,
        cursor_x=9,
        cursor_y=9,
    )

    # Should still return valid structure
    assert "right" in result
    assert "top" in result

    # But grids should be empty (all zeros)
    embed_data = result["right"]
    assert isinstance(embed_data, MiniGridData)

    all_zero = all(all(v == 0.0 for v in row) for row in embed_data.grid)
    assert all_zero, "Embed grid should be all zeros when no data"


@pytest.mark.asyncio
async def test_minigrid_update_in_async_context():
    """Test that _update_minigrids can be called from async context."""
    from gaius.core.projection import get_grid_manager, GridData, GridPoint
    from gaius.core.minigrids import get_real_minigrid_data
    import numpy as np

    # Simulate what _load_minigrid_data does
    embeddings = np.random.rand(5, 128).astype(np.float32)
    points = [
        GridPoint(x=9, y=9+i, path=f"/p{i}.md", title=f"P{i}", embedding_id=f"e{i}")
        for i in range(5)
    ]
    grid_data = GridData(
        points=points,
        coverage=0.2,
        n_documents=5,
        grid_to_embedding={(p.x, p.y): i for i, p in enumerate(points)},
        raw_embeddings=embeddings,
    )

    # Set cached data
    grid_manager = get_grid_manager()
    grid_manager.set_cached_data(grid_data)

    # Verify we can get minigrid data
    data = get_real_minigrid_data(
        grid_data=grid_data,
        curvatures=None,
        cursor_x=9,
        cursor_y=9,
    )

    assert data["right"].title == "Embed"
    assert data["top"].title.startswith("Iso")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
