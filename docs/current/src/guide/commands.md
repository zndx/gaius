# Slash Commands

Gaius implements a slash command system inspired by Claude Code. Commands provide precise control beyond what key bindings offer.

## Command Mode (Planned)

Press `/` to enter command mode. The status line becomes an input field. Type your command and press Enter.

```
/analyze K10
```

Press Escape to cancel and return to normal mode.

## Command Syntax

```
/command [arguments] [--flags]
```

Arguments are space-separated. Flags modify behavior.

## Core Commands

### Navigation Commands

```
/goto K10          # Move cursor to K10
/center            # Center cursor at J10
/mark D4 critical  # Add label to position
/unmark D4         # Remove label
```

### Query Commands

```
/info              # Show info about current position
/info K10          # Show info about K10
/neighbors         # List adjacent positions and their state
/region D4-F6      # Analyze rectangular region
```

### Swarm Commands

```
/domain "supply chain"  # Set analysis domain
/round                   # Run a swarm round
/ask "What risks?"       # Direct query to swarm
/focus Risk              # Highlight specific agent
```

### Memory Commands

```
/recall inflation    # Search memory for similar utterances
/history             # Show recent agent outputs
/clear               # Clear memory (with confirmation)
/export log.json     # Export session to file
```

### TDA Commands

```
/tda                # Run TDA computation
/loops              # List persistent H1 features
/entropy            # Show current persistence entropy
/clusters           # Show connected components
```

### View Commands

```
/overlay topology   # Set overlay mode
/mode theta         # Set view mode
/zoom D4-F6         # Focus on region (future)
/screenshot         # Save current view (future)
```

## Command Completion

Tab completion assists command entry:

```
/ana<TAB> → /analyze
/dom<TAB> → /domain
```

Arguments also complete:
```
/focus R<TAB> → /focus Risk
```

## Command History

Use up/down arrows to navigate command history. History persists within a session.

## Piping (Future)

Commands can pipe output to subsequent commands:

```
/recall risk | /summarize
/region D4-F6 | /analyze
```

## Custom Commands

Define custom commands in configuration (planned):

```yaml
commands:
  pension-crisis:
    steps:
      - /domain "pension asset allocation"
      - /round
      - /overlay h1
      - /ask "What are the top 3 liquidity risks?"
```

Invoke with:
```
/pension-crisis
```

## Acme-Inspired Execution

Following Plan 9's Acme editor, any selected text can be executed as a command by middle-clicking (or equivalent binding). This enables:

- Comments in logs that are also executable
- Self-documenting workflows
- Interactive exploration

## Error Handling

Invalid commands show clear errors:

```
/frobnicate
Error: Unknown command 'frobnicate'. Type /help for available commands.
```

Missing arguments prompt:
```
/goto
Error: /goto requires a position argument. Usage: /goto <position>
```

## Help

```
/help              # List all commands
/help analyze      # Show help for specific command
```

## Integration with Key Bindings

Many common commands have key binding equivalents:

| Command | Binding | Notes |
|---------|---------|-------|
| `/overlay topology` | `o` | Cycle mode |
| `/mode theta` | `v` | Toggle mode |
| `/round` | `s` | Swarm round |
| `/domain` | `d` | Opens modal |

Commands offer precision; bindings offer speed. Use both.
