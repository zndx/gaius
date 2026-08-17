# Terminal stays under chrome

Ghostty canvas is an explicit pixel box. `100vh` + 56px header let
`html` scroll and shove the top nav off-screen (focus/scrollIntoView
made it worse).

Terminal route is a column flex: chrome `flex-shrink: 0`, leftover
box is `#terminal-wrap` `position:absolute; inset:0`. FitAddon
measures that box. `overflow: clip` + scroll lock so Ghostty's
contenteditable caret cannot scroll Grok's top chrome out of view.
