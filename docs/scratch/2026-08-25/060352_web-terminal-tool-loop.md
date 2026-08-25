# Web Terminal looped on every tool call

Follow-on to `045952_web-terminal-tool-calling.md`. With tools[] plumbed the
turn no longer *ends* after one step — it repeats instead. The model runs a
command, the output shows up in its thinking, and it runs the command again.

## Cause: the transcript never survived the trip

`flatten_messages` collapses the whole conversation into one prompt string,
then `ask_write::thinking_complete_prompt` narrows it:

```rust
for line in flattened.lines() {
    if line.starts_with("Assistant:") || line.starts_with("Tool result") {
        tail.push_str(line);
```

Two things are lost, both silently:

1. **Every tool result is truncated to its first line.** The result is pushed
   as one `Tool result (id): <text>` block, but `.lines()` splits it and only
   the first line still starts with `Tool result`. A six-line `ps aux` reaches
   the model as one line. So does `read_file`, `grep`, `ls`, a test run.
2. **The `Assistant tool_calls:` line is dropped** — it starts with
   `"Assistant tool_calls"`, not `"Assistant:"`. The model never learns which
   call produced the fragment it is looking at.

That comment on the function — *"Dropping tool results caused Complete to
re-issue fmp_search forever"* — is the same bug, patched once at the line
level. Keeping the first line was not enough.

The model sees a question, an empty `Assistant:`, and one orphaned line. It
cannot tell the work is done, so it runs the command again — and the next
result is truncated the same way. Nothing accumulates. It never finishes.

## Reproduced, both directions

Same live endpoint, same tools[], same question — one whose answer is on
lines 3-6 of `ps`, not line 1:

> How many VLLM::Worker_TP processes are running, and what are their PIDs?

**Old flattened path** — 8 turns, 8 calls, only 4 distinct, no answer:

```text
turn 1  $ ps aux | grep -i "VLLM::Worker_TP"                 full=5 lines -> model sees 1
turn 2  $ ps -eo pid,ppid,pcpu,pmem,etime,comm,args | grep …  full=5 lines -> model sees 1
turn 3  $ ps -eo pid,ppid,pcpu,pmem,etime,comm,args | grep …  <-- REPEAT
turn 4  $ ps -eo pid,ppid,stat,etime,comm,args | grep …        full=5 lines -> model sees 1
…
turn 8  $ ps -eo pid,ppid,pcpu,pmem,etime,comm,args | grep …  <-- REPEAT
DID NOT CONVERGE in 8 turns; 8 calls, 4 distinct
```

**Structured path** — converged in 3 turns with the whole answer:

```text
turn 1  $ ps -eo pid,ppid,cmd | grep -i "VLLM::Worker_TP"     -> 4 lines
turn 2  $ ps -eo pid,ppid,cmd | grep -i "worker_tp"; …         -> 11 lines
turn 3  finish=stop, 0 calls
        4 VLLM::Worker_TP processes, PIDs 929774-929777,
        children of VLLM::EngineCore (928226) — one per TP shard.
```

Worth noting: the original "what port is vLLM on" question converged on *both*
paths, because `--port 8081` happens to sit on line 1 of `ps aux`. Truncation
only bites when the answer is not on the first line — which is most of the
time, and is why the loop looked intermittent.

## Change

`CompleteRequest.messages_json = 11` carries the real OpenAI `messages[]`, and
the engine hands them to vLLM verbatim so the chat template renders
`<tool_call>` assistant turns and `<tool_response>` tool turns the way the
model was trained to read them.

| Layer | Change |
|---|---|
| Proto | `CompleteRequest.messages_json = 11` |
| `openai.rs` | `harness_messages()` rebuilds the turns with the composed system prompt leading; `has_tool_turns()`; `structured` gate |
| `engine.rs` | `CompleteExtras.messages_json` |
| `zndx_engine_servicer.py` | `parse_messages_json` — validates roles and that every tool turn carries a `tool_call_id` |
| `backend_router.py` | `complete(messages=…)` used verbatim instead of the system/prompt pair |

A tool turn with no `tool_call_id` is dropped by the façade and rejected by the
engine (`#GR.00000013.MESSAGES`): the template cannot pair it with the call it
answers, and an unpaired result is exactly what caused this.

Ask is untouched — `structured` is gated on `!is_small_ask`. Ask has no tool
harness, so its transcript flattens without loss.

The heartbeat's token estimate now measures the transcript actually being
sent rather than the narrowed prompt.

`flattening_truncates_multiline_tool_results` pins the old behaviour as a
test, so the regression cannot come back quietly.

## Suites

`tests/engine/` 682 passed; `cargo test --release` 52 passed. Still failing
from before and untouched: `test_gaius_servicer.py::TestComplete::
{test_complete_success,test_complete_uses_default_agent}`.
