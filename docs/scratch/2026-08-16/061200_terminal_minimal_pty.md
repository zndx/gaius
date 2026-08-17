# Web terminal waiting: fullscreen, leaked env, folder-trust gate

The harness was up. Ghostty-web looked idle because:

1. grok was `--fullscreen` (alt-screen paint lost on reconnect)
2. this session leaked `GROK_AGENT=1` and metered API keys
3. isolated `GROK_HOME` had never trusted the repo, so grok
   sat on "Do you trust the contents of this directory?"

Spawn is `--minimal --no-alt-screen --trust`, leak vars
(including `SSH_*`/`TMUX*`) stripped, `trusted_folders.toml`
pre-seeded, PTY replayed on reconnect. Refresh `/terminal`.
