# decisions is thinking + dual-d3-flash

The capability token stays `decisions`. That is the name a Metaflow
workload requests. On Gaius the request means Qwen3.8-27B stays on vLLM
on the heavy YuniKorn queue, and two `vllm-sr/d3-flash` replicas
(`d3-flash-0`, `d3-flash-1`) fill the light queue.

The replicas are not `vllm serve`. Each one runs the checkpoint's
`d3_server.py` on a side interpreter (`GAIUS_D3_PYTHON` or
`.devenv/d3-runtime/bin/python` from `scripts/d3_runtime_venv.sh`). The
product vLLM pin stays 0.27.1. The HTTP body is `{model, state, questions}`
on `POST /v1/systemone`. Instructions are folded into a string state. A
non-empty `cache_salt` is `#EP.00000024.BADDECISION`. A missing side
interpreter is `#EP.00000025.D3RUNTIME`.

`Engine/Decide` round-robins the two replicas and fails over only on a
transport error or HTTP 503. It does not fall back to thinking and it
does not start the replicas. A workload that requires `decisions` keeps
or starts thinking, stops embedding and CLT for the light seats, and
restores them when the workload completes. Thinking is not stopped at
the end.

Not done in this change: the side venv was not installed, the
`vllm-sr/d3-flash` snapshot was not downloaded, and the live engine was
not restarted. `gaius-cli /decide` against the process on `:50051`
returned `UNIMPLEMENTED` because that process does not have this tree
yet. Loading it is a later restart, and starting the replicas takes
both light seats.
