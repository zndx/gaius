# Overlays & Visualization

Overlays are Gaius's mechanism for layering multiple data dimensions onto a single grid. Understanding overlay composition is key to effective visual analysis.

## Overlay Philosophy

A grid has 361 cells. Naively, that is one data point per cell. But complex domains have many dimensions. Overlays solve this by:

1. **Layering**: multiple data types occupy the same space
2. **Cycling**: focus shifts between layers via the `o` key
3. **Compositing**: some layers blend (e.g., density + markers)

## Available Overlays

Press `o` to cycle through overlay modes. The current set is based on differential geometry concepts:

### None

The cleanest view. Shows only:
- Base grid (view-mode-specific symbols)
- Cursor position
- Candidate markers (a-i) if toggled with `c`

Use this for uncluttered observation of the base state.

### Topology

Displays persistent homology features at three scales:
- **H0**: connected components -- clusters of related data points
- **H1**: loops -- cycles in the embedding space (feedback loops, circular dependencies)
- **H2**: voids -- higher-dimensional cavities (structural gaps)

Topological features that persist across scales are significant. Transient features are noise. The overlay highlights those that survive, revealing the true shape of the data.

### Geometry

Curvature heatmap showing semantic boundaries versus interiors. High curvature regions mark transitions between conceptual domains. Low curvature indicates the interior of a coherent cluster. This overlay helps identify where one topic ends and another begins.

### Dynamics

Gradient vector field showing the direction and magnitude of semantic change. Arrows or indicators point toward regions of increasing density or relevance. Divergence patterns reveal sources (generating new content) and sinks (absorbing attention). This overlay captures how the data landscape is evolving.

### Agents

Agent positions projected from embedding space onto the grid. Each active agent occupies a position determined by its current focus within the data. Watch for:

- **Clustering**: agents in agreement, converging on the same region
- **Scattering**: genuine uncertainty or broad exploration
- **Opposition**: agents on opposite sides of the grid (tension, disagreement)
- **Isolation**: a single agent in a region (unique insight worth investigating)

## Reading Composite Views

When multiple features occupy a cell, priority determines display:

1. Overlay markers -- highest priority
2. Candidate letters (a-i)
3. Cursor
4. Stones/density (view-mode symbols)
5. Empty (dot) -- lowest priority

## Overlay as Situational Awareness

Each overlay provides a different "sense":

- **None**: clean visual baseline
- **Topology**: structural awareness (what shapes exist)
- **Geometry**: boundary awareness (where things change)
- **Dynamics**: momentum awareness (where things are going)
- **Agents**: team state awareness (where agents are looking)

Cycling overlays is like shifting attention between modalities -- a form of augmented situational awareness. The OODA loop pattern (Observe, Orient, Decide, Act) maps naturally: observe with None, orient with Topology or Geometry, decide based on Dynamics, act on Agent positions.

## Combining with View Modes

Overlays compose with view modes (`v`). A Topology overlay on Go mode shows homology features atop stone positions. The same overlay on Theta mode shows features atop density shading. Experiment with combinations to find the perspective that reveals what you need.
