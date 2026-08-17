# Harness was on Qwen; identity was still Grok

`record_assistant_response model_id=Qwen/Qwen3.8-27B` on
`http://127.0.0.1:9890/v1`. The grok-build-plan template starts
`You are Grok released by xAI`, so Qwen answered as Grok.

Façade now rewrites that identity and appends Engine/Complete
(Qwen3.8-27B). Config sets `[agent] system_prompt_label`.
