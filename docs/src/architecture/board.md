# The Board Widget

The Board widget is the visual core of Gaius—a Textual `Static` widget that renders the 19×19 grid with all active overlays.

## Rendering Pipeline

```python
class Board(Static):
    def render_board(self) -> str:
        # 1. Initialize empty grid
        grid = [["·"] * 19 for _ in range(19)]

        # 2. Place cursor
        grid[cy][cx] = "✛"

        # 3. Mode-specific content (Go stones or allocations)
        # 4. Candidate markers
        # 5. TDA overlay (if enabled)
        # 6. Swarm overlay (if enabled)

        # 7. Format with coordinates
        return formatted_output
```

Each layer overwrites the previous, with later layers having visual priority.

## Layer Composition

### Base Layer: Empty Grid
```
19 · · · · · · · · · · · · · · · · · · · 19
18 · · · · · · · · · · · · · · · · · · · 18
...
```

### Cursor Layer
The cursor (`✛`) marks the current navigation position. It appears above empty points but below stones/markers.

### Content Layer (Mode-Dependent)

**Go Mode** (`v` to toggle):
```python
for x, y in app.black:
    grid[y][x] = "●"
for x, y in app.white:
    grid[y][x] = "○"
```

**Pension Mode**:
```python
for y in range(19):
    for x in range(19):
        v = app.alloc[y][x]
        grid[y][x] = "▓" if v > 75 else "▒" if v > 50 else "░" if v > 20 else "·"
```

### Candidate Layer
Lettered markers (a-i) indicate suggested positions:
```python
for i, (x, y) in enumerate(app.candidates[:9]):
    grid[y][x] = f"[bold yellow]{chr(97+i)}[/]"
```

### TDA Overlay
When `overlay == "h1"`, death loops are projected:
```python
if TDA and app.overlay == "h1":
    for y, x in death_loop_positions:
        grid[y][x] = "[on bright_red]⚠[/]"
```

### Swarm Overlay
Agent positions from embedding space:
```python
if SWARM and app.cloud.size:
    colors = ["red", "green", "blue", "yellow", "magenta", "cyan", "white"]
    for i, (xx, yy) in enumerate(zip(x_proj, y_proj)):
        grid[yy][xx] = f"[{colors[i]}]●[/{colors[i]}]"
```

## Coordinate System

```
   A B C D E F G H J K L M N O P Q R S T
19 · · · · · · · · · · · · · · · · · · ·
18 · · · · · · · · · · · · · · · · · · ·
17 · · · + · · · · · · · · · + · · · · ·
16 · · · · · · · · · · · · · · · · · · ·
...
 4 · · · + · · · · · · · · · + · · · · ·
 3 · · · · · · · · · · · · · · · · · · ·
 2 · · · · · · · · · · · · · · · · · · ·
 1 · · · · · · · · · · · · · · · · · · ·
   A B C D E F G H J K L M N O P Q R S T
```

- **X-axis**: A-T (skipping I), left to right
- **Y-axis**: 1-19, bottom to top (Go convention)
- **Star points** (+): Traditional markers at (4,4), (4,16), (16,4), (16,16), etc.

## Textual Markup

The board uses Textual's Rich-compatible markup for styling:

| Markup | Effect |
|--------|--------|
| `[bold yellow]text[/]` | Bold yellow text |
| `[on bright_red]text[/]` | Bright red background |
| `[red]●[/red]` | Red foreground |

This enables rich visual differentiation without escape sequences.

## Refresh Cycle

```python
def refresh_board(self):
    board_content = self.query_one(Board).render_board()
    self.query_one("#main-board").update(Static(board_content, id="grid"))
    self.query_one("#status").update(self.status_line())
```

Called after any state change:
- Cursor movement
- Mode toggle
- Overlay cycle
- Swarm round completion
- Domain adaptation

## Performance Considerations

The board re-renders completely on each refresh. For 19×19 with overlays, this is:
- ~361 cells × ~5 bytes = ~2KB per render
- At 60fps cap: ~120KB/s (negligible)

No incremental rendering is needed at this scale. Full re-render ensures correctness.

## Future Enhancements

- **Animation**: Smooth cursor transitions, stone placement effects
- **Zoom**: Focus on subregions for detail work
- **Annotations**: Persistent text labels on grid regions
- **History**: Replay previous board states
