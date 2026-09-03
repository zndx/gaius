"""Nautilus: the in-engine, MODEL-FREE detection capability (BaseDaemon).

Nautilus and Overwatch are DISTINCT capabilities (user doctrine):
Nautilus is the model-free watcher — deterministic snapshots, pure
triggers, zero LLM code, always works; Overwatch is its own capability
(ACP + Grok judgement, overwatch_judge) that Nautilus ESCALATES TO for
what deterministic verification cannot settle. Neither contains the
other.

Polls deterministic surfaces every 60s, evaluates the pure trigger set
(nautilus_triggers), applies once-per-scope-phase arming, and records
firings (plus any Overwatch consultation results) to overwatch_events.

Also owns the objective resolution sweep: recently-completed objective
verifications are the outcome source for upstream probe forecasts (that
resolution is performed inside ObjectiveService at verification time;
Nautilus ensures verifications HAPPEN by watching their staleness — T3).

Federated long-term: each engine runs a symmetric Nautilus over its own
ledger and FSM; peers probe each other's public surfaces and record in
their own ledgers. This service contains zero peer-write machinery by
design.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from gaius.engine.services.base_daemon import (
    BaseDaemon,
    DaemonCriticality,
    DaemonHealth,
    DaemonStartupError,
)
from gaius.engine.services.nautilus_triggers import (
    NautilusConfig,
    NautilusSnapshot,
    TriggerFiring,
    evaluate_triggers,
)
from gaius.engine.services.overwatch_judge import (
    OverwatchJudge,
    autonomy_tier,
    get_judge,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 60.0

# Triggers whose questions deterministic checks cannot settle alone —
# these escalate to the Overwatch capability. The rest are Nautilus-only
# record-and-report.
OVERWATCH_TRIGGERS = {"kill_loop", "frozen_incident", "objective_stale"}
JUDGE_TRIGGERS = OVERWATCH_TRIGGERS  # back-compat alias

# verify_all runs on the objective-verify pg_cron (`38 1,7,13,19 * * *`),
# so no objective can be re-verified more often than this, whatever its
# declared cadence. T3 staleness must clock against the verify interval,
# or a 2h-cadence objective (tier_settle) reads "stale" for two hours of
# every six — the organic T3 storm of 2026-09-03 18:47–19:06.
OBJECTIVE_VERIFY_INTERVAL = timedelta(hours=6)


class NautilusService(BaseDaemon):
    def __init__(self, db_pool: Any) -> None:
        self._pool = db_pool
        self._cfg = NautilusConfig()
        self._judge = get_judge()
        self._task: asyncio.Task | None = None
        self._running = False
        self._cycles = 0
        self._last_cycle_at: float | None = None
        self._firings_recorded = 0
        # Once-per-phase arming: (trigger, scope) -> armed marker; cleared
        # when the scope's phase signature changes.
        self._armed: dict[tuple[str, str], str] = {}
        self._facade_dark_since: float | None = None

    # ------------------------------------------------------------------
    # BaseDaemon contract
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "nautilus"

    @property
    def criticality(self) -> DaemonCriticality:
        return DaemonCriticality.OPTIONAL

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._pool is None:
            raise DaemonStartupError(
                daemon_name=self.name,
                message=(
                    "Nautilus needs the shared DB pool.\n"
                    "  Try: /health fix postgres"
                ),
                guru_code="#OW.00000004.NOPOOL",
            )
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"Nautilus started (poll={POLL_INTERVAL_S:.0f}s, "
            f"autonomy={autonomy_tier()}, judge=grok pinned/fail-closed)"
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Nautilus stopped")

    async def health_check(self) -> DaemonHealth:
        stale = (
            self._last_cycle_at is not None
            and time.monotonic() - self._last_cycle_at > 5 * POLL_INTERVAL_S
        )
        return DaemonHealth(
            healthy=self._running and not stale,
            message=(
                f"cycles={self._cycles} firings={self._firings_recorded} "
                f"armed={len(self._armed)} autonomy={autonomy_tier()}"
            ),
            guru_code="#OW.00000005.STALLED" if stale else None,
        )

    # ------------------------------------------------------------------
    # Loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Nautilus cycle failed (continuing)")
            await asyncio.sleep(POLL_INTERVAL_S)

    async def _cycle(self) -> None:
        snapshot = await self._assemble_snapshot()
        firings = evaluate_triggers(snapshot, self._cfg)
        for firing in firings:
            key = (firing.trigger, firing.scope)
            # Stable phase signature (falls back to detail for triggers
            # that have not declared one). Details that embed an age
            # re-armed every poll — the 2026-09-03 T3 storm.
            phase_sig = firing.phase or firing.detail
            if self._armed.get(key) == phase_sig:
                continue  # armed once per phase — anti-storm
            self._armed[key] = phase_sig
            await self._dispatch(firing, snapshot)
        # Re-arm scopes whose triggers no longer fire (phase cleared).
        active = {(f.trigger, f.scope) for f in firings}
        for key in list(self._armed):
            if key not in active:
                self._armed.pop(key, None)
        self._cycles += 1
        self._last_cycle_at = time.monotonic()

    # ------------------------------------------------------------------
    # Snapshot assembly (deterministic; zero LLM)
    # ------------------------------------------------------------------

    async def _assemble_snapshot(self) -> NautilusSnapshot:
        import aiohttp

        now = datetime.now(timezone.utc)

        # Thinking facade liveness (self-observable half of T1).
        facade_dark_for_s: float | None = None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "http://127.0.0.1:9890/healthz",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        self._facade_dark_since = None
                    else:
                        raise RuntimeError(f"healthz {resp.status}")
        except Exception:  # noqa: BLE001 — darkness is the measurement
            if self._facade_dark_since is None:
                self._facade_dark_since = time.monotonic()
            facade_dark_for_s = time.monotonic() - self._facade_dark_since

        async with self._pool.acquire() as conn:
            side_effects = await conn.fetch(
                """
                SELECT endpoint, created_at, side_effect
                FROM probe_forecasts
                WHERE side_effect IN ('remediate','stop_endpoint','reload')
                  AND endpoint IS NOT NULL
                  AND created_at > NOW() - INTERVAL '2 hours'
                """
            )
            objective_rows = await conn.fetch(
                """
                SELECT DISTINCT ON (objective_name)
                       objective_name, verdict, completed_at
                FROM objective_verifications
                ORDER BY objective_name, started_at DESC
                """
            )
            open_sequences = await conn.fetch(
                """
                SELECT sequence_id::text, max(endpoint) AS endpoint,
                       max(created_at) AS last_event_at,
                       bool_and(event_type != 'sequence_completed') AS is_open
                FROM healing_events
                WHERE created_at > NOW() - INTERVAL '48 hours'
                GROUP BY sequence_id
                """
            )
            watchdog_rows = await conn.fetch(
                """
                SELECT task_class, created_at FROM probe_forecasts
                WHERE observer = 'watchdog:pg_cron.task_reset'
                  AND created_at > NOW() - INTERVAL '24 hours'
                """
            )

        from gaius.engine.services.efficacy_ledger import get_ledger
        from gaius.engine.services.objective_service import OBJECTIVES

        ledger = get_ledger()
        ledger_report = await ledger.report() if ledger else []

        objectives: dict[str, tuple[str | None, datetime | None, timedelta]] = {}
        seen = set()
        for row in objective_rows:
            name = row["objective_name"]
            seen.add(name)
            spec = OBJECTIVES.get(name)
            objectives[name] = (
                row["verdict"],
                row["completed_at"],
                max(spec.cadence if spec else timedelta(hours=6), OBJECTIVE_VERIFY_INTERVAL),
            )
        for name, spec in OBJECTIVES.items():
            if name not in seen:
                objectives[name] = (None, None, max(spec.cadence, OBJECTIVE_VERIFY_INTERVAL))

        return NautilusSnapshot(
            now=now,
            facade_dark_for_s=facade_dark_for_s,
            grpc_serving=True,  # we are running inside the engine
            side_effect_forecasts=[
                (r["endpoint"], r["created_at"], r["side_effect"])
                for r in side_effects
            ],
            objectives=objectives,
            healing_sequences=[
                (r["sequence_id"], r["endpoint"] or "", r["last_event_at"], r["is_open"])
                for r in open_sequences
            ],
            watchdog_resets=[
                (r["task_class"] or "", r["created_at"]) for r in watchdog_rows
            ],
            ledger_report=ledger_report,
        )

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def _dispatch(
        self, firing: TriggerFiring, snapshot: NautilusSnapshot
    ) -> None:
        logger.warning(
            f"#OW.00000006.TRIGGER {firing.trigger} [{firing.scope}]: "
            f"{firing.detail}"
        )
        judge_payload: dict[str, Any] = {"status": "not_invoked"}
        if firing.trigger in OVERWATCH_TRIGGERS:
            judge_payload = await self._judge.consult(
                trigger=firing.trigger,
                scope=firing.scope,
                detail=firing.detail,
                snapshot_markdown=self._render_snapshot(snapshot),
                ledger_report=snapshot.ledger_report,
            )

        action = "recorded"
        verdict = judge_payload.get("verdict")
        if verdict and not verdict.get("in_contract", True):
            action = f"reported:{verdict.get('recommended_action', 'report')}"
            # v1 monitor tier: proposals are recorded for the operator;
            # nothing executes. (propose tier wires aiops approval.)

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO overwatch_events (
                        trigger_name, scope, detail, snapshot,
                        judge_invoked, judge_status, judge_verdict, action_taken
                    ) VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7::jsonb,$8)
                    """,
                    firing.trigger,
                    firing.scope,
                    firing.detail,
                    json.dumps(firing.evidence, default=str),
                    firing.trigger in OVERWATCH_TRIGGERS,
                    judge_payload.get("status"),
                    json.dumps(verdict, default=str) if verdict else None,
                    action,
                )
            self._firings_recorded += 1
        except Exception:
            logger.exception("#OW.00000007.EVTFAIL overwatch_events write failed")

    @staticmethod
    def _render_snapshot(snapshot: NautilusSnapshot) -> str:
        """No-LLM markdown rendering (the sweep-log format, condensed)."""
        lines = [f"as of {snapshot.now.isoformat()}"]
        lines.append(
            f"- thinking facade: "
            + (
                "up"
                if snapshot.facade_dark_for_s is None
                else f"dark {snapshot.facade_dark_for_s:.0f}s"
            )
        )
        for name, (verdict, completed_at, cadence) in sorted(
            snapshot.objectives.items()
        ):
            lines.append(
                f"- objective {name}: {verdict or 'never-verified'} "
                f"(last {completed_at}, cadence {cadence})"
            )
        lines.append(
            f"- side-effect forecasts (2h): {len(snapshot.side_effect_forecasts)}"
        )
        lines.append(
            f"- watchdog resets (24h): {len(snapshot.watchdog_resets)}"
        )
        open_seqs = [s for s in snapshot.healing_sequences if s[3]]
        lines.append(f"- open healing sequences (48h): {len(open_seqs)}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Status surface (for CLI)
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "cycles": self._cycles,
            "firings_recorded": self._firings_recorded,
            "armed_triggers": [
                {"trigger": t, "scope": s} for (t, s) in self._armed
            ],
            "autonomy": autonomy_tier(),
            "judge_agent": "grok (pinned, fail-closed)",
            "judge_available": OverwatchJudge.preflight() is None,
        }
