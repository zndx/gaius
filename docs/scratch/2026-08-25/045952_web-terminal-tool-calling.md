# Web Terminal keeps its turn once tool calling is on

Follow-on to `docs/scratch/2026-08-25/040739_qwen38-tool-calling.md`, which
enabled `--enable-auto-tool-choice --tool-call-parser qwen3_coder` on the
thinking endpoint. That change stopped Web Terminal turns after one step.

## Symptom

Session `01a03726` (04:21) asked "can you identify what port vllm with Qwen3.8
is running on?". Grok showed a think trace ending "Let me use the terminal to
check.", then the turn ended. No tool ran. `chat_history.jsonl` records a
`reasoning` entry and an `assistant` entry holding the reasoning text — and no
`tool_calls`. The prior session `01a036e6` (03:12, before the flags) had run
`run_terminal_command` fine under `tool_call_id=gaius-call-0`.

## Cause

`qwen3_coder` resolves to `Qwen3EngineToolParser` (`structural_tag_model =
"qwen_3_coder"`), an **engine-level** parser. It consumes `<tool_call>` markup
out of the model's output before serving. When the request declares no
`tools[]`, the extracted calls are then discarded — content comes back empty.

Reproduced directly against `:8081` with a system prompt that demanded the
markup and no `tools[]` in the request:

```text
finish_reason: stop
content_len 0
HAS <tool_call>: False
tool_calls: None
reasoning: "The user wants to identify the port ... I'll use run_terminal_command ..."
```

The façade then promoted the reasoning as the visible answer
(`visible_completion`), which reads as a finished turn.

The gaius-ui façade had been dropping the harness `tools[]` on the floor:
`ChatRequest.tools` was parsed but never used, and `tool_roster` — the old
prompt-side name list — was `#[allow(dead_code)]`. The `<tool_call>` channel
worked only because Qwen imitated the format unprompted. The engine parser
closed that channel.

Same request **with** `tools[]` declared:

```text
finish_reason: tool_calls
reasoning: "The user wants to identify the port ... Let's check the running processes and ports."
tool_calls: run_terminal_command {"command": "ps aux | grep -i vllm | grep -v grep"}
            run_terminal_command {"command": "ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null"}
```

Thinking and parallel calls both survive. There is no way back to the
prompt-markup channel while the engine parser is on — the tools must be
declared.

## Change

`tools[]` now travels the whole path, and native `tool_calls` come back as the
`<tool_call>` markup the façade already knows how to parse.

| Layer | File | Change |
|---|---|---|
| Proto | `signals-protocol .../engine.proto` | `CompleteRequest.tools_json = 9`, `tool_choice = 10` |
| Façade | `openai.rs` | `tools_json()` / `tool_choice_str()`; both threaded through `stream_complete` → `complete_ticked`; dead `tool_roster` removed |
| Façade | `engine.rs` | `CompleteExtras { timezone, clock_json, tools_json, tool_choice }`; `CompleteOut.finish_reason` |
| Engine | `zndx_engine_servicer.py` | parse `tools_json` → `extra_body {tools, tool_choice}`; `normalize_tool_choice`; real `finish_reason` |
| Engine | `vllm_controller.py` | `VLLMProcess.supports_tool_calls`; tools gate; `parse_qwen_tool_call_markup` |
| Engine | `backend_router.py` | `InferenceResponse.finish_reason` |
| Client | `flows/lattice.py` | `complete(tools=…, tool_choice=…)` |
| CLI | `cli.py` | `/engine complete`, `/engine toolcall [auto\|required\|none]` |

### tool_choice

Empty means `auto` — the right default for an agent loop. `required` and
`none` pass through, as does a named-tool JSON object. `required` forces a
call on **every** turn, so a harness using it never reaches a final text
answer; the caller owns that loop. Grok-build sends no `tool_choice`, so the
Web Terminal runs on `auto`.

### Which capabilities get tools

Only the Terminal capability. Ask runs on `interpretable` / `ask-sae`, whose
endpoints are launched without `--enable-auto-tool-choice` and which have no
tool harness (they answer in artifact fences). The façade gates on
`is_small_ask`, and the controller fails fast if tools reach an endpoint that
cannot serve them:

```text
#VLLM.00000004.NOTOOLCALL
Endpoint interpretable (Qwen/Qwen3-1.7B :8090) was launched without
--enable-auto-tool-choice, so it cannot serve tools[].
```

`supports_tool_calls` is read off the assembled serve argv at launch, so it
covers `extra-args`, per-endpoint flags and `serve_command` overrides alike,
and defaults closed.

### finish_reason is now real

The servicer used to hardcode `finish_reason="stop"`. It now reports what vLLM
returned. `flows/lattice.complete()` already raised `#EP.00000017.TRUNCATED` on
`length` — that guard was dead and is now live, so a Metaflow step whose
Complete is truncated fails instead of accepting a partial answer.

## Guru codes added

