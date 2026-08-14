# Yield for article_curate and prospects_update

Spawned Metaflow children are now `Engine/Yield` targets.

- `workload_id` = `{article-curate|prospects-update}-{task.id}`
- Yield SIGTERMs the subprocess; Iceberg/DB cursors remain the resume SoR
- Best-effort sentinel pod on `root.gaius` (`GAIUS_FLOW_SENTINEL=0` to skip)
- C2 last-gasp → Signals C2 → gRPC Yield on `:50051`

Signals protocol pin in `external/signals-protocol` has local Yield proto
until the shared submodule is bumped to the Signals commit that landed Yield.
