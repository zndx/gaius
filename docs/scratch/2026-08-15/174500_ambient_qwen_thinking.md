# Ambient default-on + Qwen3.8 thinking

- Ambient starts on engine boot unless `/ambient stop` (operator-disabled).
- YK Yield pauses GPU think-summarize; RAM FIFO stays.
- `instruct` / `fast` → `Qwen/Qwen3.8-27B` capabilities `[thinking, vision]`.
- Olmo alias is `open-thinking` (full model flow is public).
- Thinking is a request mode on instruct, not a GPU swap.
- Airflow / cron-drift / Metaflow-on-Airflow still deferred.
