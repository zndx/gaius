# 2026-W38 first finished consolidation — observation, not a verdict

Airflow run `theta_w38_retry5_20260922` (task 54070, Metaflow 7533) completed.
Ledger row 23 is `completed` for slice `2026-W38`. That means the procedure
ran to the end. It does not mean Theta worked. Success is still undefined;
Aegir's aperture is the reference that already works.

What the row holds:

- windows: 2026-09-14 through 2026-09-20
- `n_encoded=228`, `item_groundings=114`
- `documents_augmented=0`, `candidates_evaluated=0`, `candidates_selected=0`
  (those columns were not filled; the log is the record)

What infer logged:

- 64 novel CLT pairs, none at or above the 0.8 confidence gate
- DeepOnto, untuned, scored its own 5% TBox holdout (1657 train / 87 valid
  subsumptions, `do_fine_tune=false`, `bert-base-uncased`) at
  MRR 0.255, Hits@1 0.126, Hits@5 0.356, Hits@10 0.575
- that holdout score is not a score of the 64 pairs

Next refinement is empirical: what a useful threshold, a fine-tune, or a
different scorer would do to those 64 pairs. Do not treat row 23 as current.
