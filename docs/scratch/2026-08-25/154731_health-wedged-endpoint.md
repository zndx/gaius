# /health learns the wedged-endpoint failure mode

Yesterday thinking `:8081` stopped serving without dying and nothing noticed
for seven hours. `/health fix endpoints` could not even see it. This adds
detection and remediation for that shape.

## The shape

A wedged vLLM is alive by every coarse measure and serves nothing:

```text
/health           no response in 15s
GPU utilisation   0% on four cards, memory still held
worker CPU        86-88%, ~6.5h accumulated
EngineCore        futex_wait_queue
:8081 sockets     18 CLOSE-WAIT against 4 established
```

Nothing crashes, so every check that watches for a returncode sees a healthy
process.

## Why the existing framework was blind

Diagnostic reflexivity. `/health fix endpoints` asks `Orchestrator.status`
first — and a wedged endpoint is exactly what blocks the orchestrator. The
timeout was then reported as `#GR.00000001.ENGINEOFF`, blaming a perfectly
healthy engine for the endpoint's fault. Any check routed through the engine
is blind to this failure by construction.

So `gaius.health.wedged_endpoint` depends on **nothing but the host**: it
discovers endpoints from the running `vllm serve` argv, probes their HTTP
surface directly, and remediates with signals. No gRPC, no orchestrator.

## Detection

`scan_endpoints()` classifies every vLLM on the host:

| verdict | meaning |
|---|---|
| `healthy` | answered |
| `starting` | unresponsive, still inside the startup floor |
| `wedged` | alive, bound, unresponsive well past the floor |
| `down` | no process owns the port |

Endpoints are found from argv rather than the orchestrator, so a blocked
engine cannot hide one. Entries are deduped by port, preferring the process
that actually owns the listening socket — a launcher carries the same argv as
the server it spawned, and signalling the wrapper would leave the wedged child
holding the port.

### The safety guard

A cold start legitimately holds the process alive and unresponsive for up to
`VLLMController._startup_timeout` (900s). Killing a loading endpoint would be
far worse than waiting out a hung one, so anything younger than that floor is
`starting` and is **never** signalled. A test asserts the floor stays >= the
controller's own budget, so raising one without the other fails CI.
`GAIUS_WEDGED_MIN_UPTIME_S` tunes it.

One slow reply is not a wedge either — three consecutive misses are required.

## Remediation

The engine supervises vLLM: once the child exits, its health loop sees a
returncode and starts a replacement. So the cure is to make the wedged process
exit — SIGTERM, then SIGKILL, because a futex-blocked engine core routinely
ignores SIGTERM. `remediate_wedged` refuses anything not classified `wedged`.

`/health fix endpoints` now probes directly in the two cases the old path
missed: when `Orchestrator.status` times out, and when it answers but reports
nothing unhealthy (its cached status went stale when the endpoint stopped
answering).

## Surface

```text
/health wedged                     probe endpoints directly; detection only
/health fix endpoints --dry-run    show what would be ended
/health fix endpoints              end the hung process
```

`SERVICE_STRATEGIES` gains `wedged` (alias `hung`) so it is discoverable via
`list_services()`. KB heuristic:
`build/dev/current/heuristics/gaius/inference/endpoint_wedged.md`.
Guru: `#EP.00000019.WEDGED`.

## Verified

Against a fake wedged endpoint — a process carrying `vllm serve … --port 8099`
in its argv that binds, accepts and never replies — while the real thinking
endpoint stayed up throughout:

```text
default floor (900s)   8081 healthy | 8099 starting      wedged=0   # guard holds
tightened floor        8081 healthy | 8099 wedged        guru #EP.00000019.WEDGED
--dry-run              would_restart [8099]              real pid untouched
fix                    cleared [{8099, SIGTERM}]         8099 released
after                  real endpoint http=200            real pid untouched
```

The guard is the important line: with the production floor the unresponsive
fake was `starting`, not `wedged`, and would never have been signalled.

Unit suite (16) covers black-hole vs responder classification, the startup
guard, remediation refusing non-wedged verdicts, SIGTERM success, SIGKILL
escalation against a process that ignores SIGTERM, argv parsing, and report
shape. `tests/engine/` 692 passed (same two pre-existing
`test_gaius_servicer.py::TestComplete` failures).

## Not done

The autonomous loop. The orchestrator already has the machinery — 3-strike
`UNHEALTHY` → `_maybe_restart_endpoint`, auto-restart enabled — and it did not
fire during the real incident. I never determined why: restoring service
destroyed the live evidence, and wiring an autonomous path on a guess is how
you get a killer loop. The operator-invoked path here is verifiable today; if
the wedge recurs, `/health wedged` output plus the orchestrator's own logs at
that moment would settle whether the loop stalls or `_maybe_restart_endpoint`
skips on stale status.
