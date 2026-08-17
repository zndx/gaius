# Web harness workspace is not the Gaius checkout

Each `/terminal` session gets `build/dev/.gaius-ui-ws/{id}` as CWD
(`--sandbox workspace`, folder-trust on that path only). MCP `gaius`
still stdio's into the engine; that is context, not a bind-mount.

In-browser destination: grok-wasm + Ghostty VT + OPFS implementing
`xai_grok_workspace::AsyncFileSystem` (same trait as `LocalFs` /
`AcpSessionFs`). Host dir is the stand-in until that module exists.
