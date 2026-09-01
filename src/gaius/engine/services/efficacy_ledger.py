"""Probe-efficacy ledger: state-aware Brier scoring for probes and timeouts.

Every probe/timeout/heuristic/watchdog/judge verdict is recorded as a
FORECAST — a crisp proposition with an implied P(true) — stamped with the
FSM position of its call site and the epoch that produced it. Outcomes
arrive later as appended resolution events (gold = human attestation via
``/efficacy resolve``; silver = downstream objective verification or
self-resolution). Scores accumulate per (observer × call_site × momentum
bucket × epoch) and feed the DST-style discount α that Overwatch consumes.

Doctrine:
- The ledger LEARNS probe trustworthiness; it never disables a probe and
  never auto-tunes a threshold. Salt annotates; it does not override.
- ``inconclusive`` (p=0.5) is first-class "explicitly unmeasurable" —
  a timeout is inconclusive about the world-proposition it couldn't see,
  plus a separate ``theory:`` forecast for what the timeout IS evidence
  of (timeouts are measurements about the observer, not facts about the
  world).
- Recording is CONTRACTUALLY NON-RAISING toward probe paths: this is a
  deliberate, documented exception to fail-fast — observability must
  never take down the observed system. Failures log
  ``#EFF.00000001.RECFAIL`` and increment a counter surfaced in /health.
- One ledger per engine, single-writer by design. Federated peers probe
  our public surfaces and record observations in THEIR ledgers.

Pattern source: Synth's ``ObservationLedger`` (calibration.py), adapted
to Postgres + the Gaius FSM (see ``gaius.engine.fsm``).
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any
from uuid import UUID

from gaius.engine.fsm import FsmPosition, momentum_bucket

logger = logging.getLogger(__name__)

# Implied P(proposition true) per verdict. Mature probes pass explicit p.
VERDICT_P: dict[str, float] = {
    "pass": 0.85,
    "fail": 0.15,
    "inconclusive": 0.50,
    "error": 0.50,
}

# Shrinkage pseudo-count and prior for the discount alpha:
#   alpha = (n/(n+K))(1 - Brier) + (K/(n+K)) * PRIOR
_ALPHA_K = 2.0
_ALPHA_PRIOR = 0.5


def _detect_engine_rev() -> str:
    """Epoch component: this engine's code revision.

    Precedence: GAIUS_ENGINE_REV env (stamped by the launcher) → git
    rev-parse (cached) → 'unknown'. A rewritten probe must not inherit
    its predecessor's reputation, so scores filter to the current epoch.
    """
    rev = (os.environ.get("GAIUS_ENGINE_REV") or "").strip()
    if rev:
        return rev
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except Exception:
        pass
    return "unknown"


class EfficacyLedger:
    """DB-backed forecast ledger. One instance per engine, shared pool."""

    def __init__(self, db_pool: Any) -> None:
        self._pool = db_pool
        self._engine_rev = _detect_engine_rev()
        self._record_failures = 0
        # Last observed position per scope, for fsm_transitions appends.
        self._last_positions: dict[str, dict[str, Any]] = {}

    @property
    def record_failures(self) -> int:
        """Count of failed ledger writes (surfaced by /health)."""
        return self._record_failures

    @property
    def engine_rev(self) -> str:
        return self._engine_rev

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def record_forecast(
        self,
        observer: str,
        observer_kind: str,
        call_site: str,
        proposition: str,
        verdict: str,
        *,
        p: float | None = None,
        evidence: dict[str, Any] | None = None,
        side_effect: str | None = None,
        position: FsmPosition | None = None,
        model_id: str | None = None,
        elapsed_ms: int | None = None,
        resolves: list[str] | None = None,
        sequence_id: UUID | None = None,
    ) -> UUID | None:
        """Append one forecast row. NEVER raises into the caller.

        Returns the forecast_id, or None if the write failed (logged as
        #EFF.00000001.RECFAIL and counted for /health).
        """
        import json as _json

        try:
            if p is None:
                p = VERDICT_P.get(verdict, 0.5)
            pos = position.to_columns() if position else {}
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO probe_forecasts (
                        observer, call_site, observer_kind, proposition,
                        verdict, p, evidence, side_effect,
                        task_class, task_id, task_lifecycle,
                        flow_type, flow_run_id, flow_step,
                        endpoint, endpoint_state, admission_phase, momentum,
                        engine_rev, model_id, elapsed_ms, resolves, sequence_id
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11,
                              $12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23)
                    RETURNING forecast_id
                    """,
                    observer,
                    call_site,
                    observer_kind,
                    proposition,
                    verdict,
                    float(p),
                    _json.dumps(evidence or {}, default=str),
                    side_effect,
                    pos.get("task_class"),
                    pos.get("task_id"),
                    pos.get("task_lifecycle"),
                    pos.get("flow_type"),
                    pos.get("flow_run_id"),
                    pos.get("flow_step"),
                    pos.get("endpoint"),
                    pos.get("endpoint_state"),
                    pos.get("admission_phase"),
                    pos.get("momentum"),
                    self._engine_rev,
                    model_id,
                    elapsed_ms,
                    resolves,
                    sequence_id,
                )
            forecast_id = row["forecast_id"]
            if position is not None:
                await self._note_transition(observer, position)
            if verdict == "pass" and resolves:
                await self.auto_resolve_for(observer, resolves)
            return forecast_id
        except Exception as e:  # noqa: BLE001 — documented fail-open exception
            self._record_failures += 1
            logger.warning(
                f"#EFF.00000001.RECFAIL ledger write failed for {observer} "
                f"({proposition!r}): {e} — probe path unaffected; "
                f"failures={self._record_failures}"
            )
            return None

    async def _note_transition(self, observer: str, position: FsmPosition) -> None:
        """Append an fsm_transitions row when a scope's position changes."""
        import json as _json

        try:
            scope = (
                f"endpoint:{position.endpoint}" if position.endpoint
                else f"task:{position.task_class}" if position.task_class
                else f"flow:{position.flow_type}" if position.flow_type
                else None
            )
            if scope is None:
                return
            # Momentum churn is not a transition; compare non-momentum axes.
            cols = {k: v for k, v in position.to_columns().items() if k != "momentum"}
            prev = self._last_positions.get(scope)
            if prev == cols:
                return
            self._last_positions[scope] = cols
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO fsm_transitions (scope, from_position, to_position, trigger)
                    VALUES ($1, $2::jsonb, $3::jsonb, $4)
                    """,
                    scope,
                    _json.dumps(prev, default=str) if prev else None,
                    _json.dumps(cols, default=str),
                    observer,
                )
        except Exception as e:  # noqa: BLE001 — same fail-open contract
            logger.debug(f"fsm_transitions append skipped: {e}")

    # ------------------------------------------------------------------
    # Resolution (corrections are appended events; latest wins at read)
    # ------------------------------------------------------------------

    async def resolve(
        self,
        forecast_id: UUID | str,
        outcome: bool,
        tier: str,
        resolver: str,
        note: str | None = None,
    ) -> bool:
        """Append one resolution event for a forecast."""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO probe_resolutions (forecast_id, outcome, tier, resolver, note)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    UUID(str(forecast_id)),
                    outcome,
                    tier,
                    resolver,
                    note,
                )
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"#EFF.00000002.RESFAIL resolution write failed: {e}")
            return False

    async def resolve_matching(
        self,
        proposition_pattern: str,
        outcome: bool,
        tier: str,
        resolver: str,
        window_hours: float = 24.0,
        note: str | None = None,
    ) -> int:
        """Resolve every OPEN forecast whose proposition matches the
        LIKE-pattern within the trailing window. Returns rows resolved."""
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT f.forecast_id FROM probe_forecasts f
                    WHERE f.proposition LIKE $1
                      AND f.created_at > NOW() - INTERVAL '1 hour' * $2
                      AND NOT EXISTS (
                          SELECT 1 FROM probe_resolutions r
                          WHERE r.forecast_id = f.forecast_id
                      )
                    """,
                    proposition_pattern,
                    window_hours,
                )
                for row in rows:
                    await conn.execute(
                        """
                        INSERT INTO probe_resolutions (forecast_id, outcome, tier, resolver, note)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        row["forecast_id"],
                        outcome,
                        tier,
                        resolver,
                        note,
                    )
            return len(rows)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"#EFF.00000002.RESFAIL resolve_matching failed: {e}")
            return 0

    async def auto_resolve_for(
        self, observer: str, resolves: list[str], window_hours: float = 24.0
    ) -> int:
        """Silver-resolve TRUE the open forecasts a PASS retroactively
        proves (the declared ``resolves`` patterns — downstream proof)."""
        total = 0
        for pattern in resolves:
            total += await self.resolve_matching(
                pattern,
                outcome=True,
                tier="silver",
                resolver=f"downstream:{observer}",
                window_hours=window_hours,
            )
        return total

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    async def report(
        self,
        observer: str | None = None,
        current_epoch_only: bool = True,
    ) -> list[dict[str, Any]]:
        """Brier + α per (observer × call_site × momentum bucket).

        Unresolved-only groups surface as brier=None, alpha=prior —
        "uncalibrated: discount heavily", never trustworthy.
        """
        clauses = ["1=1"]
        args: list[Any] = []
        if observer:
            args.append(observer)
            clauses.append(f"f.observer = ${len(args)}")
        if current_epoch_only:
            args.append(self._engine_rev)
            clauses.append(f"f.engine_rev = ${len(args)}")
        query = f"""
            SELECT f.observer, f.call_site, f.momentum, f.p,
                   r.outcome
            FROM probe_forecasts f
            LEFT JOIN LATERAL (
                SELECT outcome FROM probe_resolutions
                WHERE forecast_id = f.forecast_id
                ORDER BY resolved_at DESC LIMIT 1
            ) r ON TRUE
            WHERE {' AND '.join(clauses)}
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *args)

        groups: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in rows:
            key = (row["observer"], row["call_site"], momentum_bucket(row["momentum"]))
            g = groups.setdefault(
                key, {"n": 0, "resolved": 0, "sse": 0.0}
            )
            g["n"] += 1
            if row["outcome"] is not None:
                g["resolved"] += 1
                target = 1.0 if row["outcome"] else 0.0
                g["sse"] += (row["p"] - target) ** 2

        out = []
        for (obs, site, bucket), g in sorted(groups.items()):
            brier = (g["sse"] / g["resolved"]) if g["resolved"] else None
            n = g["resolved"]
            if brier is None:
                alpha = _ALPHA_PRIOR
                alpha_note = f"α={alpha:.2f} (uncalibrated — discount heavily)"
            else:
                alpha = (n / (n + _ALPHA_K)) * (1.0 - brier) + (
                    _ALPHA_K / (n + _ALPHA_K)
                ) * _ALPHA_PRIOR
                alpha_note = f"α={alpha:.2f} (Brier {brier:.3f}/n={n})"
            out.append(
                {
                    "observer": obs,
                    "call_site": site,
                    "momentum_bucket": bucket,
                    "n": g["n"],
                    "resolved": n,
                    "brier": round(brier, 4) if brier is not None else None,
                    "alpha": round(alpha, 4),
                    "alpha_note": alpha_note,
                    "engine_rev": self._engine_rev if current_epoch_only else "*",
                }
            )
        return out

    async def recent(
        self, observer: str | None = None, limit: int = 25
    ) -> list[dict[str, Any]]:
        """Most recent forecasts with their latest resolution, for the CLI."""
        clauses = ["1=1"]
        args: list[Any] = []
        if observer:
            args.append(observer)
            clauses.append(f"f.observer = ${len(args)}")
        args.append(limit)
        query = f"""
            SELECT f.forecast_id, f.created_at, f.observer, f.call_site,
                   f.proposition, f.verdict, f.p, f.side_effect,
                   f.task_class, f.task_lifecycle, f.endpoint,
                   f.endpoint_state, f.admission_phase, f.momentum,
                   f.engine_rev,
                   r.outcome, r.tier, r.resolver
            FROM probe_forecasts f
            LEFT JOIN LATERAL (
                SELECT outcome, tier, resolver FROM probe_resolutions
                WHERE forecast_id = f.forecast_id
                ORDER BY resolved_at DESC LIMIT 1
            ) r ON TRUE
            WHERE {' AND '.join(clauses)}
            ORDER BY f.created_at DESC
            LIMIT ${len(args)}
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
        return [dict(row) for row in rows]


_ledger: EfficacyLedger | None = None


def init_ledger(db_pool: Any) -> EfficacyLedger:
    """Create the engine-wide ledger singleton (called from server wiring)."""
    global _ledger
    _ledger = EfficacyLedger(db_pool)
    logger.info(
        f"EfficacyLedger initialized (engine_rev={_ledger.engine_rev})"
    )
    return _ledger


def get_ledger() -> EfficacyLedger | None:
    """The engine-wide ledger, or None before wiring / outside the engine.

    Callers on probe paths must treat None as "no ledger" and continue —
    the same non-raising contract as record_forecast.
    """
    return _ledger
