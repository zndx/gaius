# Mini-Grid Mapping Fix

**Date:** 2025-12-02
**Context:** Mini-grids weren't displaying - found mapping was backwards

## Root Cause

The `embedding_to_grid` dictionary in `GridData` maps `int → tuple[int, int]` (embedding index → grid position), but the mini-grid code was trying to use it backwards: looking up grid positions as keys.

### The Bug

**GridData definition** (`projection.py:73`):
```python
# Mapping from embedding index to grid position
embedding_to_grid: dict[int, tuple[int, int]] = field(default_factory=dict)
```

**Populated at** (`projection.py:351`):
```python
grid_data.embedding_to_grid[i] = (int(x), int(y))  # i is embedding index
```

**But mini-grid code** (`minigrids.py:59, 155, 216`):
```python
# WRONG: Using grid position as key!
cursor_point_idx = grid_data.embedding_to_grid.get((cursor_x, cursor_y))
```

This would always return `None` because `(cursor_x, cursor_y)` is not a valid key in the dict.

## Solution

Added a reverse mapping to `GridData`:

### 1. Added field to GridData (`projection.py:76`)
```python
# Reverse mapping: grid position to embedding index (for mini-grids)
grid_to_embedding: dict[tuple[int, int], int] = field(default_factory=dict)
```

### 2. Populate reverse mapping (`projection.py:352`)
```python
grid_data.embedding_to_grid[i] = (int(x), int(y))
grid_data.grid_to_embedding[(int(x), int(y))] = i  # Reverse mapping
```

### 3. Updated mini-grid lookups (`minigrids.py`)
Changed all grid position lookups to use `grid_to_embedding`:

- Line 59: `cursor_point_idx = grid_data.grid_to_embedding.get((cursor_x, cursor_y))`
- Line 72: `for (gx, gy), idx in grid_data.grid_to_embedding.items():`
- Line 155: `point_idx = grid_data.grid_to_embedding.get((gx, gy))`
- Line 216: `point_idx = grid_data.grid_to_embedding.get((cursor_x, cursor_y))`

## Status

✅ Reverse mapping added to GridData
✅ Mapping populated during grid projection
✅ All mini-grid lookups updated
✅ TUI starts without errors
✅ Mini-grids should now display data correctly

## Testing

Mini-grids should now show:
- **Embed view** (top): Semantic similarity around cursor via cosine distance
- **Iso view** (bottom): Topological elevation from TDA risk scores

Test by:
1. Ensure KB has embeddings indexed
2. Start TUI: `uv run gaius`
3. Move cursor with `hjkl` to see mini-grids update
4. Try `/explain` command for LLM interpretation
