# Live engine after the federation recycle

`signals.target` was recycled on 2026-10-12 00:49–00:52 UTC. The Gaius
unit entered at 00:51:21 UTC from this tree (`8744576`), so the running
engine has `declare_decisions_handover`. Thinking is
`PROCESS_STATUS_HEALTHY` on :8081 (GPUs 0–3). GPUs 4 and 5 are free.
Hermes restarted onto signals-plugins `540600a`; its supervisor is
listening on :5081 and the moshi worker is not holding a GPU.

`/decide` was not probed. No d3 replica was started.
