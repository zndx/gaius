# Recycle when enhancements land

Landed engine/Ambient/Prospects/FDW code must be brought into service
**as soon as it is committed**, even if that recycles thinking vLLM or
other GPU work. Existing inference is not a reason to leave a stale
Python process running.

- Recycle the owning process (`gaius-engine` / `signals` as appropriate).
- Engine start always `gpu_cleanup` — do not skip because `:8081` was up.
- Thinking down is `#AMB.00000014.NOHEALTHY` until HEALTHY again.
- Do **not** wait for a quiet GPU window to pick up buffer compaction,
  HN Firebase, Brave follow-through, or synthesis.
