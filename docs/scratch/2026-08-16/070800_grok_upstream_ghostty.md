# oss-grok-build synced to xai-org; Ghostty is VT only

`weathership/oss-grok-build` was a rewritten one-commit root
(`b189869`), not `c68e39f`, so GitHub compare had no merge-base.
`gh repo sync --force` pointed the fork at `xai-org/grok-build`
`5163763` (1.0.4, SOURCE_REV `84ae1223`). Submodule follows.

Ghostty-web is the VT. `pty.rs` spawns host `grok` on a PTY.
Inference is `/v1` → Engine/Complete. Not grok-wasm yet.
