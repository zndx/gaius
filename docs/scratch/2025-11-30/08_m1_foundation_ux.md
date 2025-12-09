# M1: Foundation + Quick UX Wins

**Date:** 2025-11-30
**Commit:** 00475ec

## Summary

Completed Milestone 1 of the Gaius v1.0 roadmap, establishing foundational infrastructure for testing, configuration, and UX polish.

## Deliverables

### 1. Behave BDD Infrastructure

```
features/
├── environment.py           # Test fixtures, Textual pilot integration
├── navigation.feature       # Grid navigation scenarios
├── kb_operations.feature    # KB CRUD scenarios
├── profile.feature          # Profile switching scenarios
└── steps/
    ├── navigation_steps.py  # Cursor, panel, mode steps
    └── kb_steps.py          # FileTree, search, graph steps
```

**Run tests:**
```bash
uv run behave --dry-run  # Validate step matching
uv run behave features/  # Full test run (requires TUI)
```

### 2. HOCON Configuration System

**Files:**
- `config/base.conf` - Full application settings with env substitution
- `config/profiles/{default,cloudera,weathership}.conf` - Profile-specific overrides
- `src/gaius/core/config.py` - GaiusConfig dataclass with PyHOCON loading

**Usage:**
```python
from gaius.core.config import get_config

# Load default profile
config = get_config()

# Load specific profile
config = get_config(profile="weathership")

# Access settings
print(config.inference.backend)  # "optillm"
print(config.swarm.roles)        # ["Leader", "Risk", ...]
print(config.tda.compute_interval_minutes)  # 30 (weathership)
```

**Profile Highlights:**
| Profile | Focus | TDA Interval | Swarm Roles |
|---------|-------|--------------|-------------|
| default | General | 60 min | 7 (all) |
| cloudera | Enterprise data | 60 min | 4 (Leader, Planner, Critic, Executor) |
| weathership | Research | 30 min | 7 (all) |

### 3. UX Improvements

**FileTree Root Node Removal:**
```python
# Before: Tree("/", id="kb-tree")
# After:
self._tree = Tree("Gaius", id="kb-tree")
self._tree.show_root = False
```

Result: "Agents/" and "KB/" appear as top-level siblings, no "/" clutter.

**CSS: Borders → Background Shading:**
```css
/* Before */
#left-panel {
    background: $surface-darken-1;
    border-right: solid $primary-darken-2;
}

/* After */
#left-panel {
    background: $surface-lighten-1;
    /* No border */
}
```

**Graph→ContentPanel Preview Sync:**
When navigating wiki-link graph nodes, content panel now shows truncated preview (20 lines) of the highlighted file.

## Design Decisions

From planning session:
1. **Think mode panel**: Will replace GraphView space (g cycles: graph → think → none)
2. **Profile storage**: DB + HOCON sync (DB is source of truth)
3. **TDA computation**: Scheduled background worker (hourly default)
4. **Swarm invocation**: Hybrid (auto on domain change + manual /swarm)

## Next Steps (M2)

- Add `CenterPanelMode` enum for think mode
- Create `ThinkPanel` widget
- Implement `enterApp` startup procedure
- Add OpenTelemetry foundation

## Files Modified

```
config/base.conf                    # Expanded with full schema
config/profiles/default.conf        # NEW
config/profiles/cloudera.conf       # NEW
config/profiles/weathership.conf    # NEW
features/environment.py             # NEW
features/navigation.feature         # NEW
features/kb_operations.feature      # NEW
features/profile.feature            # NEW
features/steps/navigation_steps.py  # NEW
features/steps/kb_steps.py          # NEW
src/gaius/core/config.py            # NEW - GaiusConfig system
src/gaius/core/__init__.py          # Added config exports
src/gaius/app.py                    # CSS + graph preview sync
src/gaius/widgets/filetree.py       # show_root=False
```
