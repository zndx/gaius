# gaius.zndx.org publish since March

Landing KV was healthy four times a day with `published_count=0`. Featured
`ai-reasoning-agents` had **zero pending**; 20 pending cards sat on
non-featured `ai-keiretsu`. `article_curate` failed (`#YK.00000005.DISK`,
then `#YK.00000002.NOTADMITTED`) so no new public cards since 14 Mar.

`publish_cards` now admits recent public feed URLs (arXiv/web, no KB
paths) into the featured collection when pending is empty, enriches, then
publishes. Empty publish is `#COL.00000015.NOINFLOW` /
`#COL.00000016.NOENRICH`, not a silent KV-success.
