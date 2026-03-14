# Navigation & Modes

Gaius draws inspiration from modal editors like Vim and compositional systems like Plan 9's Acme. Navigation is keyboard-driven, modes provide context, and every operation is reversible.

## Modal Philosophy

Gaius uses modes to provide context-sensitive behavior. This is not complexity -- it is power through focus.

- **Normal Mode** (default): navigate, observe, toggle views
- **Command Mode**: enter slash commands via the command bar (`/`)

## Cursor Navigation

The cursor is your focus point on the grid. It determines what position commands act upon, the center of local context, and the reference point for the MiniGrid projections.

### Basic Movement

```
       k
       |
   h --+-- l
       |
       j
```

Vim-style navigation: `h`/`j`/`k`/`l` for left/down/up/right. These keys sit on the home row so your fingers never leave typing position.

### Tenuki

Press `t` to jump to the point of highest strategic interest -- a concept borrowed from Go, where tenuki means "playing elsewhere." The engine evaluates all grid positions and moves your cursor to the most strategically relevant one.

## View Modes

Press `v` to cycle through visualization modes:

### Go Mode
Traditional Go stones on intersections. Black and white stones mark occupied positions. Empty intersections show as dots.

### Theta Mode
Information density visualization named after theta waves, which facilitate memory consolidation. This mode renders allocation intensity and data density across the grid.

### Swarm Mode
Agent-centric view showing multi-agent positions and activity across the grid.

## Overlay Modes

Press `o` to cycle overlays. Overlays add visual information on top of the current view mode without changing the base rendering:

| Overlay | Key concept | What it shows |
|---------|-------------|---------------|
| **None** | Clean slate | Base grid only |
| **Topology** | Persistent homology | H0/H1/H2 features (components, loops, voids) |
| **Geometry** | Curvature | Semantic boundaries vs. interiors |
| **Dynamics** | Gradient field | Direction of semantic change, divergence |
| **Agents** | Team state | Agent positions on the grid |

See [Overlays](./overlays.md) for detailed interpretation guidance.

## Iso View Modes

Press `i` to cycle through Iso view modes, which change the interpretation of the MiniGrid projections below the main grid. These provide different mathematical lenses on the same data.

## Panel Management

| Key | Action |
|-----|--------|
| `[` | Toggle left panel (FileTree) |
| `]` | Toggle right panel (ContentPanel) |
| `\` | Toggle both panels simultaneously |

Hide panels to maximize grid visibility. Restore them to review details and navigate the knowledge base.

## Graph View

Press `g` to cycle the center panel between modes. This toggles between the standard grid view and a graph/wiki-link visualization, providing different perspectives on the same underlying data.

## Flow Patterns

### Exploration Flow
1. Navigate with `hjkl` to survey the grid
2. Cycle overlays (`o`) to see different data layers
3. Toggle candidates (`c`) to see suggested positions
4. Press `t` for tenuki to jump to high-interest points

### Analysis Flow
1. Press `/` to enter command mode
2. Run `/health` to check system state
3. Use overlays to compare topology, geometry, and dynamics
4. Review output in the ContentPanel

### Focused Flow
1. Hide panels (`\`) for maximum grid space
2. Navigate to a region of interest
3. Switch overlays to study different dimensions
4. Restore panels when you need detailed context
