# Commit the local backlog and push trunk

GitHub `zndx/gaius` and `zndx/gaius-acp` were already at `0dbf7b2`. The backlog was the working tree.

## Landed on trunk (`06cbf95`)

- `1fc72c9` Skip SKOS alignment until admit and extract have both succeeded. `tests/engine/test_clt_skos.py`: 19 passed.
- `4e796e0` Refresh open_inference and scheduler stubs for protobuf 6.33 and grpc 1.81. Metabase and supervision stubs are still 6.31.1.
- `0e66d19` NAM TBox head review.
- `8b4a62e` `external/semantics` → `b7e9d54` (already on `weathership/semantics` main).
- `06cbf95` `external/sdg-corpora` → `c4138b4d`.

## sdg-corpora (`c4138b4d` on `zndx/sdg-corpora` trunk)

- `24b1702d` Ignore `.owlready/`.
- `c4138b4d` Mint nine CLT prefLabels and add 83 concepts in `contrib/clt/qwen3-1.7b-20k/clt.skos.ttl`.

Pushed to `share` (`zndx/gaius`), `internal` (`zndx/gaius-acp`), and `zndx/sdg-corpora`. The raid remote `origin` (`/raid/repos/zndx-gaius`) was not updated.

## Left uncommitted

- `thirdparty/src/LuxCore` `build-helpers/make/make_deps.py`: local devenv fix that strips Nix gcc from `LD_LIBRARY_PATH` before Conan. Upstream is `LuxCoreRender/LuxCore`; the pin must stay on a commit others can fetch.
- `external/semantics` untracked Eclipse metadata under `java/iceberg-hdf5/` and `python/hdf5_iceberg/uv.lock`. That package does not track a lockfile.
- Repo-root session logs `2026-08-15-1104_process-survey` and `2026-08-24-2234_tool-calling`.
