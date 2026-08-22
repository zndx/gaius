# gaius.zndx.org live on the unified graph

Public landing was KV-healthy since March with `published_count=0`.
`article_curate` (`#YK.00000005.DISK` / `#YK.00000002.NOTADMITTED`)
emptied featured `ai-reasoning-agents`; pg_cron still ran four
`publish_cards` slots/day.

Restore on devenv-797b140 (`python -m gaius.engine` PPID=devenv daemon):

1. `admit_public_inflow` from arXiv/web `content_items` (no KB paths).
2. Enrich: Brave + thinking summaries, LuxCore images, cerebras skip.
3. Gate is image + 2 summaries. Task 12981 published 3; CLI published 2.
4. Homepage top cards are 2026-08-11 arXiv (ClusterBench, SCOUT,
   Workflow Cards, QSimAdv, wearable analytics). Card pages and
   `viz.gaius.zndx.org` display.png return 200.

STP: due pickup no longer awaits LuxCore on the LISTEN loop;
`publish_cards` is a singleton; watchdog 60m for that type; admit
when **ready** count is 0 so one unenriched pending cannot starve
inflow.
