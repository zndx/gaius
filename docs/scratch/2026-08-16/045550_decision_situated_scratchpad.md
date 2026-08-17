# Next-question space is decision-conditioned

The Cognition Buffer is a *universal* agent context, continuously
optimized for one next question out of an open generative space.

The caveat that makes that tractable: answers inform **decisions**.
That is not true-infinite thinking. Given **where** the user is and
**what they are doing**, the live set is the questions whose answers
could change a move *here*.

`DecisionSituation(where, doing, decide)` sits on the scratchpad.
`situate()` re-compacts under that prior. Vacant situation = no such
constraint (worse compaction). Token overlap is a first crude prior,
not a model of the decision — the design itself is a research topic.

Continuous compaction is readiness, not session trim: it holds
`NEXT_QUESTION_RESERVE_TOKENS` (65536) empty for **one next question**
that can arrive at any hour. It does not make room for a conversation
or a coding session.
