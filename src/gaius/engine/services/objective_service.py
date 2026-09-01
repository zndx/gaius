"""Verifiable objectives per task class — the outcome side of the ledger.

Doctrine: every scheduled task and Metaflow execution carries a
verifiable objective. Internal probes FORECAST ("cards published this
slot are publicly served"); objective verification establishes whether
the objective actually happened; the efficacy ledger is updated
accordingly (Brier). This is the mechanism that catches "probes report
success while objectives fail" — the aging-cards class.

``site_freshness`` is the first full verifier: a 3-way comparison of
what Postgres believes, what the Cloudflare KV actually serves, and what
the live public site actually renders. A site frozen for months passes a
"does any card link exist" substring test; it cannot pass axis 2 or 3.

Verdicts are written to ``objective_verifications`` (this module is that
table's first writer) and recorded as ``objective:`` forecasts in the
efficacy ledger; each run silver-resolves the upstream publish forecasts
it can prove or disprove.

Escalation: a FAIL verdict is surfaced by Nautilus trigger T3
(objective-stale) — the Overwatch path — rather than by injecting
synthetic health-observer incidents.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

logger = logging.getLogger(__name__)

PUBLIC_SITE = "https://gaius.zndx.org"


@dataclass(frozen=True)
class ObjectiveSpec:
    """Declares a task class's verifiable objective and its DAG linkage."""

    name: str
    dag: tuple[str, ...]            # scheduled_tasks task_types upstream
    flows: tuple[str, ...] = ()     # Metaflow flow names upstream
    resolves: tuple[str, ...] = ()  # forecast proposition LIKE-patterns
    cadence: timedelta = timedelta(hours=6)
    description: str = ""
    # None = declared but verifier pending (records inconclusive).
    verifier: str | None = None     # method name on ObjectiveService
    skeleton_check: str | None = field(default=None)  # SQL for skeleton specs
    params: dict[str, Any] = field(default_factory=dict)  # verifier thresholds


# The registry: every DAG-bearing task class declares an objective. Full
# verifiers land incrementally; a skeleton spec still yields an honest
# row (its SQL asserts the objective's footprint advanced in-window).
OBJECTIVES: dict[str, ObjectiveSpec] = {
    "site_freshness": ObjectiveSpec(
        name="site_freshness",
        dag=("article_curate", "publish_cards"),
        flows=("ArticleCurationFlow",),
        resolves=("slot % cards are publicly served",),
        cadence=timedelta(hours=6),
        description="Public cards on gaius.zndx.org are fresh and coherent "
        "across DB, KV, and the live site",
        verifier="verify_site_freshness",
    ),
    "content_currency": ObjectiveSpec(
        name="content_currency",
        dag=("article_curate", "publish_cards", "feed_check"),
        flows=("ArticleCurationFlow",),
        resolves=("slot % serves current content%",),
        cadence=timedelta(hours=6),
        description="The INTENT of the publishing schedule: the public "
        "surface's newly published content tracks the present, not the "
        "backlog. site_freshness proves cards flow; this proves the "
        "RIGHT cards flow. (Found 2026-09-01: mechanics green while "
        "publishing 18-day-old content past 25 fresher pending cards.)",
        verifier="verify_content_currency",
        params={
            # 7d = 2x the worst-case weekly curation cadence the health
            # checker documents (~4-5 curations/week). Tunable per spec.
            "current_days": 7,
            "window_hours": 24,
        },
    ),
    "skos_labels": ObjectiveSpec(
        name="skos_labels",
        dag=("clt_skos_admit", "clt_skos_label"),
        flows=("CltSkosAdmitFlow", "CltSkosLabelFlow"),
        cadence=timedelta(hours=6),
        description="SKOS labeling advances the labeled corpus",
        skeleton_check=(
            "SELECT count(*) FROM scheduled_tasks WHERE task_type IN "
            "('clt_skos_admit','clt_skos_label') AND error IS NULL "
            "AND completed_at > NOW() - INTERVAL '6 hours'"
        ),
    ),
    "tier_settle": ObjectiveSpec(
        name="tier_settle",
        dag=("tier_settle",),
        cadence=timedelta(hours=2),
        description="Hourly THS settle lands rows in signal_tier1",
        skeleton_check=(
            "SELECT count(*) FROM scheduled_tasks WHERE task_type='tier_settle' "
            "AND error IS NULL AND completed_at > NOW() - INTERVAL '2 hours'"
        ),
    ),
    "cognition": ObjectiveSpec(
        name="cognition",
        dag=("cognition_cycle",),
        cadence=timedelta(hours=8),
        description="Cognition cycles produce new thoughts",
        skeleton_check=(
            "SELECT count(*) FROM cognition_thoughts "
            "WHERE created_at > NOW() - INTERVAL '8 hours'"
        ),
    ),
}


