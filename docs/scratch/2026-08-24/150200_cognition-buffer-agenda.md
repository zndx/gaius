# Cognition buffer + agenda (no toy Completes)

Ambient baseline toys (fibonacci, hash table, …) are retired. Cycle health
is **thinking synthesis** of Publishing + Prospects + Ambient slices.

- `cognition_buffer`: slices + synthesis text, `episode_id`, `hx_generation_id`
- `agenda_entries`: brief / reminder / session
- HX `llm.generations` (`summary_type=cognition_synthesis`) holds prompt,
  output, and thinking_trace (HX Iceberg, not Kudu gpu_metrics)

X bookmarks are not in this loop. Engine recycle required to pick up Ambient.
