# Terminal attach: VT snapshot, not dirty-cell replay

Reload starts a blank Ghostty. Grok/ratatui only emits dirty cells, so
reattach drifted. gaius-ui now keeps a vt100 screen and on attach sends
`contents_formatted()` (plus alt-screen enter). Live bytes still stream.
