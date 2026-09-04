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
from gaius.core.budgets import QUEUE_SHARE_APPLY_NET_S, REASONING_MAX_TOKENS

logger = logging.getLogger(__name__)

PUBLIC_SITE = "https://gaius.zndx.org"

# ── the published surface as a visitor reads it (2026-09-04) ───────────────
# The landing page renders each card as <a href="/cards/<id>" class="card">…
# <span class="card-date">Sep 3</span> — year-less for the current year,
# "Sep 27, 2025" otherwise. Pure functions, pinned by tests: the first parse
# of this page matched only dated years and misread 176 of 200 cards.
_CARD_RX = None
_DATE_RX = None
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def parse_card_date(text: str, today):
    """'Sep 3' → this year (or last, if that would be in the future);
    'Sep 27, 2025' → as written. None when unparseable."""
    import re as _re
    from datetime import date as _date

    global _DATE_RX
    if _DATE_RX is None:
        _DATE_RX = _re.compile(
            r"^\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?:,\s*(\d{4}))?\s*$"
        )
    m = _DATE_RX.match(text or "")
    if not m:
        return None
    month = _MONTHS.index(m.group(1)) + 1
    day = int(m.group(2))
    try:
        if m.group(3):
            return _date(int(m.group(3)), month, day)
        d = _date(today.year, month, day)
        return d if d <= today else _date(today.year - 1, month, day)
    except ValueError:
        return None


