# Contributing

Gaius is an experiment in augmented cognition. Contributions that advance this vision are welcome.

## Development Setup

```bash
# Clone and enter
git clone https://github.com/zndx/gaius.git
cd gaius

# Install dependencies with uv
uv sync

# Run in pure UI mode (instant startup for iteration)
uv run python src/gaius/app.py

# Run with all features
uv run python src/gaius/app.py --tda --swarm
```

## Project Structure

```
gaius/
├── src/gaius/
│   ├── app.py          # Primary feature-flagged TUI
│   ├── app2-4.py       # Iteration variants
│   └── main.py         # Full swarm reference implementation
├── docs/
│   ├── src/            # mdbook source
│   └── book.toml       # mdbook config
├── pyproject.toml      # Dependencies
└── CLAUDE.md           # AI assistant guidance
```

## Contribution Areas

### Core TUI

The Board widget and navigation system. Improvements might include:
- Animation and transitions
- Zoom/focus on regions
- Custom coordinate systems
- Accessibility enhancements

### Visualization

Overlay systems and projection methods:
- New overlay types (temporal, attention, uncertainty)
- Alternative projections (UMAP, t-SNE, domain-specific)
- Color schemes and themes
- Legend and annotation systems

### Agent Architecture

Multi-agent swarm improvements:
- New agent roles
- Better APO reward functions
- Agent communication protocols
- Memory optimization

### TDA Pipeline

Topological data analysis enhancements:
- Alternative homology computations
- Faster algorithms for large clouds
- Better grid projection of topological features
- Persistence entropy visualization

### Slash Commands

Command system extensions:
- New commands
- Command completion
- Command history and macros
- Acme-style text execution

### Documentation

Clarifications, examples, tutorials:
- Domain-specific guides
- Video demonstrations
- API documentation
- Concept explanations

## Code Style

- Python 3.12+ features welcome
- Type hints for public interfaces
- Docstrings for non-obvious functions
- Prefer clarity over brevity

## Commit Messages

Use conventional commit style:
```
feat: add temporal overlay mode
fix: correct grid boundary check
docs: expand TDA explanation
refactor: simplify swarm initialization
```

## Pull Request Process

1. Fork the repository
2. Create a feature branch
3. Make changes with clear commits
4. Ensure the app runs (`uv run python src/gaius/app.py`)
5. Update documentation if needed
6. Submit PR with description of changes

## Design Principles

When contributing, consider:

1. **Keyboard-first**: Can this be done without a mouse?
2. **Progressive complexity**: Does this work with no flags?
3. **Consistency**: Does this follow existing patterns?
4. **Transparency**: Can users understand what's happening?
5. **Composition**: Can this combine with other features?

## Questions?

Open an issue for:
- Feature proposals
- Design discussions
- Bug reports
- Documentation requests

## License

Contributions are accepted under the project's license. By contributing, you agree that your contributions will be licensed under the same terms.
