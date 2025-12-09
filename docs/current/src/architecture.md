# System Overview

Gaius is architected as a layered system where each layer can operate independently, enabling progressive complexity based on user needs and available resources.

## Architectural Layers

```
┌─────────────────────────────────────────────────────────────┐
│                      TUI Layer (Textual)                     │
│   Board Widget │ Log Panel │ Status Bar │ Modal Screens     │
├─────────────────────────────────────────────────────────────┤
│                    Projection Layer                          │
│   PCA/UMAP │ Grid Mapping │ Overlay Composition             │
├─────────────────────────────────────────────────────────────┤
│                    Analysis Layer                            │
│   TDA Pipeline │ Scene Graph │ Similarity Search            │
├─────────────────────────────────────────────────────────────┤
│                    Agent Layer                               │
│   DeepAgents │ APO Middleware │ Role Templates              │
├─────────────────────────────────────────────────────────────┤
│                    Memory Layer                              │
│   Vector Store │ Embedding Cache │ Temporal Index           │
├─────────────────────────────────────────────────────────────┤
│                    Foundation Layer                          │
│   LangChain │ OpenAI APIs │ NumPy/SciKit │ giotto-tda       │
└─────────────────────────────────────────────────────────────┘
```

## Feature Flags

Gaius uses CLI flags to enable conditional imports, avoiding the cold-start penalty of heavy dependencies:

| Flag | Dependencies Loaded | Startup Time |
|------|---------------------|--------------|
| (none) | textual only | ~0.1s |
| `--tda` | + numpy, sklearn, giotto-tda | ~2s |
| `--swarm` | + langchain, openai, deepagents | ~3s |
| `--tda --swarm` | all | ~4s |

This design allows:
- **Instant iteration** on UI with no flags
- **Full analysis** when needed with all flags
- **Selective loading** based on task requirements

## Data Flow

```
User Input          Agent Output         External Data
    │                    │                    │
    ▼                    ▼                    ▼
┌──────────────────────────────────────────────────┐
│               Embedding Layer                     │
│   text → vector (1536-dim)                        │
└──────────────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────┐
│               Vector Memory                       │
│   store, index, retrieve                          │
└──────────────────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
    ┌──────────┐  ┌────────────┐  ┌──────────┐
    │   TDA    │  │   Scene    │  │  Swarm   │
    │ Pipeline │  │   Graph    │  │  State   │
    └──────────┘  └────────────┘  └──────────┘
          │              │              │
          └──────────────┼──────────────┘
                         ▼
┌──────────────────────────────────────────────────┐
│            Projection & Composition               │
│   2D projection → grid mapping → overlay merge   │
└──────────────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────┐
│               Board Widget                        │
│   render grid, handle input, update status       │
└──────────────────────────────────────────────────┘
```

## Component Interaction

### Synchronous Path (Pure UI)
Keyboard input → action handler → board refresh → render

### Asynchronous Path (Swarm)
Swarm trigger → agent invocations (parallel) → embedding → memory store → TDA compute → board refresh

The `@work` decorator in Textual enables background operations without blocking the UI.

## State Management

Application state is centralized in the `GoBoardApp` class:

```python
class GoBoardApp(App):
    # View state
    mode: str           # "go" or "pension"
    overlay: str        # "none", "risk", "h1", "swarm"
    cursor: tuple[int, int]

    # Data state
    black: set          # Black stone positions
    white: set          # White stone positions
    alloc: list[list]   # Pension allocation grid
    candidates: list    # Marked candidate positions

    # Swarm state
    domain: str         # Current analysis domain
    cloud: np.ndarray   # Embedding point cloud
    tda_result: dict    # Latest TDA computation
```

State changes trigger `refresh_board()` which recomputes the visual representation.

## Extension Points

### Custom Projections
Implement a projection function and register it:
```python
def domain_projection(cloud: np.ndarray) -> np.ndarray:
    # Custom 2D projection logic
    return projected_2d
```

### Custom Overlays
Add to the overlay cycle and implement rendering:
```python
if app.overlay == "my_overlay":
    for y, x in my_feature_positions:
        grid[y][x] = "[my_style]◆[/]"
```

### Custom Agents
Extend the swarm with specialized roles:
```python
{"name": "Regulator", "role": f"Ensure compliance in {domain}"}
```

## File Structure

```
src/gaius/
├── app.py          # Primary feature-flagged TUI
├── app2.py         # Variant with explicit events import
├── app3.py         # Variant with simplified CSS
├── app4.py         # Variant with minimal swarm stubs
└── main.py         # Full swarm implementation (no flags)
```

The multiple `app*.py` files represent evolutionary iterations. `app.py` is the current canonical implementation; `main.py` contains the complete swarm logic for reference.
