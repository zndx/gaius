# Feature Gaps: workflow.feature vs Current Implementation

This document catalogs the gaps between the desired research workflow (as specified in `features/workflow.feature`) and the current Gaius implementation. Features tagged with `@gap` in the feature file require implementation.

## Summary

| Category | Scenarios | Status |
|----------|-----------|--------|
| CLI commands | 12 | ✅ Implemented |
| Engine attachment | 3 | Partial (EvolutionPanel exists) |
| Profile/domain TUI | 3 | Needs status bar integration |
| Project notes TUI | 6 | CLI done, TUI display pending |
| Full-height mode | 3 | ❌ Not implemented |
| Document scrolling | 3 | ❌ Not implemented |
| Vim editing mode | 4 | ❌ Not implemented |
| :q document exit | 3 | ❌ Not implemented |
| Panel toggles | 2 | ✅ Implemented ([ ] \) |
| Search --append | 3 | ❌ Not implemented |
| Swarm document append | 5 | ❌ Not implemented |

## Priority 1: Full-Height Content Mode (Ctrl+Z)

**Gap**: No binding or action for expanding ContentPanel to full height.

**Current state**:
- `[ ] \` panel toggles exist and work
- No `ctrl+z` binding
- No layout state for "full-height mode"

**Required changes**:
1. Add `Binding("ctrl+z", "toggle_full_height", "Expand")` to app.py
2. Add `full_height: bool` to AppState
3. Implement `action_toggle_full_height()` that hides MainGrid, MiniGrids, Graph/Think/Evolution panels
4. CSS for `.full-height` state on center container

**Scenarios**: 3 (lines 161-183)

---

## Priority 2: Vim-Style Document Editing

**Gap**: ContentPanel displays markdown but has no editing capabilities.

**Current state**:
- `NoteEditor` widget exists but is separate from ContentPanel
- No vim-style modes (NORMAL/INSERT)
- No status bar mode indicator
- `i` key is bound to `cycle_iso` (iso mode), not insert mode

**Required changes**:
1. Add `EditMode` enum (NORMAL, INSERT, COMMAND) to state
2. Implement vim bindings when ContentPanel has focus:
   - `i` → enter INSERT mode
   - `G` (shift+g) → jump to end
   - `A` (shift+a) → jump to end + INSERT mode
   - `Escape` → exit INSERT mode, auto-save
   - `j/k` → scroll when in NORMAL mode
3. Status bar shows current mode
4. Focus management between grid and content panel

**Scenarios**: 4 (lines 222-255)

---

## Priority 3: Document Exit with :q

**Gap**: No vim-style command-line mode.

**Current state**:
- `/` enters command mode for slash commands
- No `:` prefix handling
- No document history stack

**Required changes**:
1. Detect `:` in NORMAL mode → enter COMMAND mode
2. Parse `:q` → close document, show previous
3. Maintain document history stack in AppState
4. `:q` in full-height mode should also restore layout

**Scenarios**: 3 (lines 262-286)

---

## Priority 4: Document Scrolling

**Gap**: j/k keys are bound to grid navigation globally.

**Current state**:
- `j/k` move grid cursor via `action_move()`
- ContentPanel may have internal scroll but no vim bindings
- No `Ctrl+D/U` half-page navigation

**Required changes**:
1. Context-aware key dispatch: grid vs content focus
2. When content panel focused: j/k scroll document
3. Add `Ctrl+D/U` bindings for half-page scroll
4. Arrow keys should work in content panel

**Scenarios**: 3 (lines 191-214)

---

## Priority 5: Search --append

**Gap**: /search shows results in panel, doesn't append to document.

**Current state**:
- `/search` command exists, performs hybrid search
- Results displayed in ContentPanel
- No append mode

**Required changes**:
1. Parse `--append` flag in search command
2. When appending:
   - Get current document path and cursor position
   - Format search results as markdown
   - Insert at cursor position
   - Update document in ContentPanel
3. Include source citations (wiki-links, URLs)

**Scenarios**: 3 (lines 318-342)

---

## Priority 6: Swarm Document Append

**Gap**: /swarm runs analysis but doesn't append to active document.

**Current state**:
- `/swarm` command triggers MCP `run_swarm` or `run_latent_swarm`
- Results shown in panel
- No streaming append to document

**Required changes**:
1. Detect if document is open when /swarm runs
2. Stream agent outputs to document in real-time:
   - `## Synthesis` (Leader)
   - `## Risk Analysis` (Risk)
   - `## Opportunities` (Opportunity)
   - `## Critical Review` (Critic)
   - `## Domain-Specific Insights` (Domain)
3. Append `## Cross-Agent Summary` when complete
4. Preserve scroll position or follow new content

**Scenarios**: 5 (lines 349-396)

---

## Implementation Order Recommendation

1. **Full-height mode** (Ctrl+Z) - Foundation for focused editing
2. **Document scrolling** - Basic navigation prerequisite
3. **Vim editing mode** - Core editing capability
4. **:q document exit** - Complete the vim UX loop
5. **Search --append** - Research workflow enabler
6. **Swarm document append** - Advanced research workflow

## Testing Strategy

- `@gap` tagged scenarios are skipped by default
- As features are implemented, remove `@gap` tag
- Run `behave --tags=@tui --tags=~@gap` to test implemented TUI features
- Full workflow test requires Textual Pilot framework

## Existing Bindings Reference

Current app.py bindings (relevant subset):
```python
Binding("h", "move(-1, 0)", "Left")
Binding("j", "move(0, 1)", "Down")      # Grid nav - conflicts with doc scroll
Binding("k", "move(0, -1)", "Up")       # Grid nav - conflicts with doc scroll
Binding("l", "move(1, 0)", "Right")
Binding("v", "cycle_view", "View")
Binding("o", "cycle_overlay", "Overlay")
Binding("i", "cycle_iso", "Iso Mode")   # Conflicts with insert mode
Binding("bracketleft", "toggle_left")   # [ - works
Binding("bracketright", "toggle_right") # ] - works
Binding("backslash", "toggle_both")     # \ - works
Binding("slash", "command_mode")        # / - works
Binding("ctrl+n", "new_note")
Binding("g", "toggle_graph")
Binding("e", "show_evolution")
```

Key conflicts to resolve:
- `i` currently cycles iso mode, needed for insert
- `j/k` currently grid nav, needed for doc scroll when focused
- `G` not bound, can use for jump-to-end
