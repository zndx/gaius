# Ask backends + chart peel

SPCX dump was a hallucinated `use_tool` result, not MCP. Unwrap
`use_tool` → `gaius__ask_present`. MCP POSTs and returns a short
ack (no fence). Peeler accepts `kind` and wrapped dates.

Settings: `clt-pair` (GPU4 1.7B + GPU5 CLT) or `sae-9b`
(Qwen3.5-9B-Base). Ask Complete uses `model=ask`. Thinking 0–3
untouched. Reopen Terminal after UI recycle.
