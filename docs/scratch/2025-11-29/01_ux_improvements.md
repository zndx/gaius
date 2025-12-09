# UX Improvements Session - 2025-11-29

## Summary

Implemented several UX refinements to make Gaius feel crisp and professional.

## Completed Features

### 1. Tab Focus Fix
- Removed CommandInput from tab focus cycle (`widgets/command.py:71`)
- Command input still activates via `/` key
- Cleaner tab navigation between FileTree and other focusable widgets

### 2. Graph Updates on FileTree Navigation
- Added `FileTreeHighlight` message in `widgets/filetree.py`
- Tree.NodeHighlighted handler posts message on cursor movement
- App debounces graph updates at 150ms to avoid lag during rapid navigation
- Graph selection syncs when navigating FileTree

### 3. Vim Editor Rename/Move Commands
- `:mv path/to/file.md` - Move file to arbitrary location in KB
- `:rename` - Move to `scratch/<today>/<timestamp>.md` (safe location)
- `:rename foo` - Move to `scratch/<today>/foo.md`
- `FileRenamed` message triggers FileTree and GraphView refresh
- Path validation ensures files stay within KB root

### 4. Graph Navigation
- GraphView is now focusable (`can_focus=True`)
- Arrow keys navigate between nodes (hjkl reserved for MainGrid)
- Enter opens the selected node's file
- Selected node shown with `◆` glyph and reverse styling
- Creates non-existent files when navigating to them (wiki-style)
- File creation restricted to `archive/`, `current/`, `scratch/` directories

### 5. Bi-directional Sync
- FileTree cursor → Graph: `select_node_by_path()` highlights matching node
- Graph cursor → FileTree: `highlight_path()` scrolls to and shows node
- Both directions debounced at 150ms

## Files Modified

| File | Changes |
|------|---------|
| `src/gaius/widgets/command.py` | `can_focus = False` |
| `src/gaius/widgets/filetree.py` | `FileTreeHighlight` message, `highlight_path()` method |
| `src/gaius/widgets/note_editor.py` | `:mv` and `:rename` commands, `FileRenamed` message |
| `src/gaius/widgets/graph_view.py` | Focusable, arrow key nav, `selected_node`, messages |
| `src/gaius/widgets/__init__.py` | Export `FileTreeHighlight` |
| `src/gaius/app.py` | Debounced handlers, file creation logic, path validation |

## Bug Fixes During Implementation

1. **`self._nodes` conflict** - Renamed to `self._graph_nodes` to avoid Textual internal conflict
2. **`walk_children()` missing** - Replaced with recursive `find_node()` using `children` attribute
3. **`cursor_node` read-only** - Removed setter, using `scroll_to_node()` instead
4. **`select()` missing** - Removed call, scrolling is sufficient for visual sync
5. **Relative path handling** - Paths like `current/topics/foo` now correctly resolve to `build/dev/current/topics/foo`

## Help Text Updates

Updated help (accessible via `?`) to document:
- `:mv` and `:rename` commands
- Graph view arrow key navigation
- Enter to open files from graph
- FileTree/Graph sync behavior
