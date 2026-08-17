# Qwen3.8 thinking TP=4 HEALTHY

Hard requirement met: `thinking` is `PROCESS_STATUS_HEALTHY` on `:8081`,
`Qwen/Qwen3.8-27B`, `max_model_len=262144`, TP=4, ~21 GiB on GPUs 0–3.

Chat completion returned `TP4OK` with a thinking trace (`reasoning_content`).
45s later the same Qwen3.8 serve was still bound; Ambient did not evict it.

## What actually blocked HEALTHY

Not CUDA 13. Tinybox stays driver 570 + toolkit 12.4 + `.devenv/nvidia-libs`.

1. **Nix python vs host CUDA frontend.** vLLM is Nix CPython (glibc 2.42).
   `cicc` / host `ninja` / host `as` are Ubuntu 22.04 ELFs (glibc 2.35).
   Devenv `LD_LIBRARY_PATH` puts Nix `libstdc++` first; host tools then die
   (`GLIBC_2.38`). Putting host `/usr/lib` on the *python* LD stack-smashes
   the Nix interpreter (exit -6).
2. **vLLM mutates LD after exec.** Sanitizer at spawn is not the last word;
   `/proc/<serve>/environ` shows profile/lib + gcc-15-lib restored.
3. **torch calls `$CUDA_HOME/bin/nvcc`**, not `PATH`.
4. After JIT succeeded: hybrid Mamba+Attention needs `--enable-prefix-caching`.
5. Once HEALTHY, Ambient `_evict_for_reasoning` requested `TaskType.REASONING`
   and the makespan scheduler started `cap_reasoning` (QwQ-32B) on `:8081`,
   stopping thinking.

## Fix

- `scripts/lib/tinybox-nvcc.sh` + `tinybox-ninja.sh`: host `PATH`/`LD` only,
  then exec real `/usr/local/cuda/bin/nvcc` and `~/.local/bin/ninja`.
- `_ensure_tinybox_cuda_home()` shadows `.devenv/tinybox-cuda` so
  `CUDA_HOME/bin/{nvcc,ninja}` are those wrappers. Guru `#EP.00000005.TINYBOXCUDA`.
- Python child LD is driver + toolkit only (no `/usr/lib`).
- `agents.conf` thinking `extra-args` includes `--enable-prefix-caching`.
- Ambient no longer begins a REASONING workload. Scheduler keeps a live
  `thinking` task for reasoning/thinking/instruct/chat.

Do **not** install CUDA 13 wheels on this box.
