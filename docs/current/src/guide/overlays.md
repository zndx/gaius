# Overlays & Visualization

Overlays are Gaius's mechanism for layering multiple data dimensions onto a single grid. Understanding overlay composition is key to effective visual analysis.

## Overlay Philosophy

A grid has 361 cells. Naively, that's one data point per cell. But complex domains have many dimensions. Overlays solve this by:

1. **Layering**: Multiple data types occupy the same space
2. **Cycling**: Focus shifts between layers via `o` key
3. **Compositing**: Some layers blend (e.g., density + markers)

## Available Overlays

### None

The cleanest view. Shows only:
- Base grid (· or mode-specific symbols)
- Cursor position (✛)
- Candidate markers (a-i) if toggled

Use this for uncluttered observation of the base state.

### Risk (Planned)

Visualizes risk surface across the grid:

```
High risk:    [on red]█[/]
Medium risk:  [on yellow]▓[/]
Low risk:     [on green]░[/]
Neutral:      ·
```

Risk is computed from:
- Agent assessments
- Historical volatility (if data available)
- Topological features (death loops correlate with systemic risk)

### H1 (Death Loops)

Displays persistent homology H1 features—topological loops that survive across scales.

```
   A B C D E F G H J K L M N O P Q R S T
19 · · · · · · · · · · · · · · · · · · ·
18 · · · ⚠ ⚠ · · · · · · · · · · · · · ·
17 · · ⚠ · · ⚠ · · · · · · · · · · · · ·
16 · · · ⚠ ⚠ · · · · · · · · · · · · · ·
...
```

The `⚠` markers indicate where the underlying embedding space has persistent cycles. In domain terms, these often represent:

- **Feedback loops**: Self-reinforcing dynamics
- **Circular dependencies**: A→B→C→A
- **Liquidity traps**: Capital that can't exit
- **Regulatory arbitrage**: Rules that reference each other

### Swarm

Agent positions projected from embedding space:

```
   A B C D E F G H J K L M N O P Q R S T
19 · · · · · · · · · · · · · · · · · · ·
18 · · · · · [green]●[/] · · · · · · · · · · · · ·
17 · · · · · · · · · · [yellow]●[/] · · · · · · · ·
16 · · · [red]●[/] · · · · · · · · · · · · · · ·
...
```

Color encoding:
| Color | Agent |
|-------|-------|
| Red | Leader |
| Green | Risk |
| Blue | Optimizer |
| Yellow | Planner |
| Magenta | Critic |
| Cyan | Executor |
| White | Adversary |

Watch for:
- **Clustering**: Agents in agreement
- **Scattering**: Genuine uncertainty
- **Opposition**: Agents on opposite corners (tension)
- **Isolation**: Single agent in a region (unique insight)

## Reading Composite Views

When multiple features occupy a cell, priority determines display:

1. Overlay markers (⚠, colored ●) — highest
2. Candidate letters (a-i)
3. Cursor (✛)
4. Stones/density (●, ○, ▓▒░)
5. Empty (·) — lowest

A cell showing `⚠` might also contain an agent position, but the warning takes visual priority.

## Density Interpretation

In Pension Mode, density shading encodes value intensity:

```
▓▓▓▓  High concentration — major allocation
▒▒▒▒  Moderate — significant but not dominant
░░░░  Low — minor presence
····  Minimal — negligible or empty
```

Combined with cursor navigation, you can:
1. See the macro pattern (stand back, observe density)
2. Investigate regions (navigate to high-density)
3. Query specifics (`/info` at position)

## Overlay Transitions

Pressing `o` cycles through overlays. The transition is immediate—no animation (yet). Future enhancements may include:

- Fade transitions between overlays
- Overlay blending (semi-transparent layers)
- Custom overlay ordering

## Creating Mental Models

Effective overlay use develops intuition:

**Pattern**: Death loops cluster in one corner, agents cluster in another
**Interpretation**: Risk is localized but agents haven't fully explored it yet. Run another swarm round.

**Pattern**: Agents scattered uniformly, no visible loops
**Interpretation**: Either genuine complexity with no dominant structure, or insufficient swarm rounds. Check entropy.

**Pattern**: Dense region in center, loops at edges
**Interpretation**: Core activity is well-understood; edge cases pose topological risk.

## Overlay as Situational Awareness

Each overlay provides a different "sense":

- **None**: Clean visual baseline
- **Risk**: Threat perception
- **H1**: Structural awareness
- **Swarm**: Team state awareness

Cycling overlays is like shifting attention between modalities—a form of augmented situational awareness.

## Future Overlays

Planned overlay types:

- **Temporal**: Show change over time (heat trails)
- **Attention**: Highlight where swarm has focused
- **Conflict**: Show positions with agent disagreement
- **Uncertainty**: Visualize confidence intervals
- **Custom**: User-defined overlay functions
