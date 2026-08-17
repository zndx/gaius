# Qwen3.8-27B via thinking; instruct is an alias

ColBERT-Zero removed `colpali-engine`, which unblocked transformers 5.x
and a vLLM that understands `Qwen3_5ForConditionalGeneration`.

## Capability name

The preload / empty-alias / Ambient request is **`thinking`**
(`Qwen/Qwen3.8-27B`, capabilities `[thinking, vision]`).
`instruct` is only a resolve alias (`require_agent`) so leftover callers
start the same process, not a second 4-GPU endpoint.

## vLLM

- Pin `vllm>=0.27.0` (lock: **0.27.1**). 0.12 cannot load qwen3_5.
- Recipe flags: `--reasoning-parser qwen3` plus
  `--default-chat-template-kwargs` (thinking on by default).
- Lock constraints for this host:
  - `environments`: linux x86_64 only
  - drop `cuml-cu12` from core (numba pin vs vLLM 0.65)
  - override `torch==2.13.0` (pylate/fast-plaid pins older torch;
    we encode with `pylate.models.ColBERT`, no PLAID index)
  - override `xgrammar==0.2.3` (0.2.4 has no cp312 manylinux x86_64 wheel)
  - tinybox CUDA: `.devenv/nvidia-libs` + `/usr/local/cuda` (12.4 toolkit).
    Re-run `.devenv/setup-nvidia-libs.sh` after a driver bump. Do not
    take default cu130 wheels. Test torch with that LD_LIBRARY_PATH.
    Pin torch/vision/audio/codec to `+cu129` (libcudart.so.12).
    vLLM 0.27 `--swap-space` is `--kv-offloading-size`.

## Ambient

Summarize already calls `agent_alias="thinking"` with
`enable_thinking=True`.
