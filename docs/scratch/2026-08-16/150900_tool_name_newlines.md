# Qwen XML tool names carried newlines

`use_tool` / `gaius__theta_sitrep` failed because parameter
bodies included `\n` and sitrep args sat beside `tool_name`
instead of inside `tool_input`.

Façade now strips whitespace from tool names, trims string
args, aliases sitrep names, and hoists leftover `use_tool`
keys into `tool_input`.
