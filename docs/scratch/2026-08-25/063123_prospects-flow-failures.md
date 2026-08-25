# Prospects update: two regressions, one silent report

The Agenda note `2026-08-25-040628_prospects-update.md` said only:

> Prospects update failed. Symbols: MTN, LLY, DIS, SLB, INTC, CHTR, XOM.
> No new filing count — nothing to book.

Every prospects run since 2026-08-20 has failed. The daily notes never said
why, because of a third bug in how a failure is reported.

| Date | Note |
|---|---|
| 08-17, 08-18 | completed |
| 08-19 | yielded |
| 08-20 … 08-25 | failed |

## 1. The spawner forced the wrong Metaflow profile

`efaf524` (2026-08-20) changed the generic flow spawner:

```python
-        env = metaflow_child_env()
+        env = metaflow_child_env(mode="local")
```

It fixed a real problem — NOTIFY children inherited `GAIUS_METAFLOW_MODE=platform`
and hung on the `@kubernetes` / S3 step. But it applied to *every*
sentinel-spawned flow, and `ProspectsUpdateFlow.start()` opens with
`require_signals_metaflow()`, which fail-fasts on exactly that:

```text
PlatformMetaflowError: #MF.00000006.NOPLATFORM Prospects uses the Signals
Metaflow datastore, not a Gaius-local one. METAFLOW_DEFAULT_DATASTORE='local'.
```

Prospects is the **only** flow that calls `require_signals_metaflow()`, and it
has no `@kubernetes` steps — only plain `@step` — so the hang `efaf524` was
avoiding does not apply to it. The mode is now per-call, still defaulting to
`local`, with prospects opting into `platform`.

The platform datastore is healthy: metadata service `:30180` pings 200, RustFS
`:9010` serves the `metaflow` bucket, credentials resolve.

## 2. `gpu_tokens` read off the class, not the instance

With the profile fixed, `start` got further and hit a second, unrelated fault:

```text
File "gaius/flows/base.py", line 211, in _claim_yk
  tokens = int(getattr(type(self), "gpu_tokens", 0) or 0)
TypeError: int() argument must be a string, a bytes-like object or a real
number, not 'property'
```

`611385e` (2026-08-24) introduced that class-level read. Metaflow installs a
`property` on the running flow class for every inherited class attribute, so
the class lookup returns the descriptor rather than the value. Probed directly:

```text
PROBE type(self) = ProbeFlow
PROBE class lookup   = <property object at 0x…>   property
PROBE instance lookup = 0
PROBE defined in ProbeFlow -> <property object …>   # injected, shadows the base
PROBE defined in Base     -> 0
```

The instance read resolves correctly, including to a subclass's own value — a
flow declaring `gpu_tokens = 1` reads back `1`, so the YK queue-class check
still gates.

**This one was not prospects-specific.** Every flow reaching
`emit_lineage_start` broke on 08-24:

| task_type | 08-23 | 08-24 | 08-25 |
|---|---|---|---|
| clt_skos_admit + clt_skos_label | 141 completed, 1 failed | 112 completed, 46 failed | **0 completed, 50 failed** |

Their captured tails carry the identical `TypeError … not 'property'`.

## 3. A failed run reported itself as a benign brief

`_run_spawned_metaflow` returns `{"status": "failed", "returncode": 1,
"last_lines": [...]}` — the diagnosis is in `last_lines`, and there is no
`error` key. `emit_prospects_update` only treated `err or status == "error"`
as a failure, so `status="failed"` fell through to the third branch and wrote
the bland "No new filing count — nothing to book" brief. Five days of real
tracebacks were captured in the database and never surfaced.

Failures are now `{"error", "failed", "stalled"}`, and when there is no
`error` key the child's tail becomes the body — with the exit code:

```text
Prospects update failed (failed, exit 1).
Symbols: MTN, LLY.
… PlatformMetaflowError: #MF.00000006.NOPLATFORM …
```

`last_lines` rides along on success too, so it is only read once the status
already says the run failed — otherwise every completed run would raise an
alarm. `yielded` stays a brief: a YK preemption is not a fault.

## Verified

`require_signals_metaflow` against both child envs:

```text
local    -> REJECTED: #MF.00000006.NOPLATFORM …
platform -> OK
```

A real `ProspectsUpdateFlow run --symbols=SLB` under the platform profile
registered on the Signals metadata service as run 996 and walked the whole
pipeline that used to die in `start`, exiting 0:

```text
_parameters → start → fetch_comprehensive_data → sync_filings →
extract_filings → analyze_filings → synthesize_position →
create_kb_artifacts → generate_base_files → create_sitrep → end
RETURNCODE 0
2026-08-25 06:33:05.691 Done!
```

Scheduling was never the problem — `prospects_check` has enqueued exactly one
`prospects_update` per day throughout, and none is stuck pending. Only
execution was broken.

`tests/engine/` 691 passed. New: `test_flow_gpu_tokens.py` pins the descriptor
failure mode; `test_agenda_emit.py` covers failed/stalled surfacing the tail,
a completed tail *not* raising an alarm, and yielded staying a brief;
`test_scheduled_task_dispatch.py` pins prospects as the single platform
opt-in and the spawner's local default.

## Not fixed here

`gpu_metrics_settle` fails differently — an upload to the
`signals-dataproducts` bucket from `signals/scripts/gpu_metrics_tier_up.py`.
Separate problem, left alone.
