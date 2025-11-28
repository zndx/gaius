# Roadmap

Gaius is an evolving experiment. This roadmap outlines planned development across several horizons.

## Current State (v0.1)

What works today:

- ✅ 19×19 grid rendering
- ✅ `hjkl` cursor navigation
- ✅ Go/Pension mode toggle
- ✅ Overlay cycling (none, risk, h1, swarm)
- ✅ Candidate markers
- ✅ Panel toggle
- ✅ Feature flags (--tda, --swarm, --domain)
- ✅ Basic swarm round execution
- ✅ Domain modal for swarm rewiring
- ✅ TDA death loop visualization
- ✅ Agent position projection

## Near Term (v0.2)

### Command System
- [ ] Slash command input mode
- [ ] Basic command set (/goto, /info, /domain)
- [ ] Command completion
- [ ] Command history

### Navigation
- [ ] Jump to position (G + coordinate)
- [ ] Edge navigation
- [ ] Star point cycling
- [ ] Region selection

### Visualization
- [ ] Smooth transitions
- [ ] Legend/key display
- [ ] Cursor styling by mode
- [ ] Improved status line

### Memory
- [ ] Semantic search (/recall)
- [ ] Session export (JSON)
- [ ] History navigation

## Medium Term (v0.3)

### Command Extensions
- [ ] Command piping
- [ ] Custom command definitions
- [ ] Acme-style text execution in log panel
- [ ] Macro recording

### Visualization
- [ ] Temporal overlay (change trails)
- [ ] Attention overlay (swarm focus)
- [ ] Uncertainty overlay (confidence intervals)
- [ ] Split view / comparison mode

### Agent Architecture
- [ ] Custom agent roles
- [ ] Agent communication visibility
- [ ] Per-agent focus mode
- [ ] APO reward tuning interface

### Persistence
- [ ] SQLite backend for memory
- [ ] Session save/restore
- [ ] Configuration file support

## Longer Term (v0.4+)

### Distributed Operation
- [ ] Remote swarm execution
- [ ] Shared memory across instances
- [ ] Collaborative sessions

### Domain Packages
- [ ] Pension analysis package
- [ ] Cybersecurity package
- [ ] Supply chain package
- [ ] Custom domain SDK

### Advanced TDA
- [ ] H2 (void) visualization
- [ ] Persistence diagram view
- [ ] Entropy trend graphs
- [ ] Anomaly detection

### Integration
- [ ] MCP server for Claude Code integration
- [ ] REST API for external tools
- [ ] Jupyter widget
- [ ] VS Code extension

## Speculative (v1.0+)

### Spatial Extensions
- [ ] 3D grid projection
- [ ] VR/AR interface experiments
- [ ] Multi-board layouts

### Cognitive Research
- [ ] Eye tracking integration
- [ ] SA measurement tools
- [ ] Expertise development tracking

### Community
- [ ] Domain package repository
- [ ] Shared analysis sessions
- [ ] Teaching/demo mode

## Non-Goals

Some things Gaius intentionally avoids:

- **GUI-first design**: Keyboard remains primary
- **Feature bloat**: Composition over accumulation
- **Enterprise lock-in**: Open and inspectable
- **Automatic action**: Humans decide, agents advise
- **Platform dependence**: Terminal works everywhere

## How Priorities Are Set

Development priorities consider:

1. **Core utility**: Does it make the grid more useful?
2. **Composition**: Does it combine with existing features?
3. **Consistency**: Does it follow established patterns?
4. **Community input**: What do users request?
5. **Research value**: Does it advance augmented cognition?

## Contributing to Roadmap

Have ideas? Open an issue to discuss:
- Feature proposals with use cases
- Design alternatives
- Integration opportunities
- Domain-specific needs

The roadmap evolves based on usage and feedback.
