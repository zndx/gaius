# Where the buffer, Ricci, and Tenuki live

The **19×19 MainGrid** is the home surface. Ollivier-Ricci κ is the
GEOMETRY overlay. Tenuki is an *annotation on that same field* (`☆`
last jump, `∘` visited) — not a second map. Embed / Iso minigrids stay
the CAD pair (Iso = κ elevation). Cognition is the right-hand strip
and `/cognition`: situation + the one-next-question reserve.

| Concern | TUI | Web (`components/gaius-ui` · Keiretsu / Axum) |
|---------|-----|-----------------------------------------------|
| Ricci κ | `o` → GEOMETRY; location `κ` | Board heatmap + stat |
| Tenuki | `t`; marks on the board | ☆ / ∘ on `/` |
| Cognition | info panel `### Cognition` | `/cognition` |
| One next question | status `1Q` | reserve stat / assemble |
| Agent terminal | native `gaius` | Ghostty + `external/oss-grok-build` |

Web emulates **signals-ui** (Rust, Askama, shared Keiretsu template —
same chrome as Atelier / Aegir / Metabase). Every TUI pane is a web
route in the same chrome; do not grow a Node SPA. Ghostty is the
exception (WASM in-page); the PTY target is `grok` from
`external/oss-grok-build`, not a chat session.
