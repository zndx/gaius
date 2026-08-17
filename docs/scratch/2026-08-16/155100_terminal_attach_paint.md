# Terminal stuck on attach banner

Reload reattached to a live grok whose 256KiB PTY replay was only
ratatui cursor ticks (`CSI 52;7H`, kitty `_Ga=`). Alt-screen enter
(`CSI ?1049h`) had been dropped, so Ghostty stayed on the primary
screen showing the gaius-ui hello line.

Fix: replay only a full paint; otherwise SIGWINCH grok. Do not write
the hello banner into the VT. Restarted gaius-ui; probe session
painted `Grok Build 1.0.4` on first attach and reattach.
