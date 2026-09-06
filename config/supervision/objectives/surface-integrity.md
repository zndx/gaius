# Surface Integrity (composite objective on the public surface)

## Description:
This objective is defined on the **final surfaced result** — the cards a
visitor sees at https://gaius.zndx.org/ — and asks one composite question with
three aspects: is the surface **current**, is it **clean**, and is it
**conserved**. It replaces `content_currency` (2026-09-01 → 2026-09-06) and
absorbs the source-integrity and conservation gates added on 2026-09-06 after
adversarial marketing content reached the page and after a currency FAIL had
been cleared by archiving content. The mechanics pair, `site_freshness`,
stays separate: it proves cards flow; this proves the right cards are on the
page and stay there.

The card follows the sdg-strategy `objective` pillar's task-card shape
(`external/sdg-strategy/objective/tasks/*.md` + `tasks-json/*.json`): the
normative statement lives here, the JSON twin carries typed **examples** —
each a real or constructed specimen of facts with the expected verdicts — and
`tests/engine/test_surface_integrity.py` runs every example through the same
pure evaluator the engine uses live (`gaius.engine.services.surface_integrity.evaluate`).
That is how composite sophistication keeps the demonstrated functional
efficacy: a specimen that once surfaced a fault is pinned forever.

### Facts (the evaluator's input)

| key | source | shape |
|---|---|---|
| `today`, `now` | Postgres clock | ISO date / ISO timestamp (UTC) |
| `surface` | GET `surface_url`, parsed as the visitor sees it | ordered `[[card_id, "YYYY-MM-DD" \| null], …]` |
| `top_published_at` | `collections.cards.published_at` of `surface[0]` | ISO timestamp or null (null = surface/DB incoherence) |
| `corpus_newest` | `max(source_date)` over all cards | ISO date; diagnosis only |
| `published` | `collections.cards WHERE status='published'` | `[{card_id, source_url, title}]` |
| `denied_domains` | `$discard,site=` lines of `config/brave/web-half.goggle` | `[domain, …]` |
| `events` | `collections.card_events` over `conservation_window_hours` | `{window_hours, journal_since, added, removed: [{card_id, reason}]}` |
| `<section>_error` | any failed collection | string; the section's gates render `error` |

### Aspects and gates

| aspect | gate | criterion | rationale (rule 3) |
|---|---|---|---|
| currency | `surface_newest_current` | newest visible date ≥ today − `newest_days` (2) | daily curate (09:07 UTC) + day-granular dates |
| currency | `surface_band_current` | share of the first `band` (26) cards within `current_days` (7) ≥ `min_current_share` (0.5) | intended mix ≈ 20 curate : 6 slots (0.77); floor is half |
| currency | `surface_refreshed_within_intent` | top card published ≤ `refresh_hours` (13) ago; unknown to the DB = fail | slots 12/17/21/02 UTC, longest gap 10 h → F=13 |
| integrity | `no_marketing_shapes` | `looks_like_marketing(url, title)` matches 0 published cards | what acquisition refuses must not be on the page |
| integrity | `no_denied_domains` | 0 published cards from a goggle-discarded domain | the goggle's discard list is the vendor list |
| integrity | `no_duplicate_sources` | no `source_url` published more than once | one card per source across articles |
| conservation | `no_unexplained_removals` | 0 published→archived transitions in the window without a reason | the surface may not shrink silently (2026-09-05) |
| conservation | `removal_reasons_declared` | every explained removal's category ∈ `duplicate\|adversarial\|license\|retired\|broken\|operator` | "stale" is not a reason; acquisition is |

**Monotonicity.** With every status transition journaled, "the published
surface is non-decreasing except by declared-reason removals" is exactly the
two conservation gates: a removal is either explained with a declared
category or it is a fault. Growth itself is `site_freshness`'s mechanics.

### Reason protocol (removals)

An archiver sets, in the same transaction,
`SET LOCAL gaius.card_reason = '<category>: <why>'` and
`SET LOCAL gaius.card_actor = '<who>'`; the `cards_status_events` trigger
snapshots both. `scripts/archive_cards.py --reason …` is the sanctioned path.
Rows before the journal (2026-09-06) were backfilled from the archive TSVs
with `backfill = TRUE`.

### What counts as an answer

1. A verdict per gate: **pass | fail | error** — never *inconclusive* (a gate
   that could only be inconclusive silenced the objective for 36 h on
   2026-09-03).
2. Each FAIL names the **DAG stage** in its evidence (rule 8): acquisition
   (article_curate: goggle/reflex), selection (curate/slot picks), publishing
   (publish_cards KV sync), or the archiver.
3. The **flip set** (by analogy with the causal-chain task): the smallest
   *declared* action that restores PASS — an explained archive, a fetcher
   parameter, a slot rule — never an undeclared removal. Examples carry it as
   `output.flip`.

### Verdict classes

- **pass** — all eight gates pass.
- **fail** — any gate fails; the objective's aggregate verdict is the
  engine's standard (all pass → pass; any fail → fail; errored and none
  passed → error).
- **error** — a section's facts could not be collected; evidence says why.

## Examples

See `surface-integrity.json` (`examples[]`): A the 2026-09-01 intent miss with
mechanics green; B the 2026-09-05 stale band; C the 2026-09-06 vendor
listicles; D the 2026-09-05 archive before the journal; E the clean surface
after remediation; F an undeclared removal category; G an unreadable surface.
Example inputs scale `band` down (8) so specimens stay legible; every other
parameter is the objective's own.

## Tags
objective · public-surface · currency · integrity · conservation · adversarial-content · event-sourced · gaius
