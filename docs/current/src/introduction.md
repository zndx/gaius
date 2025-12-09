# Gaius

> *"True glory consists in doing what deserves to be written, in writing what deserves to be read."*
> — Gaius Plinius Secundus (Pliny the Elder)

**Gaius** is a CLI-first terminal interface for navigating complex, graph-oriented data domains. It renders high-dimensional embeddings and topological structures onto a constrained grid—transforming abstract complexity into spatial intuition.

Named after the Roman polymath Pliny the Elder, whose *Naturalis Historia* attempted to catalog all knowledge of the natural world, Gaius embodies a similar ambition: to provide a unified interface through which the modern polymath can perceive, navigate, and reason about interconnected information landscapes.

## What Makes Gaius Different

Traditional terminals present information as streams of text. Dashboards present it as isolated charts. Neither captures the *shape* of data—the loops, clusters, and voids that reveal hidden structure.

Gaius takes a different approach:

1. **The Grid as Canvas**: A 19×19 board (inspired by Go) serves as the primary visualization surface. Every point is addressable. Every region has meaning.

2. **Topological Awareness**: Persistent homology reveals the *death loops*—cycles in your data that persist across scales. These aren't decorations; they're early warnings of systemic risk.

3. **Agentic Augmentation**: Multi-agent swarms explore your domain in parallel, their positions projected onto the grid as they converge on insights.

4. **Modal Navigation**: Like Vim, like Plan 9, Gaius rewards mastery. `hjkl` navigation, slash commands, overlay modes—all keyboard-driven for flow state operation.

## A New Paradigm

Gaius represents a departure from the spreadsheet-and-chart paradigm that has dominated data interfaces for decades. It draws instead from:

- The **information density** of Bloomberg terminals
- The **compositional elegance** of Plan 9 and Acme
- The **conversational interface** patterns pioneered by Claude Code
- The **topological intuition** of persistent homology

The result is an interface designed not just to display data, but to augment human cognition—making the invisible structures of complex domains directly perceivable.

## Getting Started

```bash
# Pure TUI mode (instant startup)
uv run gaius

# Full feature mode with TDA and agent swarms
uv run gaius --tda --swarm

# Custom domain
uv run gaius --swarm --domain "supply chain logistics"
```

Navigate with `hjkl`. Cycle overlays with `o`. Toggle modes with `v`. Press `?` for help.

Welcome to a new way of seeing.

