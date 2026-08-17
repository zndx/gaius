# Ask rail: Metabot-style thinking + progress

Ask was quiet until Engine/Complete returned (unary). Adopt the
Metabase Metabot pattern: handshake, one live status line, heartbeats,
then thinking and answer chunks.

## Shape (from Metabot)

- Immediate **Consulting Engine…** (client paints before first byte)
- Discrete progress: surface, `Complete {cap}…`, tools
- Heartbeats every 2.5s as `delta.status` — latest line only, history counted
- After Complete: peel `<think>` into the open Thinking panel, chunk answer
- Local `Working · Ns` clock so the rail still moves if SSE is delayed

Engine Complete stays unary. gRPC is unchanged. SSE is the UI façade.

## Live

Asset `0.2.15-ask-progress` on `:9890` (UI pid 4186867). Engine
untouched (`:50051`). Selenium at 300ms: Working +
`Engine · thinking · ~508 in` + `Looking at /agenda` before any
answer; then Thinking + 476-char trace + the sentence.
