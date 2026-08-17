# Theta: no client-side ThetaAgent fallback

Thin clients (CLI, TUI, MCP) and `GaiusServicer` no longer instantiate
`ThetaAgent` when the engine or `ThetaService` is missing.

| Surface | Was | Now |
|---------|-----|-----|
| MCP `theta_sitrep` / `theta_consolidate` / stats | `ThetaAgent(kb_root=...)` | `#THETA.00000008.NOENGINE` |
| `GaiusServicer` Theta* | same fallback | abort `#THETA.00000007.NOSVC` |
| CLI `/sitrep` | local `ThetaAgent.sitrep()` | `Gaius/ThetaSitrep` |
| CLI `/consolidate` | leftover `ThetaAgent` import | gRPC only |

`ThetaAgent` lives only in `ThetaService` (engine) and unit tests.
