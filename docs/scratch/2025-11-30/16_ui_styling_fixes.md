# UI Styling Fixes

Addressed UI/UX drift that had accumulated, restoring the cleaner visual appearance.

## Changes Made

### 1. Graph Panel Background Removed
- **Before**: `GraphView` had `background: $surface-darken-1`
- **After**: Background removed - the graph-grid provides sufficient visual grounding
- **File**: `widgets/graph_view.py`

### 2. Think Panel Background → Border
- **Before**: `ThinkPanel` had `background: $surface-lighten-1`
- **After**: Uses `border: solid $primary-darken-2` for separation
- **File**: `widgets/think_panel.py`

### 3. MiniGrid Background Removed
- **Before**: `MiniGrid` had both border AND `background: $surface-darken-1`
- **After**: Background removed, relying on border for visual separation
- **File**: `widgets/minigrid.py`

### 4. Left-Nav Border Restored
- **Before**: `#left-panel` had only `background: $surface-lighten-1`
- **After**: Uses `border-right: solid $primary-darken-2` to tie UI together
- **File**: `app.py` CSS

### 5. Right Panel Background Removed
- **Before**: `#right-panel` had `background: $surface-lighten-1`
- **After**: Background removed, `ContentPanel` provides its own styling
- **File**: `app.py` CSS

### 6. Note Editor Background → Border
- **Before**: Had `background: $surface-lighten-1`
- **After**: Uses `border: solid $primary-darken-2`
- **File**: `app.py` CSS

## Theme Configuration System

Added configurable theme system in HOCON:

```hocon
gaius {
  theme {
    name = "dark"  # dark, light, terminal, go
    border_style = "solid"  # solid, round, double, heavy, none

    # Semantic colors
    primary = "$primary"
    secondary = "$secondary"
    surface = "$surface"
    accent = "$accent"

    # Component-specific
    panel_border = "$primary-darken-2"
    header_bg = "$primary-darken-3"
    status_bar_bg = "$primary-darken-3"
  }
}
```

### Files Changed

- `src/gaius/core/config.py` - Added `ThemeConfig` dataclass
- `config/base.conf` - Added `theme` section

### Usage

```bash
# Use default dark theme
uv run gaius

# Set theme via environment
GAIUS_THEME=go uv run gaius
```

## Design Principles Applied

1. **Border over background** - Use borders for visual separation instead of fill colors
2. **Let content breathe** - Remove unnecessary backgrounds that compete with content
3. **Consistent theming** - All borders use the same color variable (`$primary-darken-2`)
4. **Config-driven** - Theme is now a configuration option, not hard-coded CSS
