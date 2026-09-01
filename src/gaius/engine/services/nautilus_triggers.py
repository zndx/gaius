"""Nautilus trigger evaluation — pure, model-free, fully unit-testable.

Atelier's Nautilus pattern: the watcher owns no LLM-calling code and
never kills a process. ``evaluate_triggers(snapshot, cfg, now)`` is a
pure function of a deterministic snapshot; the judge (Overwatch, ACP +
Grok) lives behind a callback seam in the service. Triggers arm once per
scope-phase and re-arm only when the scope's position changes —
anti-storm by construction.

Federated note: this module reads only a snapshot dataclass, so a peer
engine can evaluate the same triggers against OUR public surfaces and
ledger its observations in ITS OWN ledger (each engine keeps its own
ledger on its own FSM; no cross-engine writes).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

# Trigger names
T1_SERVING_DESYNC = "serving_desync"
T2_KILL_LOOP = "kill_loop"
T3_OBJECTIVE_STALE = "objective_stale"
T4_FROZEN_INCIDENT = "frozen_incident"
T5_WATCHDOG_STORM = "watchdog_storm"
T6_DISCREDITED_PROBE = "discredited_probe_armed"


@dataclass(frozen=True)
class NautilusConfig:
    serving_desync_after_s: float = 900.0     # generous outer net
    kill_loop_count: int = 3
    kill_loop_window: timedelta = timedelta(minutes=30)
    objective_stale_factor: float = 2.0       # x cadence with no verification
    frozen_incident_after: timedelta = timedelta(hours=2)
    watchdog_storm_count: int = 2
    watchdog_storm_window: timedelta = timedelta(hours=24)
    discredited_brier: float = 0.35
    discredited_min_n: int = 10


@dataclass
class NautilusSnapshot:
    """Deterministic observation set, assembled with zero LLM involvement."""

    now: datetime
    # thinking facade: seconds since last successful liveness probe, or None
    facade_dark_for_s: float | None = None
    grpc_serving: bool = True
    # side-effect forecasts: [(endpoint, created_at, side_effect)]
    side_effect_forecasts: list[tuple[str, datetime, str]] = field(default_factory=list)
    # objectives: {name: (verdict, completed_at | None, cadence)}
    objectives: dict[str, tuple[str | None, datetime | None, timedelta]] = field(
        default_factory=dict
    )
    # healing sequences: [(sequence_id, endpoint, last_event_at, open)]
    healing_sequences: list[tuple[str, str, datetime, bool]] = field(
        default_factory=list
    )
    # watchdog resets: [(task_class, created_at)]
    watchdog_resets: list[tuple[str, datetime]] = field(default_factory=list)
    # ledger report rows (dicts from EfficacyLedger.report())
    ledger_report: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class TriggerFiring:
    trigger: str
    scope: str          # arming key: trigger re-fires only when scope phase changes
    detail: str
    evidence: dict[str, Any]


def evaluate_triggers(
    snapshot: NautilusSnapshot,
    cfg: NautilusConfig,
) -> list[TriggerFiring]:
    """Pure evaluation. The service applies once-per-phase arming on the
    returned (trigger, scope) pairs."""
    firings: list[TriggerFiring] = []
    now = snapshot.now

    # T1 — serving desync: engine gRPC up but the thinking facade dark
    # past the generous net. True engine-death detection is a federated
    # PEER's job (this process dies with the engine).
    if (
        snapshot.grpc_serving
        and snapshot.facade_dark_for_s is not None
        and snapshot.facade_dark_for_s >= cfg.serving_desync_after_s
    ):
        firings.append(
            TriggerFiring(
                trigger=T1_SERVING_DESYNC,
                scope="engine:facade",
                detail=(
                    f"thinking facade dark {snapshot.facade_dark_for_s:.0f}s "
                    f"while gRPC serves (net {cfg.serving_desync_after_s:.0f}s)"
                ),
                evidence={"dark_for_s": snapshot.facade_dark_for_s},
            )
        )

    # T2 — kill loop: repeated stop/reload side effects on one endpoint.
    # Detects the pre-e0ae0be reconciliation class FROM THE LEDGER ITSELF.
    by_endpoint: dict[str, list[datetime]] = {}
    for endpoint, created_at, side_effect in snapshot.side_effect_forecasts:
        if side_effect in ("remediate", "stop_endpoint", "reload"):
            if now - created_at <= cfg.kill_loop_window:
                by_endpoint.setdefault(endpoint, []).append(created_at)
    for endpoint, times in by_endpoint.items():
        if len(times) >= cfg.kill_loop_count:
            firings.append(
                TriggerFiring(
                    trigger=T2_KILL_LOOP,
                    scope=f"endpoint:{endpoint}",
                    detail=(
                        f"{len(times)} remediation side-effects on {endpoint} "
                        f"within {cfg.kill_loop_window} — healer may be the harm"
                    ),
                    evidence={"count": len(times), "endpoint": endpoint},
                )
            )

    # T3 — objective stale: FAIL verdict, or no verification in
    # stale_factor x cadence.
    for name, (verdict, completed_at, cadence) in snapshot.objectives.items():
        stale_after = cadence * cfg.objective_stale_factor
        if verdict == "fail":
            firings.append(
                TriggerFiring(
                    trigger=T3_OBJECTIVE_STALE,
                    scope=f"objective:{name}",
                    detail=f"objective {name} FAILED its last verification",
                    evidence={"verdict": verdict},
                )
            )
        elif completed_at is None or (now - completed_at) > stale_after:
            age = None if completed_at is None else (now - completed_at)
            firings.append(
                TriggerFiring(
                    trigger=T3_OBJECTIVE_STALE,
                    scope=f"objective:{name}",
                    detail=(
                        f"objective {name} unverified for "
                        f"{age or 'ever'} (limit {stale_after}) — "
                        "the verifier itself may be down"
                    ),
                    evidence={"age_s": age.total_seconds() if age else None},
                )
            )

    # T4 — frozen incident: an open healing sequence with no new events.
    for sequence_id, endpoint, last_event_at, is_open in snapshot.healing_sequences:
        if is_open and (now - last_event_at) > cfg.frozen_incident_after:
            firings.append(
                TriggerFiring(
                    trigger=T4_FROZEN_INCIDENT,
                    scope=f"sequence:{sequence_id}",
                    detail=(
                        f"healing sequence for {endpoint} open with no events "
                        f"for {now - last_event_at}"
                    ),
                    evidence={"sequence_id": sequence_id, "endpoint": endpoint},
                )
            )

    # T5 — watchdog storm: repeated resets of one task class.
    by_class: dict[str, int] = {}
    for task_class, created_at in snapshot.watchdog_resets:
        if now - created_at <= cfg.watchdog_storm_window:
            by_class[task_class] = by_class.get(task_class, 0) + 1
    for task_class, count in by_class.items():
        if count >= cfg.watchdog_storm_count:
            firings.append(
                TriggerFiring(
                    trigger=T5_WATCHDOG_STORM,
                    scope=f"task:{task_class}",
                    detail=(
                        f"{count} watchdog resets of {task_class} in "
                        f"{cfg.watchdog_storm_window} — thresholds or the "
                        "class itself need attention"
                    ),
                    evidence={"count": count, "task_class": task_class},
                )
            )

    # T6 — discredited probe still armed: poor current-epoch Brier on a
    # side-effect-bearing observer. Action is REPORTING (salt), never
    # disabling — doctrine.
    for row in snapshot.ledger_report:
        brier = row.get("brier")
        if (
            brier is not None
            and brier > cfg.discredited_brier
            and row.get("resolved", 0) >= cfg.discredited_min_n
        ):
            firings.append(
                TriggerFiring(
                    trigger=T6_DISCREDITED_PROBE,
                    scope=f"observer:{row['observer']}:{row.get('call_site', '')}",
                    detail=(
                        f"{row['observer']} Brier {brier:.2f} over "
                        f"{row['resolved']} resolved at "
                        f"{row.get('momentum_bucket')} — verdicts deserve salt"
                    ),
                    evidence={"brier": brier, "n": row.get("resolved")},
                )
            )

    return firings
