# Ask writes: small model → thinking → AgendaCreate

Create/change from Ask no longer essays on interpretable. The small
Ask backend classifies (256 tokens + handoff fence). The façade
escalates to `thinking`, which must emit a constrained
`:::gaius-artifact` `{type:agenda, action:create, …}`. gaius-ui then
calls Engine `AgendaCreate`. The calendar reloads and opens the card.

Detector (client `escalate=thinking` + server `looks_like_agenda_write`)
covers the case where the 1.7B model never hands off.

## Live check

`0.2.16-ask-agenda`. Progress: Complete interpretable → Escalating to
thinking → Creating Review Prospects → Booked.

`scratch/2026-08-16/2026-08-16-231114_review-prospects.md` —
session · event · 2026-08-17 09:00–09:30Z · with agents.
Guru `#AG.00000008.NOWRITE` if thinking omits the artifact.
