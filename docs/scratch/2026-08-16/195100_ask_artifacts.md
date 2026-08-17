# Terminal artifacts in Ask

PTY peels `:::gaius-artifact` / OSC `GaiusArtifact=` so Ghostty
never shows JSON. Ask renders Keiretsu SVG OHLC. MCP
`gaius__ask_present` loads FMP EOD and POSTs the same payload;
print the `fence` field so peel still fires. Empty bars fail
`#UI.00000008.NOBARS`.
