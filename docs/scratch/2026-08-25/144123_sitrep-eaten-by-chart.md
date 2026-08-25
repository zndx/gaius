# A sitrep vanished behind a failed follow-up chart

Reported: asking the Web Terminal "good morning! sitrep please" answered with

```text
FMP API error: HTTP 402 - Premium Query Parameter: 'Special Endpoint :
This value set for 'symbol' is not available under your current subscription
  Guru Meditation: #FMP.00000003.HTTPERR
```

Two independent problems were in play. The FMP subscription is the operator's
to sort out; the wiring is ours.

## First: the endpoint was wedged (separate, already cleared)

`:8081` was bound but not serving — `/health` silent for 15s, GPUs holding
memory at **0% utilisation**, workers spinning at 86-88% CPU, EngineCore in
`futex_wait_queue`, and **18 CLOSE-WAIT** sockets against 4 established. Any
request would have hung. Cleared by restarting the engine, which owns vLLM's
lifecycle.

`/health fix endpoints` could not touch it: it returned
`#GR.00000001.ENGINEOFF — Request Orchestrator.status timed out`, because it
diagnoses *through* the orchestrator and a wedged endpoint is what blocks the
orchestrator. The auto-restart path exists and is enabled
(`consecutive_failures >= 3` → `_maybe_restart_endpoint`) but did not fire in
~7 hours. Why is unknown — restoring service destroyed the live evidence.

## Second: the chart branch discarded the answer

The turn actually **succeeded**. From the session history:

```text
tool_result :: {"success": true, "ascii_format": "… GAIUS SITUATION REPORT …"}
reasoning   :: …
assistant   :: FMP API error: HTTP 402 …
```

`gaius__theta_sitrep` returned a full report. Then the assistant message became
the FMP error — with no intervening tool_result, so the façade made that FMP
call itself, not the harness.

The model had emitted an OHLC artifact fence alongside its answer (SLB.PA — a
prospects candidate). `parse_ohlc_spec` picked it up, and:

```rust
if let Some(ohlc) = ohlc {
    emit_turn(&tx, &ctx, &out, pin_est, &reasoning, "", &calls).await;  // content = ""
    apply_chart(&tx, &ctx, &state.artifacts, &ohlc).await;
}
```

`emit_turn`'s third argument is the visible channel. Passing `""` threw away
the report the model had already written; `apply_chart` then streamed the raw
provider error as the only visible content. A **follow-up** chart replaced the
**primary** answer, and its failure became the answer. The agenda-write branch
had the same shape.

`""` was not arbitrary — the raw text still holds the `:::gaius-artifact`
fence, which the reader must not see. The fix strips the fence instead of
blanking the turn:

- `ask_write::strip_artifact_fences` drops `:::gaius-artifact … :::` blocks and
  keeps the prose around them (unterminated fence → drop the tail rather than
  leak JSON).
- Both branches now emit `visible_completion(strip_artifact_fences(&stripped),
  &reasoning)`.
- `apply_chart`'s error is demoted to an italic aside naming the symbol, rather
  than dumped as the answer.

## Verified

Forcing the fence path with a symbol that fails resolution:

```text
content : "System status is HEALTHY with 6 GPUs and 1 endpoint."
progress: "Fetching SLB.PA EOD…"
content : "\n\n_Chart for SLB.PA unavailable — No ticker for 'SLB.PA'. …_\n"
finish  : stop
```

The answer survives; the failure is subordinate. Before, the first chunk was
`""`.

Sitrep itself was never broken — with the endpoint healthy, "sitrep" and
"good morning! sitrep please" both route to `gaius__theta_sitrep`, the façade
unwraps `use_tool` correctly, and the report renders:

```text
model  → use_tool {"tool_name":"gaius__theta_sitrep","tool_input":{"horizon":"open"}}
façade → gaius__theta_sitrep {"horizon":"open"}   finish_reason=tool_calls
turn 2 → "Good morning! Here's your sitrep:" + GAIUS SITUATION REPORT
```

An earlier worry that yesterday's `tools[]` change made `gaius__*` names
unemittable under structural-tag constraints was wrong: the model routes
through the declared `use_tool`, which is in the harness roster.

`cargo test` 57 passed; `tests/engine/` 692 passed (same two pre-existing
`test_gaius_servicer.py::TestComplete` failures).

## Still open

- Nothing recovers a wedged endpoint. A watchdog probing the endpoint directly,
  rather than via the orchestrator RPC, would close that loop.
- `devenv processes restart gaius-engine` no-op'd twice reporting `Phase: ready`,
  then raced its own shutdown into `#EN.00000014.DUALBIND` and left the engine
  down until restarted again.
