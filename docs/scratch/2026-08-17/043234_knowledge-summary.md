# KNOWLEDGE collection summaries

Weekly Signals Summary stays on the in-process ACP path
(`run_weekly_summary` → scratch `*_wWW-summary.md`). That readout is
unchanged.

## What we added

Metaflow `KnowledgeSummaryFlow` (`gaius.flows.summary`) fans out with
`foreach` over `ontology` and `heuristic`. Each branch calls the engine
function `write_section_summary`, which walks the real KB folders:

- `current/ontology/**/*.md` → `current/ontology/summary.md`
- `current/heuristics/**/*.md` → `current/heuristics/summary.md`

Generated pages carry inline `[[wiki]]` hops. `.owl` files stay out.
`summary.md` is not listed as a note (no self-hop).

## Bindings

Summary lineup `section=ontology|heuristic` (no lens) is the standing
collection, not a keyword filter and not week-gated. Seed is
`summary.md` when present, else a virtual catalog of the same notes.

`/summary knowledge [section] [week]` writes the pages via
`Gaius/KnowledgeSummary`. The Monday weekly handler enqueues
`knowledge_summary` after the zettel so the flow can run on the next
processor tick without blocking ACP.

## Commands

```
/summary knowledge
/summary knowledge ontology
/summary index ontology
/summary index heuristic
```
