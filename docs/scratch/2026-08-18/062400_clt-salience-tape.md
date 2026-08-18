# CLT salience tape — 2026-08-18

Stopped 27B preload (`preload-endpoints = []`). Thinking decode at
~450 W / 0.7 % KV was not a corpus.

CLT import: shim `HF_HUB_ENABLE_HF_TRANSFER` for huggingface_hub 1.27.
`feature_tape` + pg_cron `feature-probe` every 5 min. Kind `clt-probe`
on YK light, GPU 4, disk floor `/raid` only.

Discover Popular chips now include `kind=feature` once rows exist.
