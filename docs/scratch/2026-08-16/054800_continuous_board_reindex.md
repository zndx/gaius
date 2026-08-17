# Board reindex is continuous; the UI is current by tautology

`current_state` is the board. A pg_cron `board-reindex` job (`* * * * *`)
inserts `scheduled_tasks.board_reindex` when the last cycle is older than
60s and none is pending. The engine handler republishes KB topology +
Iceberg coverage. Catch-up on engine start so a recycle is not a blank
grid.

`/board` reads that row. `/board refresh` is only a kick. Ricci/UMAP
still come from `/reindex` when embeddings exist and will not be
overwritten by topology.
