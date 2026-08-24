"""Write Agenda zettels from scheduled surfaces.

Intents: brief (letter/memo for an executive), reminder (shared
suggestion list), session (catch-up with a colleague; headlines in
the calendar description).

Emit is observability: a failed write is logged with a guru and must
not raise into the task that produced the surface. Do not invent
filings, holders, or news that the clocks did not produce.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from gaius.engine.services.agenda_notes import (
    AgendaError,
    AgendaItem,
    create_item,
    find_by_slug,
    kb_root_from_env,
    skewer,
    update_item,
)

logger = logging.getLogger(__name__)

GURU_EMITFAIL = (
    "Agenda emit failed.\n"
    "  Guru: #AG.00000005.EMITFAIL\n"
    "  Try: confirm GAIUS_KB_ROOT and /agenda cards"
)


def upsert(
    *,
    kind: str,
    title: str,
    body: str,
    now: datetime,
    starts: str = "",
    ends: str = "",
    tags: list[str] | None = None,
    pin: bool = False,
    intent: str = "",
    with_whom: str = "",
    slug: str = "",
    root: Path | None = None,
) -> AgendaItem | None:
    """Create or rewrite the card for this day's slug (no twins)."""
    try:
        kb = root or kb_root_from_env()
        day = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
        key = slug or skewer(title, kind)
        existing = find_by_slug(kb, day, key)
        if existing is not None:
            rel = str(existing.relative_to(kb)).replace("\\", "/")
            return update_item(
                kb,
                rel,
                kind=kind,
                title=title,
                body=body,
                starts=starts,
                ends=ends,
                tags=list(tags or []),
                pin=pin,
                intent=intent,
                with_whom=with_whom,
            )
        return create_item(
            kb,
            kind=kind,
            title=title,
            body=body,
            starts=starts,
            ends=ends,
            tags=tags or [],
            pin=pin,
            now=now,
            intent=intent,
            with_whom=with_whom,
        )
    except (AgendaError, OSError) as exc:
        logger.error("%s\n  cause: %s", GURU_EMITFAIL, exc)
        return None


def emit(
    *,
    kind: str,
    title: str,
    body: str,
    now: datetime,
    starts: str = "",
    ends: str = "",
    tags: list[str] | None = None,
    pin: bool = False,
    intent: str = "",
    with_whom: str = "",
    root: Path | None = None,
) -> AgendaItem | None:
    """Back-compat alias for upsert (rewrite if the day's skewer exists)."""
    return upsert(
        kind=kind,
        title=title,
        body=body,
        now=now,
        starts=starts,
        ends=ends,
        tags=tags,
        pin=pin,
        intent=intent,
        with_whom=with_whom,
        root=root,
    )


def _next_session_slot(now: datetime) -> datetime:
    slot = now.astimezone(timezone.utc).replace(
        hour=13, minute=0, second=0, microsecond=0
    )
    if now.astimezone(timezone.utc) >= slot:
        slot = slot + timedelta(days=1)
    return slot


def emit_prospects_update(result: dict[str, Any], root: Path | None = None) -> AgendaItem | None:
    """Error → reminder. Completed filings → session. Else brief."""
    now = datetime.now(timezone.utc)
    symbols = result.get("symbols") or []
    status = result.get("status") or ("error" if result.get("error") else "unknown")
    filings = result.get("new_filings_count")
    err = (result.get("error") or "").strip()
    sym = ", ".join(str(s) for s in symbols) or "(none)"

    if err or status == "error":
        body = (
            f"Prospects update failed ({status}).\n\n"
            f"Symbols: {sym}.\n\n"
            f"{err[:400]}\n"
            "\n"
            "- [ ] Re-admit on a prospects-update claim, not the standing "
            "article-curate pod\n"
        )
        return upsert(
            kind="list",
            title="Prospects update failed",
            body=body,
            now=now,
            tags=["prospects", "ops"],
            intent="reminder",
            root=root,
        )

    if filings:
        start = _next_session_slot(now)
        ends = start + timedelta(minutes=30)
        starts_s = start.isoformat()
        ends_s = ends.isoformat()
        brief = (
            f"Walk {filings} new FMP filing(s) on {sym}.\n"
            "Do not treat an empty 13F cache as no change "
            "(institutional-ownership is 402 on this key).\n"
        )
        return upsert(
            kind="event",
            title="Prospects filings session",
            body=brief,
            now=start,
            starts=starts_s,
            ends=ends_s,
            tags=["prospects", "watchlist"],
            intent="session",
            with_whom="agents",
            root=root,
        )

    body = (
        f"Prospects update {status}. Symbols: {sym}. "
        "No new filing count — nothing to book.\n"
    )
    return upsert(
        kind="note",
        title="Prospects update",
        body=body,
        now=now,
        tags=["prospects", "watchlist"],
        intent="brief",
        root=root,
    )


