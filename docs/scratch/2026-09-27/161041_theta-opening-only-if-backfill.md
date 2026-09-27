# Theta opening signal only if the week is a backfill

Week 38 is already a completed ledger row. A backfill now would not clear Ripley's opening: the line was the missing `scheduled_tasks` hub tick, which the 22 September success never booked, not a missing week. Re-running the week would also not make `documents_augmented` non-zero.

The session opening announces Theta only when the previous ISO week has no completed ledger row, after the Monday admission window. A caught-up week is not a backfill, so a missing hub row is not that signal.
