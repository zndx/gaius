# Gaius

> *"True glory consists in doing what deserves to be written, in writing what deserves to be read."*
> — Gaius Plinius Secundus (Pliny the Elder)

**Gaius** is a CLI-first terminal interface for navigating complex, graph-oriented data domains. It renders high-dimensional embeddings and topological structures onto a constrained grid — transforming abstract complexity into spatial intuition.

Named after the Roman polymath Pliny the Elder, whose *Naturalis Historia* attempted to catalog all knowledge of the natural world, Gaius embodies a similar ambition: to provide a unified interface through which the modern polymath can perceive, navigate, and reason about interconnected information landscapes.

## What Makes Gaius Different

Traditional terminals present information as streams of text. Dashboards present it as isolated charts. Neither captures the *shape* of data — the loops, clusters, and voids that reveal hidden structure.

Gaius takes a different approach:

1. **The Grid as Canvas**: A 19x19 board (inspired by Go) serves as the primary visualization surface. Every point is addressable. Every region has meaning.

2. **Topological Awareness**: Persistent homology reveals the *death loops* — cycles in your data that persist across scales. These aren't decorations; they're early warnings of systemic risk.

3. **Autonomous Agents**: Agents explore domains, evolve through RLVR training, and consolidate knowledge via theta-wave-inspired memory compression. Their state projects onto the grid.

4. **Modal Navigation**: Like Vim, like Plan 9, Gaius rewards mastery. `hjkl` navigation, slash commands, overlay modes — all keyboard-driven for flow state operation.

5. **Self-Healing Infrastructure**: FMEA-based health monitoring with automated remediation. When something breaks, Gaius diagnoses and fixes itself before you notice.

## The Platform

Gaius has grown from a TUI prototype into a full platform:

- **gRPC Engine** with 37 registered services on port 50051
- **Three interfaces**: TUI (interactive), CLI (scripting), MCP (AI-assisted)
- **6 NVIDIA GPUs** running vLLM inference with makespan scheduling
- **Metaflow pipelines** for article curation, evaluation, and rendering
- **LuxCore path tracer** for procedural card visualizations
- **Health Observer** daemon with FMEA scoring and ACP escalation
- **Bases feature store** with temporal entity queries
- **RASE metamodel** for verifiable agent training

## Getting Started

```bash
# Launch the TUI
uv run gaius

# Use the CLI for scripting
uv run gaius-cli --cmd "/health" --format json

# Check system status
uv run gaius-cli --cmd "/gpu status" --format json
```

Navigate with `hjkl`. Cycle overlays with `o`. Toggle modes with `v`. Press `?` for help.

Welcome to a new way of seeing.
