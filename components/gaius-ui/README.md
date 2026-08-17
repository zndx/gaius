# gaius-ui

TUI-parity web surface for Gaius. Same shape as
[`signals-ui`](https://github.com/weathership/signals-ui): **Rust / Axum /
Askama**, **Keiretsu** chrome (`data-theme="keiretsu"`), no Node runtime.

| Path | TUI counterpart |
|------|-----------------|
| `/` Board (implicit landing; brand is home) | `MainGrid` + Embed/Iso minigrids + location κ / tenuki |
| `/agenda` | Consciousness calendar (zettels: note / list / event) |
| `/cognition` | Federation attention dashboard (`CognitionSurface`) |
| `/terminal` | Ghostty-web WASM VT ↔ PTY ↔ `grok` (see below) |
| `/settings` | Deployment logo pack (Weathership default · Cloudera · custom `.tgz`) |

Ask (chrome toggle, Ctrl+E) is a right panel over Engine/Complete. It
receives the current surface (Agenda focus + nearby rows, Cognition
recent thoughts) so "this flight" resolves to the open event.

Terminal prose stays on the PTY. Structured artifacts
(`:::gaius-artifact` or OSC `GaiusArtifact=`) are peeled in `pty.rs`
and rendered in Ask (Keiretsu SVG OHLC). MCP `gaius__ask_present`
fetches FMP EOD and posts the same payload; print the returned `fence`
verbatim. `/chart <symbol>` is the slash.

```sh
export GAIUS_UI_BIND=0.0.0.0:9890   # default; LAN-visible
just ui
# http://<host>:9890/
```

`devenv` process `gaius-ui` starts with the unit (`just up` / `gaius.service`).

Keiretsu CSS is vendored from the shared template (Atelier / Signals /
`cldr-design-template`). Do not restyle locally; sync upstream.

Logo packs live under `assets/brand/` (`weathership` default, `cloudera`,
empty `custom`). Operators switch them on `/settings` or
`GAIUS_UI_BRAND`. Custom is a Weathership-shaped `.tgz` written to
`build/dev/.gaius-ui-brand/custom/`.

The board API (`GET /api/gaius/v1/board`) is honest-empty until the engine
streams curvature / tenuki / the live scratchpad — it does not invent κ.

## Terminal: Ghostty VT + Grok harness

The harness is **not compiled into the web page**. Ghostty-web is only
the VT (bytes in, pixels out). `grok` is a host process on a PTY.

```
browser  /terminal
   │  ghostty-web.js + ghostty-vt.wasm   (assets/ghostty/, from Atelier)
   │  terminal.js  WS  {type:text|input|resize}
   ▼
gaius-ui  GET /ws/terminal/{id}          (crates/gaius-ui/src/pty.rs)
   │  portable-pty  master/slave
   ▼
grok --fullscreen --trust --sandbox workspace -m gaius-thinking
   │  GROK_HOME = build/dev/.gaius-ui-grok/{id}   (config, sessions)
   │  CWD       = build/dev/.gaius-ui-ws/{id}    (workspace — not the checkout)
   │  HTTP  POST /v1/chat/completions
   ▼
gaius-ui  openai.rs  →  Engine/Complete  (capability=thinking → Qwen3.8-27B)
```

The Gaius checkout is not the agent's filesystem. MCP `gaius` is how it
reaches the engine/KB. `--sandbox workspace` lets the harness write only
the session workspace (plus `GROK_HOME` / tmp). That profile
re-execs through `bwrap` (`pkgs.bubblewrap` in `devenv.nix`). Missing
`bwrap` is `#UI.00000002.NOBWRAP` — fail-fast, not an unsandboxed start.

`GAIUS_GROK_BIN` (default `~/.local/bin/grok`) is the binary. Source
lives in `external/oss-grok-build` (`weathership/oss-grok-build`,
tracking `xai-org/grok-build`). A grok-wasm module would replace the
PTY process, keep Ghostty as the VT, and back `AsyncFileSystem` with
the browser Origin Private File System instead of this host directory.
