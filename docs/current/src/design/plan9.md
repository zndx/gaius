# Plan 9 & Acme

Plan 9 from Bell Labs (1992) was Ken Thompson and Rob Pike's attempt to push Unix ideas to their logical conclusion. Its text editor, Acme (1994), remains one of the most influential programmer tools ever created.

## Plan 9 Philosophy

### Everything is a File

Unix had "everything is a file" as aspiration. Plan 9 achieved it:
- Network connections: files
- Processes: files
- Graphics: files
- Input devices: files

This uniformity enables composition. Any tool that reads files can process any system resource.

### Distributed by Design

Plan 9 assumed network operation. Local and remote resources accessed identically. Your terminal could seamlessly use CPU from across the network.

### Simplicity Through Completion

Rather than adding features, Plan 9 removed special cases. The result is smaller but more general.

## Acme: A Different Editor

Acme is startling to modern users:
- No syntax highlighting
- No configuration files
- No plugins
- No key bindings (almost)

And yet, Acme users are among the most productive programmers.

### Mouse Chording

Acme uses three-button mouse chording:
- **Left**: Select text
- **Middle**: Execute selected text as command
- **Right**: Search/open selected text

Any text can become a command. Type `make`, select it, middle-click. The boundary between text and action dissolves.

### Tags as Command Lines

Each window has a "tag" line containing text. That text is executable:

```
/home/user/project Del Snarf Get | fmt | Look
```

Click on `Del` to delete the window. Click on `fmt` to reformat. The tag is a command palette you can edit.

### No Modes

Acme has no insert/command mode distinction. You're always in "insert mode"—typing inserts text. Commands are executed by clicking on them.

This eliminates mode errors entirely.

### Plumbing

Plan 9's plumber routes messages based on content. Click on a filename: it opens. Click on an error with line number: editor jumps there. Click on a URL: browser opens.

Pattern matching replaces explicit handlers.

## What Gaius Inherits

### Text as Command

Gaius plans to make log panel text executable:

```
[Risk] Cluster forming at K10-L12. Consider /analyze K10.
```

Click on `/analyze K10` to execute it. Agent suggestions become actionable.

### Minimal Configuration

Gaius aims for sensible defaults. The grid is 19×19. Colors are fixed. Navigation is `hjkl`. Power comes from composition, not configuration.

### Compositional Commands

Planned command piping:

```
/region D4-F6 | /analyze | /summarize
```

Small operations combine into complex workflows—the Unix way.

### Simplicity Through Generality

One grid serves many purposes:
- Go stones
- Pension allocations
- Agent positions
- Topological features

The grid is general; overlays specialize.

## Where Gaius Differs

### Modes Exist

Acme's modelessness works for text editing. Gaius's modes serve navigation:
- Normal mode: `hjkl` moves cursor
- Command mode: typing enters commands
- (Future) Visual mode: region selection

Modes concentrate related operations without modifier keys.

### Keyboard Priority

Acme was designed for mice (three-button, specifically). Gaius prioritizes keyboard:
- Navigation without mouse
- Commands via slash prefix
- Mode switching via single keys

Both approaches are valid; Gaius serves users who prefer keyboard.

### Visualization Over Text

Acme is fundamentally a text environment. Gaius is fundamentally visual:
- Grid as primary display
- Symbols over words
- Patterns over paragraphs

## Lessons from Plan 9/Acme

### 1. Composition Over Features

Don't add a feature when you can compose existing ones. Gaius's overlay system composes simple layers; it doesn't have a "complex visualization mode."

### 2. Uniformity Enables Power

Consistent interaction patterns (every overlay cycles with `o`, every mode toggles with its key) compound into expertise.

### 3. Text as Interface

Making text executable bridges display and action. Log panel entries become command suggestions.

### 4. Defaults Over Configuration

Every configuration option is a decision users must make. Prefer good defaults. Gaius's fixed color scheme and grid size are deliberate.

### 5. Network Transparency

Gaius doesn't yet have distributed operation, but the architecture anticipates it:
- Agent swarms could run remotely
- Vector memory could be shared
- Grid state could synchronize

## The Acme User Profile

Acme attracts a specific user: one who prefers mastery over convenience, composition over features, simplicity over apparent ease.

Gaius seeks the same users:
- Experts who will invest in learning
- Polymaths who work across domains
- Professionals who value efficiency

If you want a tool that works immediately without learning, Gaius (like Acme) isn't it. If you want a tool that rewards mastery, welcome.

## Rob Pike's Influence

Pike's essays—"Notes on Programming in C," "A Lesson in Brevity," various design rationales—express a philosophy:
- Clarity over cleverness
- Data structures over algorithms
- Composition over inheritance (before OOP made this controversial)

Gaius aspires to this clarity: a small set of concepts (grid, overlays, modes, commands) that compose into powerful workflows.
