# UI Polish Fixes

**Date:** 2025-12-01
**Session:** UI polish - focus, duplication, think panel, colors

## Summary

Fixed four UI issues identified during testing:

1. Tab-focus visual indication
2. Content duplication between panels
3. Think panel functionality
4. Invalid Rich color names

## Fixes Applied

### 1. MissingStyle 'bold orange' Color Error

**Problem:** Hard crash with `MissingStyle: Failed to get style 'bold orange'; unable to parse 'orange' as color`

**Cause:** Rich/Textual doesn't recognize "orange", "purple", or "silver" as color names.

**Solution:** Updated `agents/roles.py` with valid Rich color names:
- `orange` → `dark_orange`
- `purple` → `medium_purple`
- `silver` → `grey70`

### 2. Content Duplication

**Problem:** Startup thoughts shown in both center-panel editor AND info-panel.

**Solution:** Changed info-panel to show brief summary instead of duplicate:
```python
# Before (duplicate)
content.show_file("thoughts.md", note_content)

# After (brief summary)
content.show_file(
    "startup.md",
    f"# Session Started\n\n"
    f"**Thoughts note:** `{note_path.name}`\n\n"
    f"*Edit in center panel or dismiss with `[`*"
)
```

### 3. Think Panel Functionality

**Problem:** ThinkPanel displayed but never populated with traces.

**Solution:** Added trace recording hooks to key operations:

```python
# Startup reflection
think.stream_reasoning("Generating startup reflection...")
# ... do reflection ...
think.complete_trace(
    operation="synthesis",
    query=f"startup: {domain}",
    summary=f"Reflection ({len(text)} chars)",
    tokens=result.tokens_used,
    sources=result.entries_considered,
    duration_ms=result.duration_ms,
)

# Daily summary
think.stream_reasoning("Generating daily summary...")
# ... generate ...
think.complete_trace(
    operation="synthesis",
    query="daily summary",
    summary=f"Generated summary: {note.title}",
    ...
)
```

### 4. Tab-Focus Visual Indication

**Problem:** No visual feedback when widgets receive focus via Tab.

**Solution:** Added focus CSS for all major widgets:

```css
/* Focus indicators */
#left-panel:focus-within { border-right: solid $accent; }
FileTree:focus { border: solid $accent; }
MainGrid:focus { border: solid $accent; }
MiniGrid:focus { border: solid $accent; }
#graph-view:focus { border: solid $accent; }
#think-panel:focus { border: solid $accent; }
ContentPanel:focus { border: solid $accent; }
#note-editor:focus-within { border: solid $accent; }
CommandInput:focus-within {
    background: $surface-darken-2;
    border-top: solid $accent;
}
```

Also added `can_focus=True` to widgets:
- `MainGrid`
- `ThinkPanel`
- `ContentPanel`

### 5. Focus Refinements (Follow-up)

**Feedback:** Red border breaks 19x19 grid alignment, graph/think panel already has title highlight, prefer changing existing interior border color.

**Refinements:**
1. **MainGrid** - Removed from tab order (hjkl works globally)
2. **GraphView/ThinkPanel** - Removed focus border (has title highlight)
3. **Left/Right panels** - Changed interior border color on focus (not full border)
4. **CommandInput** - Removed from tab order (access via '/')
5. **ContentPanel** - Added arrow key scrolling when focused

**Simplified Focus CSS:**
```css
/* Left panel - change interior border color on focus */
#left-panel:focus-within { border-right: solid $accent; }

/* Right panel - change interior border color on focus */
ContentPanel:focus { border-left: solid $accent; }

/* Note editor focus */
#note-editor:focus-within { border: solid $accent; }
```

**ContentPanel Scrolling:**
```python
BINDINGS = [
    Binding("up", "scroll_up", ...),
    Binding("down", "scroll_down", ...),
    Binding("pageup", "page_up", ...),
    Binding("pagedown", "page_down", ...),
    Binding("home", "scroll_home", ...),
    Binding("end", "scroll_end", ...),
]
```

## Files Modified

- `src/gaius/agents/roles.py` - Fixed color names
- `src/gaius/app.py` - Focus CSS, duplication fix, trace hooks
- `src/gaius/widgets/grid.py` - Removed `can_focus` (use hjkl)
- `src/gaius/widgets/think_panel.py` - Removed `can_focus` (has title)
- `src/gaius/widgets/content.py` - Added arrow key scrolling
- `src/gaius/widgets/command.py` - Removed from tab order

## Testing

```
MainGrid: can_focus = False
ThinkPanel: can_focus = False
ContentPanel: can_focus = True
ContentPanel bindings: ['up', 'down', 'pageup', 'pagedown', 'home', 'end']
All imports successful!
```

## Usage

- **Tab** - Cycle focus between FileTree, ContentPanel, NoteEditor
- **hjkl** - Navigate 19x19 grid (works globally)
- **/** - Access command input
- **g** - Cycle center panel: GRAPH → THINK → NONE
- **Arrow keys** - Scroll ContentPanel when focused
- Think panel shows real-time reasoning traces during operations