def emit_publish_cards(result: dict[str, Any], root: Path | None = None) -> AgendaItem | None:
    """Brief only when the landing page actually received cards."""
    published = int(result.get("published_count") or 0)
    if published <= 0:
        return None
    now = datetime.now(timezone.utc)
    slot = result.get("slot") or "unknown"
    body = (
        f"Published {published} card(s) to gaius.zndx.org "
        f"(slot={slot}, kv={result.get('kv_sync_success')}).\n"
    )
    return upsert(
        kind="note",
        title="gaius.zndx.org published",
        body=body,
        now=now,
        tags=["publish"],
        intent="brief",
        root=root,
    )


def backfill_surfaces(root: Path | None = None) -> list[AgendaItem]:
    """Rewrite the surface cards in the brief/reminder/session framing.

    Facts only. No Perseids unless it is in a Gaius store (it is not).
    No invented 13F holder deltas.
    """
    kb = root or kb_root_from_env()
    made: list[AgendaItem] = []

    def add(item: AgendaItem | None) -> None:
        if item is not None:
            made.append(item)

    q2_start = "2026-08-14T13:00:00+00:00"
    q2_end = "2026-08-14T13:30:00+00:00"
    q2_brief = (
        "Session: walk the watchlist against what actually landed on "
        "the Q2 13F due date (45 days after 30 Jun).\n"
        "\n"
        "What ran that morning (`prospects_check` 5366 → "
        "`prospects_update` 5367):\n"
        "- 50 new FMP filings across MTN, LLY, DIS, INTC, CHTR, XOM\n"
        "- 0 filings extracted / analyzed (docling 0, EDGAR synced 0)\n"
        "- 5 positions synthesized from existing KB: "
        "CHTR BUY 75% high, DIS BUY 75% medium, MTN HOLD 60%, "
        "LLY HOLD 40%, XOM HOLD 50%\n"
        "- INTC was in the payload but not in the sitrep table; "
        "SLB and AI.PA (watchlist P1) were not in this run\n"
        "\n"
        "13F holder tape did not land. FMP "
        "`/stable/institutional-ownership/…` is 402 on this key; "
        "`meta.institutional_holders_cache` is empty. Empty is not "
        "“no change”.\n"
        "\n"
        "What the prospects KB *does* have (Schedule 13G, not 13F):\n"
        "- Dodge & Cox 11.3% of CHTR Class A as of 31 Oct 2025 "
        "(SC 13G/A 2025-11-06)\n"
        "- State Street 5.8% / 7.96M shares as of 30 Sep 2025 "
        "(SC 13G 2025-11-10)\n"
        "\n"
        "Related: [[scratch/2026-08-14/070315_prospects_sitrep]] "
        "[[current/prospects/chtr/synthesis]] "
        "[[current/prospects/dis/synthesis]]\n"
    )
    add(
        upsert(
            kind="event",
            title="Q2 13F window vs watchlist",
            slug="q2-13f-window-vs-watchlist",
            starts=q2_start,
            ends=q2_end,
            tags=["13f", "prospects", "watchlist"],
            pin=True,
            intent="session",
            with_whom="agents",
            now=datetime(2026, 8, 14, 13, 0, 0, tzinfo=timezone.utc),
            root=kb,
            body=q2_brief,
        )
    )
    add(
        upsert(
            kind="note",
            title="Prospects update — 50 FMP filings, 0 extracts",
            slug="prospects-update-50-fmp-filings-0-extracts",
            tags=["prospects"],
            intent="brief",
            now=datetime(2026, 8, 14, 7, 3, 15, tzinfo=timezone.utc),
            root=kb,
            body=(
                "Run 12 / correlation `ec904517-0393-4441-b6e1-a9f5365e958d` "
                "completed. 21 KB artifacts, $0.00. Synthesis reused existing "
                "notes; the 50 new FMP rows were not pulled into the extract "
                "claim.\n"
                "\n"
                "A later zndx-profile pass the same afternoon (run 15) "
                "created nothing.\n"
                "\n"
                "Related: [[scratch/2026-08-14/070315_prospects_sitrep]]\n"
            ),
        )
    )
    add(
        upsert(
            kind="list",
            title="Prospects check 52 filings then NOADMIT",
            slug="prospects-check-52-filings-then-noadmit",
            tags=["prospects", "ops"],
            intent="reminder",
            now=datetime(2026, 8, 16, 4, 10, 4, tzinfo=timezone.utc),
            root=kb,
            body=(
                "`prospects_check` 5628: 52 new FMP filings, "
                "update_recommended. `prospects_update` 5629 failed "
                "`#YK.00000001.NOADMIT` — kubectl apply targeted "
                "standing pod `article-curate-1786767299`.\n"
                "\n"
                "- [ ] Re-admit on a prospects-update claim, not the "
                "standing article-curate pod\n"
                "- [ ] Extract the 52-row aperture after admit\n"
            ),
        )
    )
    add(
        upsert(
            kind="note",
            title="gaius.zndx.org clock is empty since March",
            slug="gaius-zndx-org-clock-is-empty-since-march",
            tags=["publish"],
            intent="brief",
            now=datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc),
            root=kb,
            body=(
                "Last published card: 14 Mar 2026 "
                "(LLM multi-agent / legal-agents survey). "
                "212 published, 20 pending (newest pending 11 Mar), "
                "2 archived.\n"
                "\n"
                "`publish_cards` four slots/day is now completing with "
                "Cloudflare KV configured (since 14 Aug ~12:00 UTC) but "
                "`published_count=0` every slot. Upstream "
                "`article_curate` 13–16 Aug: Metaflow fail, "
                "`#YK.00000001.NOADMIT`, then `#YK.00000005.DISK` "
                "(18.4Gi free vs 32Gi floor).\n"
            ),
        )
    )
    add(
        upsert(
            kind="list",
            title="Unblock the landing-page pipeline",
            slug="unblock-the-landing-page-pipeline",
            tags=["publish", "ops"],
            intent="reminder",
            now=datetime(2026, 8, 16, 12, 5, 0, tzinfo=timezone.utc),
            root=kb,
            body=(
                "- [ ] Free disk above the 32Gi YK envelope (`#YK.00000005.DISK`)\n"
                "- [ ] Admit article-curate on its own claim, not the standing "
                "article-curate-1786767299 pod\n"
                "- [ ] Enrich the 20 pending March cards so publish_cards has "
                "something to ship\n"
                "- [ ] Confirm KV sync still true after a non-zero publish\n"
            ),
        )
    )
    add(
        upsert(
            kind="note",
            title="Ambient standing — 36 cycles, 0 tasks",
            slug="ambient-standing-36-cycles-0-tasks",
            tags=["ambient"],
            intent="brief",
            now=datetime(2026, 8, 16, 18, 1, 0, tzinfo=timezone.utc),
            root=kb,
            body=(
                "`ambient_daemon_state.running=t` since 15 Aug 18:01 UTC "
                "(operator_disabled=f). 36 cycles, 0 total_tasks. The "
                "buffer exists in-process; nothing harvestable has been "
                "admitted.\n"
            ),
        )
    )
    add(
        upsert(
            kind="note",
            title="Ops week — clocks that actually fired",
            slug="ops-week-clocks-that-actually-fired",
            tags=["ops"],
            intent="brief",
            now=datetime(2026, 8, 16, 20, 4, 0, tzinfo=timezone.utc),
            root=kb,
            body=(
                "13–16 Aug `scheduled_tasks` (engine up):\n"
                "- board_reindex: 6244 docs / 1453 iceberg (2 min)\n"
                "- feed_check → heuristic/llm_triage: arxiv_cs_dc, "
                "biorxiv_synbio, databricks/crusoe/temporal blogs, "
                "philpapers/philevents\n"
                "- cognition_cycle: success, 0 patterns / 0 connections\n"
                "- weekly_summary: 0 queries, 0 KB entries\n"
                "- evolution_cycle: 7 completed\n"
                "- article_curate / prospects_update: YK disk + NOADMIT "
                "when extract is required\n"
            ),
        )
    )
    add(
        upsert(
            kind="list",
            title="Watchlist after Q2 13F",
            slug="watchlist-after-q2-13f",
            tags=["watchlist", "13f"],
            intent="reminder",
            starts="2026-08-17T13:00:00+00:00",
            now=datetime(2026, 8, 17, 13, 0, 0, tzinfo=timezone.utc),
            root=kb,
            body=(
                "- [ ] CHTR: Dodge & Cox 11.3% and State Street 5.8% are "
                "13G, not 13F — wait for holders or treat as stale\n"
                "- [ ] DIS BUY 75% — thesis body is empty; do not act on "
                "the label alone\n"
                "- [ ] Pull SLB and AI.PA into the next prospects_update "
                "(missed 14 Aug)\n"
                "- [ ] Re-admit the 52 FMP filings from 16 Aug after YK "
                "NOADMIT\n"
                "- [ ] Do not invent 13F deltas while the endpoint is 402\n"
            ),
        )
    )
    q3_start = "2026-11-14T13:00:00+00:00"
    q3_end = "2026-11-14T13:30:00+00:00"
    q3_brief = (
        "Session: Q3 2026 13F statutory deadline (45 days after 30 Sep = "
        "14 Nov 2026, Saturday). Same watchlist as Q2: "
        "CHTR, SLB, AI.PA, DIS, MTN, LLY, INTC, XOM. Holders "
        "only if FMP institutional-ownership is no longer 402 "
        "or EDGAR 13F extract is wired.\n"
    )
    add(
        upsert(
            kind="event",
            title="Q3 13F window",
            slug="q3-13f-window",
            tags=["13f", "watchlist"],
            intent="session",
            with_whom="agents",
            starts=q3_start,
            ends=q3_end,
            now=datetime(2026, 11, 14, 13, 0, 0, tzinfo=timezone.utc),
            root=kb,
            body=q3_brief,
        )
    )
    return made
