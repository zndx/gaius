# Qwen3.8-27B vLLM tool calling on :8081

thinking (`Qwen/Qwen3.8-27B`, port 8081) was healthy but vLLM was
not started with tool calling. `tool_choice=auto` returned 400:

```
"auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser to be set
```

The live serve line had `--reasoning-parser qwen3` only.

## Change

`config/agents.conf` thinking `extra-args` (and `QWEN38_27B` registry
`VLLMConfig`) now include the vLLM 0.27 recipe flags:

```
--enable-auto-tool-choice --tool-call-parser qwen3_coder
```

Engine reloaded `agents.conf` and preloaded thinking. New serve line
includes those flags. `/gpu status` → `PROCESS_STATUS_HEALTHY` on 8081.

## Verify

1. thinking off, `tool_choice=auto` → `finish_reason=tool_calls`,
   `get_weather({"city":"Paris"})`.
2. default thinking on, `tool_choice=required` → same, plus
   `reasoning` text, `get_weather({"city":"Tokyo"})`.