def surface_cards(html: str, today) -> list[tuple[str, Any]]:
    """Ordered (card_id, visible_date|None) for every card on the landing
    page, first occurrence wins — page order IS what the visitor sees."""
    import re as _re

    global _CARD_RX
    if _CARD_RX is None:
        _CARD_RX = _re.compile(
            r'<a href="/cards/(card_[0-9a-f]{12})" class="card">(.*?)</a>', _re.S
        )
    out: list[tuple[str, Any]] = []
    seen: set[str] = set()
    for m in _CARD_RX.finditer(html or ""):
        cid = m.group(1)
        if cid in seen:
            continue
        seen.add(cid)
        dm = _re.search(r'<span class="card-date">([^<]*)</span>', m.group(2))
        out.append((cid, parse_card_date(dm.group(1), today) if dm else None))
    return out


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
        description="FINAL SURFACED RESULT: the card links a visitor sees "
        "on gaius.zndx.org. Fresh and coherent across DB, KV, and the "
        "live page — DB/KV agreement is the intermediate forecast; the "
        "live page is what the user receives.",
        verifier="verify_site_freshness",
    ),
    "content_currency": ObjectiveSpec(
        name="content_currency",
        dag=("article_curate", "publish_cards", "feed_check"),
        flows=("ArticleCurationFlow",),
        resolves=("slot % serves current content%",),
        cadence=timedelta(hours=6),
        description="The INTENT of the publishing schedule, measured on the "
        "PUBLISHED SURFACE against the current date: the card dates a "
        "visitor reads at gaius.zndx.org today track the present, the top "
        "of the page is mostly current, and the surface refreshed within "
        "the slot cadence. Thresholds are what pg_cron promises (daily "
        "curate 09:07 UTC; slots 12/17/21/02 UTC); Airflow runs no gaius "
        "surface DAG (2026-09-04). site_freshness proves cards flow; this "
        "proves the RIGHT cards flow — as seen, not as stored. (2026-09-01: "
        "mechanics green while publishing 18-day-old content past 25 "
        "fresher pending cards. 2026-09-04: the DB-side selection gate could "
        "only ever be inconclusive — the curate publishes its own cards — "
        "so the gates moved to the surface.)",
        verifier="verify_content_currency",
        params={
            # What the visitor reads is compared to TODAY. Rationale (rule 3):
            # newest_days: article-curate-daily (09:07 UTC) promises new content
            #   every day; source dates are day-granular and lag the fetch by up
            #   to a day → the newest visible date must be within 2 days.
            "newest_days": 2,
            # current_days: 7d = 2x the worst-case weekly curation cadence the
            #   health checker documents (~4-5 curations/week).
            "current_days": 7,
            # band: one day's intended publishes = ~20 curate + (3+1+1+1) slot
            #   cards — the set a day's visitor is offered at the top.
            "band": 26,
            # min_current_share: the intended mix is ≈ 20 current : 6 slot
            #   (0.77); the gate floor is half of that — below 0.5 the slots are
            #   outweighing the curate or the curate did not run.
            "min_current_share": 0.5,
            # refresh_hours: slots at 12/17/21/02 UTC → longest gap 10 h
            #   (02→12); the next Fibonacci hour is 13.
            "refresh_hours": 13,
            "surface_url": "https://gaius.zndx.org/",
        },
    ),
    "prospects_intelligence": ObjectiveSpec(
        name="prospects_intelligence",
        dag=("prospects_check", "prospects_update"),
        flows=("ProspectsUpdateFlow",),
        resolves=("%user receives prospect briefs%",),
        cadence=timedelta(hours=36),
        description="Defined on the FINAL SURFACED RESULT (doctrine rule "
        "2): the prospect briefs the user opens are sufficient to the "
        "task — current, well-formed, and substantively informative per "
        "an explicit quality rubric whose FINAL CALL is the Overwatch "
        "ACP+Grok judge (LLM-as-Judge) reasoning about the brief text "
        "itself. The task: inform a rebalancing BOUNDARY decision under "
        "switching costs — for capital OR for a professional's scarce "
        "time, money, and energy (kb current/prospects/"
        "portfolio-theory.md — no-trade-region discipline; 'no action "
        "warranted' is a first-class, supported conclusion, never "
        "silence). Flow "
        "completion, task rows, file writes, and the local model's "
        "rubric self-score are FORECASTS resolved by that call, never "
        "gates. (Found 2026-09-02: flow died mid-DAG with a green task "
        "row and hollow briefs on the user surface; year audit: last "
        "decision-grade brief 2026-01-11.)",
        verifier="verify_prospects_intelligence",
        params={
            # 36h = daily-ish prospects cadence x 1.5 buffer.
            "window_hours": 36,
            # Deterministic rubric floor: a real Summary says something.
            "min_summary_chars": 40,
            # Title pathology guard: symbol should appear once or twice,
            # never as a repetition artifact ("(XOM)" x23, 2026-09-02).
            "max_symbol_repeats": 2,
            # Rubric final call is the Overwatch ACP+Grok judge
            # (LLM-as-Judge); at most this many briefs go to it per run.
            "rubric_sample_max": 3,
        },
    ),
    "skos_labels": ObjectiveSpec(
        name="skos_labels",
        dag=("clt_skos_admit", "clt_skos_label"),
        flows=("CltSkosAdmitFlow", "CltSkosLabelFlow"),
        cadence=timedelta(hours=6),
        description="SKOS labeling advances the labeled corpus",
        # (2026-09-04 16:17) `error IS NULL` counted DEFERRED ticks as work
        # done: the admit flow deferred 28 times in a row from 09:00 and this
        # skeleton passed throughout. A deferral is a clean row that did
        # nothing; only a completed run advances the corpus.
        skeleton_check=(
            "SELECT count(*) FROM scheduled_tasks WHERE task_type IN "
            "('clt_skos_admit','clt_skos_label') AND error IS NULL "
            "AND result->>'status' = 'completed' "
            "AND completed_at > NOW() - INTERVAL '6 hours'"
        ),
    ),
    # (2026-09-04 16:17) skos_labels' 6 h window would have passed through a
    # 5 h admit outage (today's ran 09:00–16:15 unseen). The admit tick is a
    # 15-min cadence: a completed run within 3 ticks — one designed
    # deferral tolerated — or the corpus is not being admitted.
    "skos_admission": ObjectiveSpec(
        name="skos_admission",
        dag=("clt_skos_admit",),
        flows=("CltSkosAdmitFlow",),
        cadence=timedelta(hours=1),
        description="The 15-min CLT/SKOS admit tick completes: a completed run within 45 min",
        skeleton_check=(
            "SELECT count(*) FROM scheduled_tasks WHERE task_type='clt_skos_admit' "
            "AND error IS NULL AND result->>'status' = 'completed' "
            "AND completed_at > NOW() - INTERVAL '45 minutes'"
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
    # (2026-09-04) The two flows that replaced the engine's private timers.
    "market_buffer": ObjectiveSpec(
        name="market_buffer",
        dag=("fmp_roll",),
        flows=("FmpMarketBufferFlow",),
        cadence=timedelta(hours=2),
        description="The prospects FIFO tracks the market: live FMP rows newer than 2h",
        skeleton_check=(
            "SELECT count(*) FROM buffer_entries "
            "WHERE buffer = 'prospects' AND compacted_at IS NULL "
            "AND created_at > NOW() - INTERVAL '2 hours'"
        ),
    ),
    "ambient_synthesis": ObjectiveSpec(
        name="ambient_synthesis",
        dag=("ambient_synthesis",),
        flows=("AmbientSynthesisFlow",),
        cadence=timedelta(hours=2),
        description="Ambient synthesis lands: a thinking synthesis episode in cognition_buffer within 2h",
        skeleton_check=(
            "SELECT count(*) FROM cognition_buffer "
            "WHERE kind = 'synthesis' AND created_at > NOW() - INTERVAL '2 hours'"
        ),
    ),
    # (2026-09-04) The arbiter objective (resource-intents step 10). Every
    # declared phase intent is a FORECAST that the federation's arbiter will
    # apply it; this objective resolves those against what YuniKorn actually
    # guarantees. Silver from Signals' records + the cluster ConfigMap (both
    # outside the emitter's bookkeeping); a sustained FAIL is what Nautilus
    # escalates to Overwatch. Not task-bearing (dag=()): it verifies a
    # protocol, not a flow.
    "queue_share_arbitration": ObjectiveSpec(
        name="queue_share_arbitration",
        dag=(),
        cadence=timedelta(hours=2),
        description=(
            "Applied YuniKorn floors match the live declared intents: no record stuck "
            "short of APPLIED past the apply net; guaranteed GPU per leaf == merge of "
            "live declared floors; every held phase intent has an APPLIED record"
        ),
        verifier="verify_queue_share_arbitration",
        params={
            "apply_net_s": QUEUE_SHARE_APPLY_NET_S,
            "gpu_key": "federation.zndx.org/gpu",
            "namespace": "yunikorn",
            "configmap": "yunikorn-configs",
            "leaves": [
                "root.internal.inference.heavy",
                "root.internal.inference.light",
                "root.internal.inference.medium",
                "root.internal.inference.extract",
            ],
            "rationale": (
                "merge semantics mirror signals.engine.queue_share.merge_floors: declared "
                "floor when present, else the record's share guaranteed; max per leaf across "
                "live APPLIED records; leaves with no live record expect 0"
            ),
        },
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
        """The schedule's INTENT, measured on the PUBLISHED SURFACE.

        (2026-09-04, user reframe) What a visitor sees at gaius.zndx.org
        today is the basis for currency; the thresholds are what the
        schedules PROMISE (pg_cron: article-curate-daily 09:07 UTC;
        publish-cards at 12/17/21/02 UTC. Airflow runs no gaius surface
        DAG as of this date). Every gate parses the live landing page —
        the ordered cards and the `card-date` each renders (year-less for
        the current year, "Mon D, YYYY" otherwise) — against the current
        date. Nothing here reads `collections.cards` to decide currency;
        the DB is consulted once, to date the surface's own top card.

        1. surface_newest_current — the newest date a visitor can read is
           within `newest_days` of today (daily curate + day-granular
           source dates ⇒ 2).
        2. surface_band_current — of the first `band` cards (one day's
           intended publishes: ~20 curate + 3+1+1+1 slots = 26), at least
           `min_current_share` are dated within `current_days`.
        3. surface_refreshed_within_intent — the top card was published
           within `refresh_hours` (the slots' longest gap is 10 h, 02→12
           UTC; the next Fibonacci hour is 13). A top card unknown to the
           DB is a surface/DB incoherence and fails.

        The former `selection_favors_current` gate is gone: with the curate
        publishing its own cards there is never current pending content,
        so it could only ever return inconclusive. Selection now shows up
        where visitors see it — in gate 2's band share. Corpus inflow is
        reported as diagnosis (rule 8: name the DAG stage), not a gate.
        """
        import aiohttp

        today = await self._today()
        newest_days = int(spec.params.get("newest_days", 2))
        current_days = int(spec.params.get("current_days", 7))
        band = int(spec.params.get("band", 26))
        min_share = float(spec.params.get("min_current_share", 0.5))
        refresh_hours = int(spec.params.get("refresh_hours", 13))
        url = str(spec.params.get("surface_url") or f"{PUBLIC_SITE}/")
        gates: list[dict[str, Any]] = []

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    status = resp.status
                    html = await resp.text()
            if status != 200:
                raise RuntimeError(f"GET {url} -> {status}")
            cards = surface_cards(html, today)
            if not cards:
                raise RuntimeError(f"no cards parsed from {url} ({len(html)} bytes)")
        except Exception as e:  # noqa: BLE001 — honest error verdict on every gate
            ev = f"surface unreadable: {e}"
            return [
                {"gate": g, "verdict": "error", "evidence": ev}
                for g in (
                    "surface_newest_current",
                    "surface_band_current",
                    "surface_refreshed_within_intent",
                )
            ]

        # Diagnosis text (upstream DAG stage), attached to gate 1's evidence.
        async with self._pool.acquire() as conn:
            corpus_newest = await conn.fetchval(
                "SELECT max(source_date) FROM collections.cards"
            )
            top_id = cards[0][0]
            top_pub = await conn.fetchval(
                "SELECT published_at FROM collections.cards WHERE card_id = $1",
                top_id,
            )
            now_ts = await conn.fetchval("SELECT NOW()")

        dated = [d for _, d in cards if d is not None]
        newest = max(dated) if dated else None
        g1_ok = newest is not None and (today - newest).days <= newest_days
        gates.append(
            {
                "gate": "surface_newest_current",
                "verdict": "pass" if g1_ok else "fail",
                "evidence": (
                    f"newest visible card date = {newest} (today {today}; within "
                    f"{newest_days}d required: daily curate + day-granular source "
                    f"dates); {len(dated)}/{len(cards)} cards dated; corpus newest "
                    f"source_date = {corpus_newest}"
                    + ("" if g1_ok or corpus_newest is None or (today - corpus_newest).days <= current_days
                       else " — DAG stage: curation inflow (article_curate) is stale")
                ),
            }
        )

        head = cards[:band]
        head_current = sum(
            1 for _, d in head if d is not None and (today - d).days <= current_days
        )
        share = head_current / len(head) if head else 0.0
        g2_ok = share >= min_share
        gates.append(
            {
                "gate": "surface_band_current",
                "verdict": "pass" if g2_ok else "fail",
                "evidence": (
                    f"{head_current}/{len(head)} of the first {band} cards dated within "
                    f"{current_days}d (share {share:.2f}; ≥ {min_share:.2f} required — "
                    f"intent ≈ 20 curate : 6 slot publishes per day)"
                    + ("" if g2_ok else " — DAG stage: article_curate's own selection "
                       "returned mostly non-current sources (2026-09-04: 10 of its 20 "
                       "were within 7d), or publish_cards' pool picks are outweighing "
                       "it, or the curate did not run")
                ),
            }
        )

        if top_pub is None:
            g3_verdict, g3_ev = "fail", (
                f"top card {top_id} on the surface is unknown to the DB — "
                "surface/DB incoherence (DAG stage: publish_cards KV sync)"
            )
        else:
            age_h = (now_ts - top_pub).total_seconds() / 3600.0
            g3_verdict = "pass" if age_h <= refresh_hours else "fail"
            g3_ev = (
                f"top card {top_id} published {age_h:.1f}h ago (≤ {refresh_hours}h "
                f"required: slots at 12/17/21/02 UTC, longest gap 10h → next "
                f"Fibonacci hour 13)"
                + ("" if g3_verdict == "pass" else " — DAG stage: publish_cards slot "
                   "missed or deferred")
            )
        gates.append(
            {
                "gate": "surface_refreshed_within_intent",
                "verdict": g3_verdict,
                "evidence": g3_ev,
            }
        )
        return gates

    async def _today(self):
        async with self._pool.acquire() as conn:
            return await conn.fetchval("SELECT (NOW() AT TIME ZONE 'UTC')::date")

    async def verify_prospects_intelligence(
        self, spec: ObjectiveSpec
    ) -> list[dict[str, Any]]:
        """Objective on the FINAL SURFACED RESULT (doctrine rule 2).

        The user's surface is the prospect briefs they open under
        kb/scratch/. Every gate evaluates THAT artifact against an
        explicit quality rubric:

        1. briefs_surfaced — briefs the user can open exist within the
           cadence window.
        2. rubric_wellformed — deterministic rubric items per brief:
           Summary section >= min_summary_chars; title free of
           repetition artifacts (a symbol repeated more than
           max_symbol_repeats times is generation pathology, not a
           title).
        3. rubric_sufficiency — model-scored rubric on the brief text
           the reader sees: states what changed, explains why it merits
           (or doesn't merit) attention, recommendation consistent with
           the stated evidence, reads as finished prose. Mean score
           must reach sufficiency_threshold.

        Flow completion is NOT a gate. It is a FORECAST that the user
        receives the intended result — recorded here from Metaflow's
        own store (heuristic:prospects.flow_completed) and
        silver-resolved by this objective's surface verdict via
        spec.resolves.
        """
        import glob as _glob
        import json as _json
        import os as _os
        import re as _re
        import time as _time

        window_h = int(spec.params.get("window_hours", 36))
        min_chars = int(spec.params.get("min_summary_chars", 40))
        max_repeats = int(spec.params.get("max_symbol_repeats", 2))
        gates: list[dict[str, Any]] = []

        # FORECAST (not a gate): flow-level delivery claim from
        # Metaflow's own store. The surface verdict resolves it.
        flow_verdict, flow_evidence = "error", ""
        try:
            import asyncpg

            mf_dsn = _os.environ.get(
                "GAIUS_METAFLOW_DB_URL",
                "postgres://signals:signals@127.0.0.1:5455/metaflow",
            )
            conn = await asyncpg.connect(mf_dsn, timeout=15)
            try:
                row = await conn.fetchrow(
                    """
                    SELECT r.run_number,
                           EXISTS (
                               SELECT 1 FROM steps_v3 s
                               WHERE s.flow_id = r.flow_id
                                 AND s.run_number = r.run_number
                                 AND s.step_name = 'end'
                           ) AS reached_end
                    FROM runs_v3 r
                    WHERE r.flow_id = 'ProspectsUpdateFlow'
                      AND to_timestamp(r.ts_epoch / 1000)
                          > NOW() - INTERVAL '1 hour' * $1
                    ORDER BY r.ts_epoch DESC
                    LIMIT 1
                    """,
                    window_h,
                )
            finally:
                await conn.close()
            if row is None:
                flow_verdict = "fail"
                flow_evidence = f"no ProspectsUpdateFlow run in {window_h}h"
            else:
                flow_verdict = "pass" if row["reached_end"] else "fail"
                flow_evidence = (
                    f"run {row['run_number']}: "
                    + ("reached end" if row["reached_end"] else "died mid-DAG")
                )
        except Exception as e:  # noqa: BLE001 — honest error verdict
            flow_evidence = f"metaflow store unreachable: {e}"
        from gaius.engine.fsm import FsmPosition
        from gaius.engine.services.efficacy_ledger import get_ledger

        ledger = get_ledger()
        if ledger is not None:
            await ledger.record_forecast(
                observer="heuristic:prospects.flow_completed",
                observer_kind="heuristic",
                call_site="objective_service.verify_prospects_intelligence",
                proposition=(
                    "user receives prospect briefs from ProspectsUpdateFlow"
                ),
                verdict=flow_verdict,
                evidence={"evidence": flow_evidence},
                position=FsmPosition(
                    task_class="prospects_update",
                    flow_type="ProspectsUpdateFlow",
                ),
            )

        # Gate 1 — the surface exists and is current.
        from gaius.engine.services.agenda_notes import kb_root_from_env

        kb = kb_root_from_env()
        cutoff = _time.time() - window_h * 3600
        files = sorted(
            f
            for f in _glob.glob(str(kb / "scratch" / "*" / "*prospect_*.md"))
            if _os.path.getmtime(f) > cutoff
        )
        if not files:
            gates.append(
                {"gate": "briefs_surfaced", "verdict": "fail",
                 "evidence": f"no prospect briefs written in {window_h}h "
                 f"(flow forecast: {flow_evidence})"}
            )
            gates.append(
                {"gate": "rubric_wellformed", "verdict": "inconclusive",
                 "evidence": "no briefs on the surface to assess"}
            )
            gates.append(
                {"gate": "rubric_sufficiency", "verdict": "inconclusive",
                 "evidence": "no briefs on the surface to score"}
            )
            return gates
        gates.append(
            {"gate": "briefs_surfaced", "verdict": "pass",
             "evidence": f"{len(files)} brief(s) within {window_h}h"}
        )

        # Gate 2 — deterministic rubric items on each brief.
        malformed: list[str] = []
        readable: list[tuple[str, str]] = []  # (basename, text) for gate 3
        for f in files:
            base = _os.path.basename(f)
            try:
                with open(f, encoding="utf-8") as fh:
                    text = fh.read()
            except OSError:
                malformed.append(f"{base} (unreadable)")
                continue
            problems = []
            m = _re.search(
                r"^## Summary\s*\n(.*?)(?=^## |\Z)", text,
                _re.MULTILINE | _re.DOTALL,
            )
            body = (m.group(1) if m else "").strip()
            if len(body) < min_chars:
                problems.append("empty Summary")
            title = next(
                (ln for ln in text.splitlines() if ln.startswith("# ")), ""
            )
            symbols = _re.findall(r"\(([A-Z]{1,6})\)", title)
            worst = max(
                (symbols.count(s) for s in set(symbols)), default=0
            )
            if worst > max_repeats:
                problems.append(f"title repetition artifact (x{worst})")
            if problems:
                malformed.append(f"{base} ({', '.join(problems)})")
            else:
                readable.append((base, text))
        gates.append(
            {
                "gate": "rubric_wellformed",
                "verdict": "pass" if not malformed else "fail",
                "evidence": (
                    f"{len(files)} brief(s), all well-formed"
                    if not malformed
                    else f"{len(malformed)}/{len(files)} malformed: "
                    + "; ".join(malformed[:5])
                ),
            }
        )

        # Gate 3 — sufficiency per rubric. The LOCAL model's score is a
        # FORECAST; the FINAL CALL is the Overwatch ACP+Grok judge
        # (LLM-as-Judge) reasoning about the artifact the reader sees,
        # from outside the trust boundary (doctrine rule 6). Brier
        # propagation follows the judge's call. Fail-closed: judge
        # unavailable => error verdict, never a thinking fallback.
        if not readable:
            gates.append(
                {"gate": "rubric_sufficiency", "verdict": "inconclusive",
                 "evidence": "no well-formed briefs to score"}
            )
            return gates
        sample = readable[: int(spec.params.get("rubric_sample_max", 3))]
        rubric = (
            "PRIMARY — classical portfolio optimization (sufficiency "
            "requires these; the complement below adds credit and can "
            "tip a borderline call, but cannot rescue a brief that "
            "fails the primary focus):\n"
            "1. change: states concretely what changed or is new for the "
            "prospect.\n"
            "2. attention: explains why this merits (or does not merit) "
            "action — 'no action warranted' is a first-class conclusion "
            "when stated with support (no-trade-region discipline: most "
            "drift should NOT trigger a trade).\n"
            "3. consistency: recommendation/conviction is consistent "
            "with the evidence stated, framed as a rebalancing boundary "
            "judgment — does this evidence move the position toward or "
            "across its tolerance band, net of switching costs?\n"
            "4. finish: reads as finished prose — no placeholder text, "
            "repetition artifacts, or empty sections.\n"
            "HETERODOX COMPLEMENT — attention portfolios (generally "
            "follows the primary analysis rather than replacing it):\n"
            "5. allocation: translates the finding for a professional "
            "allocating scarce time, money, and energy (e.g. sales "
            "activities): whose cadence — daily, weekly, quarterly — "
            "does this touch, or explicitly nobody's.\n"
            "6. framing: the structure serves the content. Leading with "
            "an opportunity is WELCOME when the reasoning supports it — "
            "credit well-reasoned agent decisions to headline "
            "opportunities as they present themselves. Judge structural "
            "and framing diversity on whether the choice is "
            "well-reasoned, never on conformity to a house template; "
            "intellectual quality standards are unchanged.\n"
        )
        blocks = "\n\n".join(
            f"--- {base} ---\n{text[:4000]}" for base, text in sample
        )

        # Internal forecast: thinking self-scores the surface. Recorded,
        # never load-bearing — its Brier accrues against the judge.
        fid_local = None
        local_note = "thinking self-score unavailable"
        try:
            from gaius.client.engine_client import Message, get_engine_client

            engine = await get_engine_client()
            completion = await engine.complete(
                [Message(role="user", content=(
                    "Score whether these prospect intelligence briefs, as "
                    "a set, are sufficient for a reader per this rubric "
                    "(each item 0 or 1):\n" + rubric +
                    "\nReply with ONLY a JSON object:\n"
                    '{"sufficient": true, "items": {"change": 0, '
                    '"attention": 0, "consistency": 0, "finish": 0, '
                    '"allocation": 0, "framing": 0}, '
                    '"note": "<one line>", "confidence": 0.0}\n\n'
                    f"Briefs:\n\n{blocks}"
                ))],
                model="thinking",
                temperature=0.1,
                max_tokens=REASONING_MAX_TOKENS,
            )
            out = (completion.content or "").strip()
            jm = _re.search(r"\{.*\}", out, _re.DOTALL)
            if not jm:
                raise ValueError("no JSON in thinking self-score")
            obj = _json.loads(jm.group(0))
            local_ok = bool(obj.get("sufficient"))
            conf = max(0.0, min(1.0, float(obj.get("confidence", 0.5))))
            local_note = (
                f"thinking forecast: "
                f"{'sufficient' if local_ok else 'insufficient'} "
                f"conf={conf:.2f}"
            )
            if ledger is not None:
                fid_local = await ledger.record_forecast(
                    observer="judge:thinking-rubric",
                    observer_kind="judge",
                    call_site=(
                        "objective_service.verify_prospects_intelligence"
                    ),
                    proposition=(
                        f"{spec.name} surfaced briefs are sufficient "
                        "per rubric"
                    ),
                    verdict="pass" if local_ok else "fail",
                    p=conf if local_ok else 1.0 - conf,
                    evidence={
                        "items": obj.get("items"),
                        "note": str(obj.get("note", ""))[:200],
                    },
                    model_id="thinking",
                    position=FsmPosition(
                        task_class="prospects_update",
                        flow_type="ProspectsUpdateFlow",
                    ),
                )
        except Exception as e:  # noqa: BLE001 — a forecast, not a gate
            logger.info(f"thinking rubric self-score skipped: {e}")

        # Final call — Overwatch ACP+Grok judge on the same artifacts.
        from gaius.engine.services.overwatch_judge import get_judge

        result = await get_judge().judge_rubric(
            objective=spec.name,
            surface=(
                f"prospect briefs under kb/scratch "
                f"({len(sample)}/{len(files)} in window)"
            ),
            rubric=rubric,
            artifacts=sample,
        )
        if result.get("status") != "verdict":
            gates.append(
                {"gate": "rubric_sufficiency", "verdict": "error",
                 "evidence": (
                     f"judge {result.get('status')}: "
                     f"{str(result.get('reason', ''))[:160]} "
                     f"(fail-closed, no local fallback; {local_note})"
                 )}
            )
            return gates
        v = result["verdict"]
        sufficient = bool(v.get("sufficient"))
        gates.append(
            {
                "gate": "rubric_sufficiency",
                "verdict": "pass" if sufficient else "fail",
                "authority": "overwatch-grok",
                "evidence": (
                    f"judge FINAL CALL: "
                    f"{'sufficient' if sufficient else 'insufficient'} "
                    f"conf={v.get('confidence')} items={v.get('items')} — "
                    f"{str(v.get('note', ''))[:160]} [{local_note}]"
                ),
            }
        )
        # The judge's call resolves the local forecast gold — Brier
        # propagation per doctrine.
        if ledger is not None and fid_local is not None:
            await ledger.resolve(
                fid_local,
                outcome=sufficient,
                tier="gold",
                resolver=f"overwatch-grok-rubric:{spec.name}",
            )
        return gates

    async def verify_queue_share_arbitration(
        self, spec: ObjectiveSpec
    ) -> list[dict[str, Any]]:
        """The arbiter is honest — three gates against sources outside the
        emitter's own bookkeeping:

        1. records_settled — no LIVE record (valid, not superseded/rejected) is
           stuck in RECORDED/APPLYING past the apply net.
        2. floors_applied — YuniKorn's guaranteed GPU per leaf (the cluster
           ConfigMap) equals the merge of live APPLIED declared floors (max per
           leaf; legacy records fall back to their share's guaranteed).
        3. intents_honoured — every phase intent this engine still holds
           (queue_share._PHASE_SHARES) has a live APPLIED record.
        """
        import asyncio
        import subprocess
        import time

        import yaml

        from gaius.engine import queue_share as qs
        from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2 as spb

        gpu_key = str(spec.params.get("gpu_key", "federation.zndx.org/gpu"))
        net_s = int(spec.params.get("apply_net_s", QUEUE_SHARE_APPLY_NET_S))
        leaves = [str(x) for x in (spec.params.get("leaves") or [])]
        ns = str(spec.params.get("namespace", "yunikorn"))
        cm = str(spec.params.get("configmap", "yunikorn-configs"))
        gate_names = ("records_settled", "floors_applied", "intents_honoured")

        try:
            # Live records are hours old at most (the engine restarts daily);
            # a 48 h window bounds the arbiter's work per call.
            records = await asyncio.to_thread(
                qs.list_queue_share_requests,
                peer=qs.PEER,
                since_ns=time.time_ns() - 48 * 3_600 * 1_000_000_000,
                limit=2000,
                timeout_s=10.0,
            )
        except Exception as e:  # noqa: BLE001 — an error verdict, never a guess
            ev = f"ListQueueShareRequests: {e}"
            return [{"gate": g, "verdict": "error", "evidence": ev} for g in gate_names]
        if not records:
            # The helper returns [] for a transient too (Signals not ready /
            # deadline). While this engine is up, thinking's standing record
            # is always live, so "no records" is "no answer": explicitly
            # unmeasurable, never a pass. (Found 2026-09-04 05:54: the first
            # in-engine run passed vacuously on records=0 during boot.)
            ev = (
                "ListQueueShareRequests returned no records — Signals not ready or "
                "deadline; thinking's standing record should always be live"
            )
            return [{"gate": g, "verdict": "inconclusive", "evidence": ev} for g in gate_names]

        now_ns = time.time_ns()
        applying = getattr(spb, "QUEUE_SHARE_APPLYING", 5)
        by_id: dict[str, Any] = {}
        for r in records:
            rid = r.request.request_id
            if rid not in by_id or r.recorded_at_ns > by_id[rid].recorded_at_ns:
                by_id[rid] = r

        def _live(r: Any) -> bool:
            vu = int(r.request.valid_until_ns or 0)
            return r.state not in (spb.QUEUE_SHARE_SUPERSEDED, spb.QUEUE_SHARE_REJECTED) and (
                vu == 0 or vu > now_ns
            )

        live = [r for r in by_id.values() if _live(r)]
        stuck = [
            r
            for r in live
            if r.state in (spb.QUEUE_SHARE_RECORDED, applying)
            and (now_ns - int(r.recorded_at_ns)) > net_s * 1_000_000_000
        ]
        gates: list[dict[str, Any]] = [
            {
                "gate": "records_settled",
                "verdict": "fail" if stuck else "pass",
                "evidence": (
                    f"records={len(by_id)} live={len(live)} stuck_past_{net_s}s="
                    + str(
                        [
                            (
                                r.request.request_id[-8:],
                                qs._state_name(spb, r.state),
                                (r.apply_error or "")[:60],
                            )
                            for r in stuck
                        ][:6]
                    )
                ),
            }
        ]

        # Expected floors: merge of live APPLIED records (arbiter semantics).
        expected: dict[str, int] = {leaf: 0 for leaf in leaves}
        for r in live:
            if r.state != spb.QUEUE_SHARE_APPLIED:
                continue
            shares = {s.queue: s for s in r.request.shares}
            for w in r.request.workloads:
                if w.HasField("floor"):
                    eff = int(w.floor)
                else:
                    s = shares.get(w.queue)
                    eff = int(s.guaranteed.quantities.get(gpu_key, 0)) if s is not None else 0
                expected[w.queue] = max(int(expected.get(w.queue, 0)), eff)

        def _guarantees(yaml_text: str) -> dict[str, int]:
            """guaranteed[gpu_key] per queue FQN from a YuniKorn queues.yaml."""
            doc = yaml.safe_load(yaml_text) or {}
            res: dict[str, int] = {}

            def walk(node: dict[str, Any], prefix: str) -> None:
                name = str(node.get("name") or "")
                fqn = f"{prefix}.{name}" if prefix else name
                g = ((node.get("resources") or {}).get("guaranteed") or {}).get(gpu_key)
                if g is not None:
                    res[fqn] = int(str(g))
                for ch in node.get("queues") or []:
                    walk(ch, fqn)

            for part in doc.get("partitions") or []:
                for q in part.get("queues") or []:
                    walk(q, "")
            return res

        def _applied() -> dict[str, int]:
            out = subprocess.run(
                ["kubectl", "-n", ns, "get", "configmap", cm, "-o", "jsonpath={.data.queues\\.yaml}"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if out.returncode != 0:
                raise RuntimeError((out.stderr or "kubectl failed").strip()[:200])
            return _guarantees(out.stdout)

        def _baseline() -> dict[str, int]:
            """The arbiter merges over the SoR template's guarantees (Signals'
            baseline_guarantees reads the same file); mirror it, never assume 0."""
            import os
            from pathlib import Path

            root = (os.environ.get("SIGNALS_ROOT") or "").strip()
            if not root:
                raise RuntimeError("SIGNALS_ROOT unset — cannot read the federation queue template")
            p = Path(root) / str(spec.params.get("baseline_yaml", "config/scheduler/federation-queues.yaml"))
            if not p.is_file():
                raise RuntimeError(f"baseline queues missing: {p}")
            return _guarantees(p.read_text(encoding="utf-8"))

        try:
            applied = await asyncio.to_thread(_applied)
            baseline = await asyncio.to_thread(_baseline)
        except Exception as e:  # noqa: BLE001
            gates.append(
                {"gate": "floors_applied", "verdict": "error", "evidence": f"{ns}/{cm} or template: {e}"}
            )
        else:
            for leaf, g in baseline.items():
                if leaf in leaves or leaf in expected:
                    expected[leaf] = max(int(expected.get(leaf, 0)), int(g))
            compare = sorted(set(leaves) | set(expected))
            mismatch = [
                (leaf, expected.get(leaf, 0), applied.get(leaf, 0))
                for leaf in compare
                if int(expected.get(leaf, 0)) != int(applied.get(leaf, 0))
            ]
            gates.append(
                {
                    "gate": "floors_applied",
                    "verdict": "fail" if mismatch else "pass",
                    "evidence": (
                        "applied=" + str({k.rsplit('.', 1)[-1]: applied.get(k, 0) for k in compare})
                        + " expected=" + str({k.rsplit('.', 1)[-1]: expected.get(k, 0) for k in compare})
                        + (f" mismatch(leaf,expected,applied)={mismatch}" if mismatch else "")
                    ),
                }
            )

        held = dict(qs._PHASE_SHARES)
        missing = []
        for (owner_wid, workload), (rid, leaf) in held.items():
            rec = by_id.get(rid)
            if rec is None or not _live(rec) or rec.state != spb.QUEUE_SHARE_APPLIED:
                missing.append(
                    (owner_wid, workload, leaf.rsplit(".", 1)[-1], qs._state_name(spb, rec.state) if rec else "no-record")
                )
        gates.append(
            {
                "gate": "intents_honoured",
                "verdict": "fail" if missing else "pass",
                "evidence": f"held={len(held)} not_applied={missing[:6]}",
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
        # A gate whose verdict was rendered by the Overwatch ACP+Grok
        # judge carries independent authority (doctrine rule 6): its
        # resolutions — and the upstream propagation it anchors — are
        # GOLD, not silver.
        judge_backed = any(
            g.get("authority") == "overwatch-grok" for g in gates
        )
        ledger = get_ledger()
        if ledger is not None:
            for g in gates:
                gate_gold = g.get("authority") == "overwatch-grok"
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
                        tier="gold" if gate_gold else "silver",
                        resolver=(
                            f"overwatch-grok-rubric:{spec.name}"
                            if gate_gold
                            else f"objective-measured:{spec.name}"
                        ),
                    )
            # Resolve upstream forecasts this verdict proves or disproves
            # ("the internal probe said the user would receive the result;
            # the objective says it did or didn't happen"). Gold when the
            # verdict is anchored by the independent judge, else silver.
            if verdict in ("pass", "fail"):
                tier = "gold" if judge_backed else "silver"
                for pattern in spec.resolves:
                    n = await ledger.resolve_matching(
                        pattern,
                        outcome=verdict == "pass",
                        tier=tier,
                        resolver=(
                            f"{'overwatch' if judge_backed else 'objective'}"
                            f":{spec.name}:{verdict}"
                        ),
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