class ObjectiveService:
    """Runs objective verifications; writes objective_verifications;
    updates the efficacy ledger."""

    def __init__(self, db_pool: Any, collection_service: Any = None) -> None:
        self._pool = db_pool
        self._collections = collection_service

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def verify(self, name: str) -> dict[str, Any]:
        """Verify one objective; returns the verdict payload."""
        spec = OBJECTIVES.get(name)
        if spec is None:
            raise ValueError(
                f"Unknown objective: {name!r}.\n"
                f"  Known: {', '.join(sorted(OBJECTIVES))}\n"
                "  Guru: #OBJ.00000001.UNKNOWN"
            )
        if spec.verifier:
            gates = await getattr(self, spec.verifier)(spec)
        elif spec.skeleton_check:
            gates = await self._verify_skeleton(spec)
        else:
            gates = [
                {
                    "gate": "declared",
                    "verdict": "inconclusive",
                    "evidence": "verifier pending",
                }
            ]
        return await self._record(spec, gates)

    async def verify_all(self) -> list[dict[str, Any]]:
        out = []
        for name in OBJECTIVES:
            try:
                out.append(await self.verify(name))
            except Exception as e:  # noqa: BLE001 — one objective must not block the rest
                logger.exception(f"objective {name} verification errored")
                out.append({"objective": name, "verdict": "error", "error": str(e)})
        return out

    # ------------------------------------------------------------------
    # Verifiers
    # ------------------------------------------------------------------

    async def _verify_skeleton(self, spec: ObjectiveSpec) -> list[dict[str, Any]]:
        """Skeleton verifier: the objective's DB footprint advanced
        in-window. Honest but shallow — full verifiers replace these."""
        async with self._pool.acquire() as conn:
            n = await conn.fetchval(spec.skeleton_check)
        ok = bool(n and int(n) > 0)
        return [
            {
                "gate": "footprint_advanced",
                "verdict": "pass" if ok else "fail",
                "evidence": f"rows_in_window={n}",
            }
        ]

    async def verify_site_freshness(self, spec: ObjectiveSpec) -> list[dict[str, Any]]:
        """The 3-way compare: DB truth vs KV read-back vs live page."""
        import aiohttp

        gates: list[dict[str, Any]] = []

        # Axis 1 — DB truth
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT max(published_at) AS newest,
                       (SELECT array_agg(card_id) FROM (
                           SELECT card_id FROM collections.cards
                           WHERE status = 'published'
                           ORDER BY published_at DESC LIMIT 20
                       ) t) AS recent_ids
                FROM collections.cards WHERE status = 'published'
                """
            )
            stale_after = await conn.fetchval(
                "SELECT NOW() - INTERVAL '1 second' * $1",
                2 * spec.cadence.total_seconds(),
            )
        newest = row["newest"]
        recent_ids = list(row["recent_ids"] or [])
        db_fresh = newest is not None and newest > stale_after
        gates.append(
            {
                "gate": "db_fresh",
                "verdict": "pass" if db_fresh else "fail",
                "evidence": f"newest_published_at={newest} threshold=2x{spec.cadence}",
            }
        )

        # Axis 2 — KV read-back (the same key sync_to_kv writes)
        kv_ids: set[str] = set()
        kv_verdict = "error"
        kv_evidence = ""
        try:
            if self._collections is None:
                raise RuntimeError("collection service unavailable")
            account_id, api_token, namespace_id = (
                self._collections._get_kv_credentials()
            )
            url = (
                f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
                f"/storage/kv/namespaces/{namespace_id}/values/published_cards"
            )
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={"Authorization": f"Bearer {api_token}"},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"KV GET {resp.status}")
                    payload = await resp.json(content_type=None)
            cards = payload.get("cards", payload) if isinstance(payload, dict) else payload
            kv_ids = {c.get("card_id") for c in cards if isinstance(c, dict)}
            missing = [cid for cid in recent_ids if cid not in kv_ids]
            kv_verdict = "pass" if not missing else "fail"
            kv_evidence = (
                f"kv_cards={len(kv_ids)} missing_recent={missing[:5]}"
                if missing
                else f"kv_cards={len(kv_ids)} all {len(recent_ids)} recent present"
            )
        except Exception as e:  # noqa: BLE001 — honest error verdict
            kv_verdict = "error"
            kv_evidence = f"KV read-back failed: {e}"
        gates.append(
            {"gate": "kv_coherent", "verdict": kv_verdict, "evidence": kv_evidence}
        )

        # Axis 3 — live page serves the newest card
        live_verdict = "error"
        live_evidence = ""
        try:
            newest_id = recent_ids[0] if recent_ids else None
            if newest_id is None:
                live_verdict = "fail"
                live_evidence = "no published cards in DB"
            else:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{PUBLIC_SITE}/cards/{newest_id}",
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        body = await resp.text()
                        ok = resp.status == 200 and len(body) > 500
                        live_verdict = "pass" if ok else "fail"
                        live_evidence = (
                            f"GET /cards/{newest_id} -> {resp.status}, "
                            f"{len(body)} bytes"
                        )
        except Exception as e:  # noqa: BLE001
            live_verdict = "error"
            live_evidence = f"live probe failed: {e}"
        gates.append(
            {"gate": "live_coherent", "verdict": live_verdict, "evidence": live_evidence}
        )
        return gates

    async def verify_content_currency(self, spec: ObjectiveSpec) -> list[dict[str, Any]]:
        """The schedule's INTENT: published content tracks the present.

        Three gates, all against `collections.cards.source_date` (the
        content's own date, e.g. arXiv submission), never `published_at`
        (our push time — that is site_freshness's axis, and measuring it
        alone let mechanics stay green while the surface aged):
        1. published_content_current — newest source_date among the
           window's publishes is within current_days.
        2. selection_favors_current — when the pending backlog CONTAINS
           current content, the window's publishes include some of it
           (the publisher must not starve fresh content while it exists).
        3. curation_inflow_current — the corpus's newest source_date is
           within current_days (is curation even ingesting the present?).
        """
        current_days = int(spec.params.get("current_days", 7))
        window_hours = int(spec.params.get("window_hours", 24))
        gates: list[dict[str, Any]] = []
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                  (SELECT max(source_date) FROM collections.cards
                    WHERE published_at > NOW() - INTERVAL '1 hour' * $1)
                    AS pub_newest,
                  (SELECT count(*) FROM collections.cards
                    WHERE published_at > NOW() - INTERVAL '1 hour' * $1
                      AND source_date > NOW() - INTERVAL '1 day' * $2)
                    AS pub_current,
                  (SELECT count(*) FROM collections.cards
                    WHERE status = 'pending'
                      AND source_date > NOW() - INTERVAL '1 day' * $2)
                    AS pending_current,
                  (SELECT max(source_date) FROM collections.cards)
                    AS corpus_newest
                """,
                window_hours,
                current_days,
            )
        pub_newest = row["pub_newest"]
        pub_current = int(row["pub_current"] or 0)
        pending_current = int(row["pending_current"] or 0)
        corpus_newest = row["corpus_newest"]

        threshold = f"within {current_days}d"
        g1_ok = pub_newest is not None and (
            await self._within_days(pub_newest, current_days)
        )
        gates.append(
            {
                "gate": "published_content_current",
                "verdict": "pass" if g1_ok else "fail",
                "evidence": (
                    f"newest source_date in last {window_hours}h publishes = "
                    f"{pub_newest} ({threshold} required)"
                ),
            }
        )
        if pending_current == 0:
            # No current content available — the publisher cannot be
            # blamed for selection; the failure (if any) is inflow's.
            g2_verdict = "inconclusive"
            g2_evidence = "no current pending content to select from"
        else:
            g2_verdict = "pass" if pub_current > 0 else "fail"
            g2_evidence = (
                f"{pending_current} current card(s) pending; "
                f"{pub_current} current card(s) published in window"
            )
        gates.append(
            {
                "gate": "selection_favors_current",
                "verdict": g2_verdict,
                "evidence": g2_evidence,
            }
        )
        g3_ok = corpus_newest is not None and (
            await self._within_days(corpus_newest, current_days)
        )
        gates.append(
            {
                "gate": "curation_inflow_current",
                "verdict": "pass" if g3_ok else "fail",
                "evidence": f"corpus newest source_date = {corpus_newest} ({threshold})",
            }
        )
        return gates

    async def _within_days(self, d: Any, days: int) -> bool:
        async with self._pool.acquire() as conn:
            return bool(
                await conn.fetchval(
                    "SELECT $1::date > (NOW() - INTERVAL '1 day' * $2)::date",
                    d,
                    days,
                )
            )

    # ------------------------------------------------------------------
    # Recording + resolution
    # ------------------------------------------------------------------

    async def _record(
        self, spec: ObjectiveSpec, gates: list[dict[str, Any]]
    ) -> dict[str, Any]:
        import json as _json

        from gaius.engine.fsm import FsmPosition
        from gaius.engine.services.efficacy_ledger import get_ledger

        passed = sum(1 for g in gates if g["verdict"] == "pass")
        errored = any(g["verdict"] == "error" for g in gates)
        if passed == len(gates):
            verdict = "pass"
        elif errored and passed == 0:
            verdict = "error"
        elif any(g["verdict"] == "fail" for g in gates):
            verdict = "fail"
        else:
            verdict = "inconclusive"
        accuracy = passed / len(gates) if gates else 0.0

        # Ledger: one objective: forecast per gate, at the objective's
        # DAG position. These are ground-truth-adjacent observations —
        # resolved gold-by-construction (the gate IS the measurement).
        ledger = get_ledger()
        if ledger is not None:
            for g in gates:
                fid = await ledger.record_forecast(
                    observer=f"objective:{spec.name}.{g['gate']}",
                    observer_kind="objective",
                    call_site="objective_service.verify",
                    proposition=f"objective {spec.name}/{g['gate']} holds",
                    verdict=g["verdict"],
                    evidence={"evidence": g["evidence"]},
                    position=FsmPosition(task_class=spec.dag[0] if spec.dag else None),
                )
                if fid is not None and g["verdict"] in ("pass", "fail"):
                    await ledger.resolve(
                        fid,
                        outcome=g["verdict"] == "pass",
                        tier="silver",
                        resolver=f"objective-measured:{spec.name}",
                    )
            # Silver-resolve upstream publish forecasts this verdict proves
            # or disproves ("the internal probe said the cards were served;
            # the objective says it did or didn't happen").
            if verdict in ("pass", "fail"):
                for pattern in spec.resolves:
                    n = await ledger.resolve_matching(
                        pattern,
                        outcome=verdict == "pass",
                        tier="silver",
                        resolver=f"objective:{spec.name}:{verdict}",
                        window_hours=2 * spec.cadence.total_seconds() / 3600,
                    )
                    if n:
                        logger.info(
                            f"objective {spec.name} {verdict} resolved {n} "
                            f"upstream forecast(s) matching {pattern!r}"
                        )

        # objective_verifications row (this table's first writer).
        run_id = uuid.uuid4().hex[:12]
        try:
            from gaius.rase.traceability import IdScheme, TraceableId

            thread_id = TraceableId.generate(scheme=IdScheme.RASE, prefix="verify").uri
        except Exception:  # noqa: BLE001 — vocabulary nicety, not load-bearing
            thread_id = f"rase://verify_{run_id}"
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO objective_verifications (
                    run_id, objective_name, objective_path, domain,
                    verdict, accuracy, reward, gates_total, gates_passed,
                    gate_results, thread_id, completed_at, kb_root
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,NOW(),$12)
                """,
                run_id,
                spec.name,
                f"objectives/{spec.name}",
                "site" if spec.name == "site_freshness" else "ops",
                verdict,
                accuracy,
                accuracy,  # GradedReward: proportion of gates passed
                len(gates),
                passed,
                _json.dumps(gates),
                thread_id,
                "",
            )

        if verdict == "fail":
            logger.warning(
                f"#OBJ.00000002.OBJFAIL objective {spec.name} FAILED "
                f"({passed}/{len(gates)} gates): "
                + "; ".join(f"{g['gate']}={g['verdict']}" for g in gates)
                + "\n  Surfaced by Nautilus T3 (objective-stale)."
                "\n  Try: /objective verify " + spec.name
            )

        return {
            "objective": spec.name,
            "run_id": run_id,
            "verdict": verdict,
            "accuracy": round(accuracy, 3),
            "gates": gates,
        }

    async def history(self, limit: int = 20) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT run_id, objective_name, verdict, accuracy,
                       gates_total, gates_passed, gate_results,
                       started_at, completed_at
                FROM objective_verifications
                ORDER BY started_at DESC
                LIMIT $1
                """,
                limit,
            )
        return [dict(r) for r in rows]
