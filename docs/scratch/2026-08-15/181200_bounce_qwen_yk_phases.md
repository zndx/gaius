# Bounce + YK phases

`gaius.service` recycled. Ambient auto-started; `gaius-ambient` on
`root.internal.compute` with `federation.phase=buffer`.

Instruct `Qwen/Qwen3.8-27B` advertised `capabilities=[thinking,vision]`
then failed: **vLLM 0.12.0 has no `Qwen3_5ForConditionalGeneration`**.
Latest vLLM on PyPI is 0.27.1 — pin bump is a separate cut.
`transformers` overridden to 5.15.0 (colpali still wants `<4.58`).

Phases: buffer=compute/no GPU; summarize+compact bind the one extract
token so Ægir fine-tune preempts a single claim.
