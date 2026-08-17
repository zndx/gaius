# Agenda first pass (web + MCP)

Consciousness surface: what to keep in mind, and how the day is
structured. Store is the KB. Users and agents write the same
zettels. Web and MCP are thin clients over engine gRPC.

## Shape

| Kind | Analog | Body |
|---|---|---|
| `note` | Keep card | Markdown |
| `list` | Keep checklist | `- [ ]` / `- [x]` |
| `event` | Calendar row | Markdown + `starts:` / `ends:` ISO-8601 |

Naming: `scratch/YYYY-MM-DD/YYYY-MM-DD-HHmmss_<skewer>.md`.
Header `prev:` / `next:` wiki-links chain same-kind cards (same
grammar as TUI project notes). `[[current/agenda]]` is the day
rollup hook; ThetaAgenda `list|init` still owns that file.

## Surfaces

- Engine: `AgendaList` / `Get` / `Create` / `Update` (`#AG.00000001`–`04`)
- CLI: `/agenda cards|create|get` (list/init stay Theta)
- MCP: `gaius__agenda_list|get|create|update` (engine-first)
- Web `/agenda`: Board (masonry) + Schedule, FAB `+`, editor,
  month rail, kind/tag/search, clickable prev/next

## Verified 2026-08-16

- Unit + servicer: 8 passed
- Live: `GET /agenda` 200 (`0.2.1-agenda`); list/create/update via
  HTTP; CLI cards/create/get; prev/next stitch on notes
- Live cards: pinned list, timed event, two notes
- Chromium headless dumped core here — board verified via API +
  compiled HTML, not a screenshot
- Session MCP process predates `agenda_*`; reconnect grok MCP to
  see the tools. Engine RPCs are live.

Engine `:50051` and gaius-ui `:9890` recycled for this pass.
Thinking/vLLM may still fail on `/dev/shm` (63G full); Agenda
does not need it.

## Not this pass

Autonomous cognition→agenda writer, TUI Keep board, rewriting
legacy `HHMMSS_type.md` names, Google Calendar sync.
