# Getting Started

## Installation

Gaius requires Python 3.12+ and uses `uv` for dependency management.

```bash
# Clone the repository
git clone https://github.com/zndx/gaius.git
cd gaius

# Install dependencies
uv sync
```

## First Launch

Start with the pure UI mode for instant feedback:

```bash
uv run python src/gaius/app.py
```

You should see:
```
Pure GoBoard TUI mode – no external deps, instant start
```

And a 19×19 grid with a cursor at the center.

## Basic Navigation

```
┌─────────────────────────────────────────┐
│  h ← left    l → right                   │
│  j ↓ down    k ↑ up                      │
│                                          │
│  q   quit                                │
│  ?   help (when implemented)             │
└─────────────────────────────────────────┘
```

Try moving the cursor. The `✛` marker follows your navigation.

## View Modes

Press `v` to toggle between:

- **Pension Mode**: Density heatmap (▓▒░·) showing allocation intensities
- **Go Mode**: Black and white stones on intersections

## Overlays

Press `o` to cycle through overlay modes:

1. **none**: Clean grid, no overlays
2. **risk**: (Future) Risk surface visualization
3. **h1**: TDA death loops (requires `--tda`)
4. **swarm**: Agent positions (requires `--swarm`)

## Candidates

Press `c` to toggle candidate markers. These appear as lowercase letters (a-i) at suggested positions.

## Panels

Press `t` to toggle the side panel visibility. The panel shows:
- Log of recent operations
- Swarm agent outputs
- Status messages

## Enabling Features

### TDA Mode

```bash
uv run python src/gaius/app.py --tda
```

Enables topological data analysis. Requires `giotto-tda`:
```bash
uv add giotto-tda
```

### Swarm Mode

```bash
uv run python src/gaius/app.py --swarm
```

Enables multi-agent analysis. Requires:
```bash
uv add langchain langchain-openai deepagents agentlightning[apo]
```

And an OpenAI API key in your environment:
```bash
export OPENAI_API_KEY="sk-..."
```

### Full Mode

```bash
uv run python src/gaius/app.py --tda --swarm --domain "your domain here"
```

## Running a Swarm Round

With `--swarm` enabled:

1. Press `s` to trigger a swarm round
2. Watch the log panel fill with agent responses
3. Observe agent positions appear on the grid
4. Press `o` to cycle to swarm overlay for clear visualization

## Changing Domain

With `--swarm` enabled:

1. Press `d` to open the domain modal
2. Type a new domain (e.g., "supply chain logistics")
3. Press Enter
4. The swarm rewires and runs an initial round

## Keyboard Reference

| Key | Action |
|-----|--------|
| `h` | Move cursor left |
| `j` | Move cursor down |
| `k` | Move cursor up |
| `l` | Move cursor right |
| `o` | Cycle overlay mode |
| `c` | Toggle candidates |
| `t` | Toggle panels |
| `v` | Toggle Go/Pension mode |
| `s` | Run swarm round |
| `d` | Open domain modal |
| `1` | PORT page |
| `5` | OPT page |
| `0` | TDA page |
| `q` | Quit |

## Next Steps

- Read [Navigation & Modes](./navigation.md) for detailed navigation patterns
- Learn about [Slash Commands](./commands.md) for advanced interaction
- Explore [Overlays & Visualization](./overlays.md) for visual interpretation
