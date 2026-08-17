# Cognition Buffer: scratchpad + attention schema

Supersedes `043000_cognition_attention_schema.md` (that note treated
the buffer *as* the schema and discarded merge content).

Two layers, one RAM object (`gaius.engine.services.cognition_buffer`):

1. **Scratchpad** — merge of Ambient + Prospects, full content, token
   budget 196608 / 262144. Always-on context for the next question.
   Instantaneous decisions start here, not from a from-zero search.
2. **Attention schema** — layered *on* that scratchpad. Vocabulary from
   `external/sdg-corpora`. Membrane from `external/sdg-strategy`.
   Informs `compact()` (budget eviction by keep-score, not FIFO).

Harvest admission (strategy) is **threshold**. Scratchpad compaction is
**budget** — enlarging what is attended can evict a previous keep.
Those regimes are not interchangeable.

The schema's *form* will be refined. What it *does* (steer continuous
cognition) and *where it lives* (on this buffer) are the fixed claims.

The next-question space is **decision-conditioned**: see
`045550_decision_situated_scratchpad.md`.
