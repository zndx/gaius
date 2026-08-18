# HuggingFace cache = Aegir HF_HOME

Canonical: `HF_HOME=/raid/cache/huggingface` → repos in `$HF_HOME/hub`.
Do not set `HF_HUB_CACHE`. Aegir already uses this; Gaius had forked
`/raid/cache/rch/huggingface` (481 G).

## Done

- Symlink `hub/models--bluelightai--clt-qwen3-1.7b-base-20k` →
  existing 41 G Aegir tree (28 feature-label bins).
- `mv` unique first-party weights rch → hub (same filesystem):
  `Qwen3-1.7B` 3.8 G, `Qwen3.8-27B` 52 G, `bert-base-uncased` 421 M.
- CLT worker and `download_clt_models.py` drop `HF_HUB_CACHE` /
  `HUGGINGFACE_HUB_CACHE` so they cannot write a second tree.

## Left in rch (safe to delete after unsetting the env)

~425 G: 21 duplicate repos already in hub, plus ~50 empty stub
`models--*` (20 K each) and stray datasets. Not moved into the
shared cache on purpose.

Unset `HF_HUB_CACHE` in the shell / devenv that injected
`/raid/cache/rch/huggingface`. Then `rm -rf /raid/cache/rch/huggingface`
reclaims the duplicates.
