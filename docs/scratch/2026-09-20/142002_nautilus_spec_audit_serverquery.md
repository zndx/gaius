# Nautilus spec audit — Status green while ServerQuery is dead (2026-09-20)

AgentRTC Connect on 2026-09-20 opened an empty workspace (`no live agenda or
thoughts brief`) and sitrep looked like "no cognition, Airflow unreachable."
Neither was true. **Audit every project's Nautilus spec against this class.**

## What actually failed

Gaius `Engine/ServerQuery` returned UNKNOWN for every kind (THOUGHTS, AGENDA,
COGNITION, PEERS, SURFACES) because the servicer compared
`zpb.SERVER_QUERY_KIND_FMP` after a proto compile that omitted that enum.
`Engine/Status` still advertised `cognition` healthy. Hermes built an empty
pack. The live call's first turn was honest-empty.

Airflow 3 was up (`/api/v2/monitor/health` 200). Sitrep `airflow_hub` is
Gaius's **coordination** surface: `#CO.0000000D.MISSTICK
miss:theta_cycle,weekly_signals_summary` — missed DAG ticks (skip≠success),
not an unreachable hub. Theta is not caught up. `/health` is a 404 on
Airflow 3 (moved to `/api/v2/monitor/health`).

## What Nautilus did not see

Gaius Nautilus (`config/supervision/gaius.textproto`, `directives=observe`)
watches `SOURCE_KIND_ENGINE_GRPC` **Status / WatchWorkload**, systemd, and
task-queue cadences. It does **not** probe ServerQuery THOUGHTS or AGENDA, so
UNKNOWN on every query with a green Status is a silent miss. MISSTICK is a
guru stuffed into `Surface.url`, not a Nautilus process. Airflow itself is
not in the Gaius tree.

Observe-only would not have actuated anyway; the gap is **visibility**.

## Audit each project spec for

1. **ServerQuery vs Status.** A Status-healthy engine can still fail THOUGHTS,
   AGENDA, RESOURCES. Observe at least one content kind (THOUGHTS or AGENDA)
   or treat ServerQuery UNKNOWN as unhealthy.
2. **Do not equate coordination MISSTICK with Airflow down.** Probe Airflow 3
   at `/api/v2/monitor/health`. Missed kinds (especially `theta_cycle`) are
   cadence, not hub death. Do not catch up Theta.
3. **Surface.url is a URL.** Gurus (`#CO.…`) in `url` make sitrep/voice say
   the hub is unreachable. Keep guru/missed_ticks out of the URL field.
4. **Proto compile.** Generating `engine_pb2` from a tree missing an enum the
   servicer still names must not crash every ServerQuery (getattr / kind table).
5. **Cross-project trees.** Repeat for Gaius, Hermes, Ægir, Atelier, Signals
   `config/supervision/*.textproto`.

## Live remediations that landed

- Gaius servicer: `SERVER_QUERY_KIND_FMP` via getattr (2026-09-20).
- Hermes sitrep: Airflow 3 probe separate from coordination MISSTICK.
- This note: specs still need the audit; do not treat this file as the audit.
