# Terminal is Ghostty WASM + Grok PTY, not a REPL façade

Do not wrap Grok in an Atelier-style line buffer. Ghostty-web is the
VT (WASM). oss-grok-build is the agent harness, spawned on a PTY.
The same VT byte interface is what a later grok-wasm module would
speak — we do not invent a second protocol.

Grok's custom model `gaius-thinking` calls this process
`/v1/chat/completions`, which is `zndx.engine.v1.Engine/Complete`
(`capability=thinking`). MCP `gaius` is stdio to `gaius.mcp_server`.
`GROK_HOME` is per-session under `build/dev/.gaius-ui-grok/`.
