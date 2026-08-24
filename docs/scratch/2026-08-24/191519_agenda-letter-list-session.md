# Agenda genres: letter, shared list, colleague catch-up

`/agenda` is the operator surface. Cognition writes those cards, not a
second ledger operators never see. Postgres `agenda_entries` stays a
warehouse index (`episode_id`, `hx_generation_id`).

## Genres

| Intent | Shape | What the card is |
|--------|--------|------------------|
| brief | note | A letter or memo written for an executive, in natural-register prose |
| reminder | list | Shared suggestions between agents and operators (and later other agents) |
| session | event | A time to catch up with a colleague; discussion headlines live in the calendar description, plus a Terminal paste block |

Guru codes stay in Thinking RCA (`SEARCH_GURU`). They are stripped from
executive copy.

## Write path

`insert_agenda` density-caps the cycle, then `agenda_notes.create_item`
for each accepted row. Missing KB is fail-fast (`#AG.00000001.NOKB`).
Sessions without a start time are not written (zip against
`next_session_slots`).

## Surfaces updated

Prompt (`SYNTH_PROMPT`), `/agenda` kicker and FAB (List, not Reminder),
Ask write addendum, `/agenda` slash skill, MCP `agenda_create`.
