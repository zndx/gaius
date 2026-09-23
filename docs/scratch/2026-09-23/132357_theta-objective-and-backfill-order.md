# Wait for the week; two pivots

No backfill today. W39 proceeds on the Monday 06:00 cycle. Row 23 (2026-W38)
is one point. The next natural consolidation is the second point, and that
pair is a trajectory. Do not open this week as an out-of-band LIGHT occupancy.

Backfill order, when a missed week is remediated: start at the earliest UTC
day of the most recent week and walk each daily increment toward the present.
That approximates the whole-week consolidation. Latest-first does not.
`scripts/theta_backfill.py` in Signals now defaults to that order
(`--latest-first` keeps the old one).

Core objective: converge to the best OWL-grounded SKOS-in-Qdrant aperture
for the week-or-longer timeframe under consolidation, and remain effective
when that aperture is backtested on the accumulated corpus. Novel pairs, the
0.8 gate, BERTSubs MRR/Hits, and `documents_augmented` are process artifacts.
They are in service of the objective and are likely to be retired for
measures of ontology efficacy.
