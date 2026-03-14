# Key Bindings

Complete reference for all keyboard shortcuts in the Gaius TUI.

## Navigation

| Key | Action | Description |
|-----|--------|-------------|
| `h` | Move left | Move cursor one position left |
| `j` | Move down | Move cursor one position down |
| `k` | Move up | Move cursor one position up |
| `l` | Move right | Move cursor one position right |
| `t` | Tenuki | Jump to point of highest strategic interest |

## View Controls

| Key | Action | Description |
|-----|--------|-------------|
| `v` | Cycle view | Cycle through view modes: Go, Theta, Swarm |
| `o` | Cycle overlay | Cycle through overlays: None, Topology, Geometry, Dynamics, Agents |
| `i` | Cycle iso | Cycle Iso view modes for MiniGrid projections |
| `c` | Toggle candidates | Show/hide candidate markers (a-i) at suggested positions |

## Panel Controls

| Key | Action | Description |
|-----|--------|-------------|
| `[` | Toggle left | Show/hide the FileTree panel |
| `]` | Toggle right | Show/hide the ContentPanel |
| `\` | Toggle both | Show/hide both panels simultaneously |

## Commands and Help

| Key | Action | Description |
|-----|--------|-------------|
| `/` | Command mode | Focus the command bar to enter a slash command |
| `?` | Help | Display help and key reference in the ContentPanel |

## Graph and Evolution

| Key | Action | Description |
|-----|--------|-------------|
| `g` | Graph | Cycle center panel between grid and graph views |
| `e` | Evolution | Show evolution panel directly |

## Notes

| Key | Action | Description |
|-----|--------|-------------|
| `Ctrl+n` | New note | Create a new Zettelkasten note and focus the editor |
| `Ctrl+z` | Zoom editor | Toggle editor zoom (tmux-style) |

## Application

| Key | Action | Description |
|-----|--------|-------------|
| `q` | Quit hint | Display quit instructions (use `/q` or `/exit` to actually quit) |

## Command Bar Keys

When the command bar is focused (after pressing `/`):

| Key | Action |
|-----|--------|
| `Enter` | Execute command |
| `Escape` | Cancel and return to normal mode |
| `Up` | Previous command in history |
| `Down` | Next command in history |
| `Tab` | Auto-complete command |

## Design Notes

Key bindings follow Vim conventions for navigation (`hjkl`) and use mnemonic single keys for mode cycling (`v` for view, `o` for overlay, `c` for candidates). Panel toggles use bracket keys (`[`, `]`, `\`) which are adjacent on a standard keyboard. The `/` key enters command mode, matching the slash-command convention used by Claude Code and similar tools.
