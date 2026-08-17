# Gaius slash commands in the Grok `/` menu

Grok autocomplete is not the Gaius CLI parser. It lists:

1. Grok builtins
2. `user-invocable` skills / flat `.grok/commands/<name>.md` (stem = `/name`)

gaius-ui seeds the session workspace `.grok/commands/` with the CLI-shaped
surface that has a real MCP tool (`sitrep`, `thoughts`, `gpu`, …). Each body
calls `gaius__*`. `/agenda` is not seeded — sitrep's quick action has no RPC.
