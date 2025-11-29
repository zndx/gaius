# Wiki-Link System Design

## Overview

Implement wiki-style linking in scratch notes to create and navigate entries under `current/`. Links automatically create a graph structure and update when notes are archived.

## Syntax

```markdown
[[current/projects/new-project/agenda]]
```

- Double brackets denote a wiki-link
- Path is relative to KB root (`build/dev/`)
- Supports nested paths with `/`

## Link Resolution

1. **Parse**: Extract `[[path]]` patterns from note text
2. **Resolve**: Check if `build/dev/{path}.md` exists
3. **Create or Link**:
   - If exists: Create clickable link
   - If not exists: Create file on first navigation, or mark as "pending"

## File Creation

When navigating to a non-existent link:

```
build/dev/current/projects/new-project/agenda.md
```

- Create parent directories as needed
- Initialize with template:
  ```markdown
  # {title}

  Created: {timestamp}
  Linked from: [[scratch/{date}/{note}]]

  ---

  ```

## Link Graph

Track bidirectional links in a graph structure:

```python
@dataclass
class LinkGraph:
    # Forward links: source -> [targets]
    forward: dict[str, set[str]]

    # Backlinks: target -> [sources]
    back: dict[str, set[str]]

    def add_link(self, source: str, target: str): ...
    def remove_link(self, source: str, target: str): ...
    def get_backlinks(self, path: str) -> set[str]: ...
```

## Archive Migration

When moving scratch notes to archive:

1. Scan note for `[[current/...]]` links
2. Update all backlinks in `current/` files to point to new archive location
3. Optionally: Update internal links if referenced notes are also archived

### Example

Before archive:
- `scratch/2025-11-28/1234567890.md` contains `[[current/projects/foo]]`
- `current/projects/foo.md` has backlink to scratch note

After archive (Q4 2025):
- Move to `archive/2025Q4/1234567890.md`
- Update `current/projects/foo.md` backlink: `[[archive/2025Q4/1234567890]]`

## Implementation Phases

### Phase 1: Link Parsing (Current)
- Regex to extract `[[...]]` patterns
- Display as highlighted text in editor

### Phase 2: Navigation
- Click/Enter on link to open target
- Create file if doesn't exist

### Phase 3: Backlinks
- Parse all files on startup to build graph
- Update graph on file save
- Show backlinks in content panel

### Phase 4: Archive Migration
- `/archive` command to move scratch to archive
- Automatic backlink updates

## Data Storage

Link graph persisted to:
```
build/dev/.gaius/
├── links.json      # Serialized link graph
└── index.json      # File metadata cache
```

## Editor Integration

In `NoteEditor`:
- Highlight `[[...]]` patterns with distinct color
- Ctrl-Enter or click to follow link
- Auto-complete for existing paths

## Commands

- `/links` - Show links from current note
- `/backlinks` - Show notes linking to current
- `/archive [note]` - Archive a scratch note
- `/graph` - Visualize link graph (future)
