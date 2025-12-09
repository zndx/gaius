# Navigation & Modes

Gaius draws inspiration from modal editors like Vim and compositional systems like Plan 9's Acme. Navigation is keyboard-driven, modes provide context, and every operation is reversible.

## Modal Philosophy

Unlike modeless interfaces where every key always does the same thing, Gaius uses modes to provide context-sensitive behavior. This isn't complexity—it's power through focus.

**Normal Mode** (default): Navigate, observe, toggle views
**Command Mode** (planned): Enter slash commands
**Visual Mode** (planned): Select regions for bulk operations

## Cursor Navigation

The cursor is your focus point on the grid. It determines:
- What position commands act upon
- The center of local context
- The reference point for relative addressing

### Basic Movement

```
       k
       ↑
   h ← ✛ → l
       ↓
       j
```

Vim-style navigation: `h`/`j`/`k`/`l` for left/down/up/right.

### Why HJKL?

These keys are on the home row. Your fingers never leave typing position. This isn't a quirk—it's 50 years of refinement from vi to vim to modern modal interfaces.

### Planned Navigation Extensions

**Jump to position**: `G` + coordinate (e.g., `GK10` jumps to K10)
**Edge navigation**: `0` for column A, `$` for column T
**Star points**: `*` cycles through star points (D4, D10, D16, K4, K10, etc.)
**Search**: `/` enters search mode for semantic grid search

## View Modes

Press `v` to toggle between visualization modes:

### Pension Mode (Default)
The grid displays allocation intensity:

| Symbol | Meaning | Value Range |
|--------|---------|-------------|
| `▓` | High density | >75% |
| `▒` | Medium density | 50-75% |
| `░` | Low density | 20-50% |
| `·` | Minimal | <20% |

This view reveals where capital concentrates.

### Go Mode
Traditional Go stones on intersections:

| Symbol | Meaning |
|--------|---------|
| `●` | Black stone |
| `○` | White stone |
| `·` | Empty intersection |

Useful for understanding the underlying Go metaphor and for actual game analysis.

## Overlay Modes

Press `o` to cycle overlays. Overlays add visual information without changing the base view:

### None
Clean grid. No additional markers.

### Risk (Planned)
Heat map of risk surface. Red regions indicate elevated risk.

### H1 (Requires --tda)
Death loop markers (`⚠`) appear where persistent homology detects H1 features—topological loops in the point cloud.

### Swarm (Requires --swarm)
Agent positions rendered as colored stones:
- Red: Leader
- Green: Risk
- Blue: Optimizer
- Yellow: Planner
- Magenta: Critic
- Cyan: Executor
- White: Adversary

## Panel Management

Press `t` to toggle the side panel. The panel displays:

- **Log**: Recent operations and messages
- **Swarm output**: Agent responses during rounds
- **TDA metrics**: Entropy and feature counts

In complex sessions, toggle panels off to maximize grid visibility, then back on to review details.

## Pages

Numeric keys switch context pages:

| Key | Page | Content |
|-----|------|---------|
| `1` | PORT | Portfolio/allocation view |
| `5` | OPT | Optimizer recommendations |
| `0` | TDA | Topological analysis display |

Pages update the log panel with relevant information and may adjust the grid overlay.

## Status Line

The bottom status bar shows:
- Current mode
- Active features (TDA on, Swarm on)
- Current domain (if swarm enabled)
- Key hint for available actions

Example:
```
Ready | TDA on | Swarm (pension asset allocation) | hjkl=move o=overlay
```

## Flow Patterns

### Exploration Flow
1. Navigate with `hjkl` to survey the grid
2. Cycle overlays (`o`) to see different data layers
3. Toggle candidates (`c`) to see suggested positions
4. Use pages (`1`, `5`, `0`) to dive into specific analyses

### Analysis Flow
1. Set domain (`d`) if needed
2. Run swarm round (`s`)
3. Watch agent outputs in panel
4. Observe agent positions on grid
5. Cycle to H1 overlay to see topology
6. Repeat rounds to deepen analysis

### Focused Flow
1. Hide panels (`t`)
2. Navigate to region of interest
3. Toggle to relevant overlay
4. Study the concentrated view
5. Restore panels for logging
