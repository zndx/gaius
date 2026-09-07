# surface_integrity conversation aspect (Agenda / AgentRTC)

2026-09-07. After in-place UXR rewrite of today's Agenda cards and two
forward sessions (watchlist after FMP tape; Theta retrospective), the
composite objective grows a **conversation** aspect so later emit/brief
workflows can be scored against the curated bar without reengineering
emit in the same step.

## What a visitor (or the voice) receives

Horizon = today · tomorrow · week only. Past Iceberg-failure reminders
stay ugly on purpose and are out of scope for these gates.

| gate | observable |
|---|---|
| `agenda_lede_is_prose` | `summary` must not open as `- [ ]`, `BEGIN SESSION`, traceback, guru, "Catch-up with a colleague" |
| `agenda_session_has_a_question` | each `intent=session` poses an ask |
| `agenda_brief_matches_horizon` | spoken must not say tomorrow/week empty when those buckets have items |
| `agenda_intents_diverse` | n≥3 ⇒ ≥2 intents and ≥1 session |

Specimens: JSON example K (curated PASS), L (pre-UXR FAIL). Historical
A–J omit `agenda` → conversation gates `error` (facts not in the specimen).
