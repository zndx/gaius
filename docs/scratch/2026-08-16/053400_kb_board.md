# Board = live KB (Iceberg migration in view)

`current_state` / Qdrant were empty; the knowledge base was not
(6k+ markdown, 2070 `content_items`, 1455 with `iceberg_id`).

`/board refresh` walks `build/dev/{current,scratch,archive}`, joins
HX Iceberg ids, places notes by path topology (`kb_topology`), and
publishes `current_state` so the TUI 19×19 and `gaius-ui` show
occupancy. UMAP/Ricci still come from `/reindex` when embeddings
exist — this path will not overwrite a live UMAP snapshot.

Iceberg is the HX warehouse (`s3://zndx-gaius/hx/`, migrating with
the rest of the lake). The board reports coverage; it does not
invent a second catalog.
