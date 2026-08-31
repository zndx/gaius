# Six-hour operations sweep (06:45–12:45 UTC): findings and remediations

Cadence: cron-driven tick every ~20min hunting issues holding up normal
operations. Final health: 0 failures (29/32 pass, warnings only).

## Found and fixed (committed)
- **Polaris/Impala incident chain**: file moves broke the `.devenv/polaris`
  symlink → live Polaris 500'd on lazy jar loads (port stayed open —
  invisible to checks) → healing Polaris orphaned Impala's frontend client
  → ALL Polaris tables unresolvable. Symlink repointed, polaris +
  impala-impalad recycled. Payoff: FIRST-ever green signal settle chain —
  hour 496707/496710 registered AND verified (1.37M/1.45M rows), THS read
  path serving through Impala + the FDW `signal` view. Scheduled settles:
  6/6 green today.
- **task-watchdog ate live runs** (`e67648a`): 60-min wall-clock reset sat
  below median curate runtime; reset the healthy run-1805 row mid-render.
  Row restored (run completed into it), thresholds → 4h/45m (migration).
- **agenda_tracker persistence race** (`2a73b01`): dict mutated during
  iteration killed persistence passes; snapshot iteration.
- **ambient sklearn/scipy mismatch** (`c89065c`): lock paired sklearn
  1.7.2 with scipy 1.13.1 (is_lazy_array) — every synthesis cycle died.
  sklearn → 1.6.1 (+ mixed-module lesson: pair live-venv swaps with a
  prompt engine restart — the interim mixed state broke card renders).
- **Periodic Tasks check miscalibration** (same commit): expected
  cadences stale by 16× (cognition 15min vs real 4h) — permanent false
  "critically overdue" FAILs. Expected = real cadence.
- **Imageless published card** repaired (render + R2 + KV) after a
  transient R2 egress blip; health Card Images FAIL cleared.

## Proven organic (no hands)
- Cognition: first cron-driven cycle since Aug-15 (6 thoughts @09:02,
  233s); 16 thoughts today total.
- article_curate run 1805: select clean (the old 500 gone), dual-layer
  retention `hx.cot_reasoning id=86c57b78 (3,861 tok)`, 20 sources,
  completed into its rescued row.
- tier_settle: 6/6 scheduled green.

## Self-recovering as designed (post-window)
- 12:00 publish slot: aborted by the 12:12 mixed-state remediation
  restart; watchdog re-pick ~12:55 on coherent sklearn → enrichment-gate
  proof lands then (17:00 slot as backstop).
- 12:43 cognition: enqueued for 13:26 (jitter).
- FMP compaction: NOTREADY-only during load windows; first warm attempt
  on fixed engine_client ~13:15 — if "empty thinking compaction" recurs
  warm, prospects_service:412 gets the THINKBURN treatment.

## Notes
- Nix-python bare-probe libz artifact documented (memory): `import zlib`
  first; not damage.
- Durable follow-ups: `devenv tasks run polaris:install` (end the
  cross-project symlink); Cerebras optional-summary model pins; COG guru
  namespace renumbering.