| Code | Meaning |
|---|---|
| `#GR.00000010.TOOLSCHEMA` | `tools_json` and `json_schema` both set — guided_json disables thinking and suppresses tool_calls |
| `#GR.00000011.TOOLSJSON` | `tools_json` is not a non-empty JSON array |
| `#GR.00000012.TOOLCHOICE` | `tool_choice` is not auto/required/none/named-tool JSON |
| `#VLLM.00000004.NOTOOLCALL` | tools[] sent to an endpoint launched without `--enable-auto-tool-choice` |

## Incidental repairs

Two files were syntactically broken on trunk and could not be imported:

- `engine/services/ask_present.py:66` — `-> list[Any]::` (double colon). Broke
  `tests/engine/test_ask_present.py` collection, which blocked the whole
  `tests/engine/` run.
- `engine/backends/colpali_controller.py` — commit `6aef4dc` replaced the
  module docstring but left the previous one's body orphaned after the closing
  quotes, with a stray `"""` behind it. `uv run python -m compileall -q src/gaius`
  is clean now.

`tests/engine/test_gaius_servicer.py::TestComplete::{test_complete_success,
test_complete_uses_default_agent}` fail on trunk before these changes too —
untouched here.

## Restart surface — back on devenv

The previous session restarted the engine by `kill -TERM` on the pid. The
devenv daemon respawned it, but process-compose bookkeeping never caught up:

```text
$ devenv processes list
gaius-engine                   stopped   restarts: 0     # child of the devenv daemon, running
gaius-ui                       gave_up   restarts: 5     # binary running unmanaged
metabase                       starting  restarts: 647
minio / postgres / prometheus / qdrant / opentelemetry-collector   gave_up
```

`devenv processes restart gaius-engine` no-ops against a `stopped`/`gave_up`
phase, which is why that path appeared broken. This deploy went through the
unit instead:

```bash
sudo systemctl restart gaius.service
```

`systemd_stop.sh` runs `just down` and reaps this checkout's compose
leftovers; `systemd_start.sh` runs `devenv up -d` and waits for the
compose-owned `Engine/Status` on `:50051`. systemd and a login-shell
`devenv processes` are the same graph — see
`docs/current/src/operations/peer-unit.md`. Do not `kill` engine pids; it
desyncs that graph.

## Verified

Deployed via `sudo systemctl restart gaius.service`; thinking reloaded on
GPUs 0–3 with the tool-calling flags. `/gpu status` →
`thinking PROCESS_STATUS_HEALTHY 8081 Qwen/Qwen3.8-27B`.

CLI gate (`zndx.engine.v1.Engine/Complete`, thinking on throughout):

| Command | finish_reason | calls |
|---|---|---|
| `/engine toolcall` (auto) | `tool_calls` | 2 × `run_terminal_command` |
| `/engine toolcall required` | `tool_calls` | 2 × `run_terminal_command` |
| `/engine complete "…capital of France?"` | `stop` | 0 — "The capital of France is Paris." |

Web Terminal path (`POST :9890/v1/chat/completions`), replaying the exact
question that stalled — "can you identify what port vllm with Qwen3.8 is
running on?":

| Turn | Input | Result |
|---|---|---|
| 1 | user question + 3 tools | `finish_reason=tool_calls`, 2 OpenAI `tool_calls` |
| 2 | + assistant call + `role:tool` result | reads the result, concludes 8081, calls once more to verify |
| 3 | + second tool result, "no more tool calls" | `finish_reason=stop`, 0 calls, final prose answer |

Streaming (`stream:true`, the shape grok-build uses) emits the same two calls
as SSE `delta.tool_calls` deltas and closes with `finish_reason=tool_calls`
then `[DONE]`.

Ask (`model:"ask"`) with tools attached returns prose and `finish_reason=stop`
— `tools_chars=0` in the façade log confirms they were not forwarded to the
1.7B endpoint, which would have 400'd.

### Live harness traffic

A real Grok Build session ran through the new path while verifying:

```text
model="thinking" system_chars=6655 prompt_chars=3730 tools_chars=36581 tool_choice=auto stream=true
model="thinking" system_chars=6655 prompt_chars=3833 tools_chars=36581 ...
model="thinking" system_chars=6655 prompt_chars=3905 tools_chars=36581 ...
model="thinking" system_chars=6655 prompt_chars=3977 tools_chars=36581 ...
model="thinking" system_chars=6655 prompt_chars=4125 tools_chars=36581 ...
```

The harness roster is 24 tools / ~36 KB — comfortable against a 262 K window.
`prompt_chars` climbing across turns is the transcript accumulating, i.e. the
discussion continuing. Zero
`"finished on tool_calls but no <tool_call> survived"` warnings.

### Suites

`uv run pytest tests/engine/ -q` → 674 passed, plus 33 new
(`test_vllm_tool_calls.py`, `TestCompleteToolCalling`).
`cargo test --release` (gaius-ui) → 48 passed.
Pre-existing, untouched: `test_gaius_servicer.py::TestComplete::
{test_complete_success,test_complete_uses_default_agent}`.
