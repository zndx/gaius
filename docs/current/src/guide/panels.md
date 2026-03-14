# Panels

Gaius has two side panels flanking the central grid: the **FileTree** on the left and the **ContentPanel** on the right. Both can be toggled independently or together.

## Toggle Controls

| Key | Action |
|-----|--------|
| `[` | Toggle left panel (FileTree) |
| `]` | Toggle right panel (ContentPanel) |
| `\` | Toggle both panels simultaneously |

When a panel is hidden, the grid expands to fill the available space.

## Left Panel: FileTree

The FileTree presents a Plan 9-inspired hierarchical view of the system. Everything is navigable as if it were a filesystem:

```
/
  agents/
    cognition/
    evolution/
    health/
  kb/
    current/
      projects/
      content/
    scratch/
  state/
```

Agents are represented as files under `/agents/`. Knowledge base entries appear under `/kb/`. System state is exposed under `/state/`. This design follows the Plan 9 philosophy where everything -- processes, data, system state -- is accessible through a uniform file interface.

Selecting an entry in the FileTree updates the ContentPanel on the right to show its contents.

## Right Panel: ContentPanel

The ContentPanel is the primary output area. It displays:

- **File contents** -- when a FileTree entry is selected
- **Command output** -- results from slash commands (e.g., `/health`, `/gpu status`)
- **Position context** -- information about the current grid position
- **Help** -- key binding reference when `?` is pressed
- **Agent output** -- responses from agent operations

The ContentPanel renders markdown-formatted text, tables, and structured data. It scrolls vertically for long output.

## Layout Strategies

Different tasks benefit from different panel configurations:

**Full context** (default): both panels visible. Use when you need to navigate the knowledge base and see detailed output simultaneously.

**Grid focus**: press `\` to hide both panels. Use when studying spatial patterns, overlay composition, or doing pure grid exploration.

**Research mode**: hide the left panel with `[`. The grid and ContentPanel share the screen, giving more room for command output and detailed content.

**Navigation mode**: hide the right panel with `]`. The FileTree and grid share the screen, useful when browsing the knowledge base structure without needing detailed content.

## Panel Persistence

Panel visibility state persists during your session. If you hide a panel and run a command, the panel stays hidden. Toggle it back when you need it.
