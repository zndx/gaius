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
import re
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
from gaius.core.budgets import LONG_FORM_MAX_TOKENS

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


# A spawned flow reports these with no `error` key — the diagnosis is in
# `last_lines`. Treating them as anything but a failure buries the reason.
_PROSPECTS_FAILURES = frozenset({"error", "failed", "stalled"})


def _tail_lines(text: str, budget: int = 1200) -> str:
    """Last whole lines that fit in ``budget``.

    Slicing a traceback by character starts the note mid-token
    ("ice.py\", line 186, in ..."), which reads as corruption.
    """
    lines = (text or "").strip().splitlines()
    kept: list[str] = []
    used = 0
    for line in reversed(lines):
        used += len(line) + 1
        if kept and used > budget:
            break
        kept.append(line)
    return "\n".join(reversed(kept))


def emit_prospects_update(result: dict[str, Any], root: Path | None = None) -> AgendaItem | None:
    """Failure → reminder. Completed filings → session. Else brief."""
    now = datetime.now(timezone.utc)
    symbols = result.get("symbols") or []
    status = result.get("status") or ("error" if result.get("error") else "unknown")
    err = (result.get("error") or "").strip()
    failed = bool(err) or status in _PROSPECTS_FAILURES
    if failed and not err:
        # _run_spawned_metaflow carries the child's tail here instead of an
        # `error` key. It is present on success too, so only read it once the
        # status already says this run failed.
        tail = result.get("last_lines") or []
        err = "\n".join(str(line) for line in tail if str(line).strip())
    sym = ", ".join(str(s) for s in symbols) or "(none)"

    if failed:
        rc = result.get("returncode")
        detail = _tail_lines(err) or "no output captured"
        body = (
            f"Prospects update failed ({status}"
            f"{f', exit {rc}' if rc is not None else ''}).\n\n"
            f"Symbols: {sym}.\n\n"
            f"{detail}\n"
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

    summary = result.get("outcomes_summary") or {}
    outcomes = summary.get("outcomes") or []

    if outcomes:
        total_filings = int(summary.get("filings_analyzed_total") or 0)
        cost = float(summary.get("total_cost_usd") or 0.0)
        rows: list[str] = []
        lines: list[str] = []
        for o in outcomes:
            osym = str(o.get("symbol") or "?")
            rec = str(o.get("recommendation") or "?").upper()
            conv = o.get("conviction")
            conv_s = f"{float(conv):.0%}" if isinstance(conv, (int, float)) else "—"
            prior = o.get("prior") or {}
            if prior:
                p_rec = str(prior.get("recommendation") or "?").upper()
                p_conv = prior.get("conviction")
                p_conv_s = (
                    f"{float(p_conv):.0%}" if isinstance(p_conv, (int, float)) else "?"
                )
                delta = f"was {p_rec} {p_conv_s}"
            else:
                delta = "new (no prior)"
            action = str((o.get("rebalancing_call") or {}).get("action") or "watch")
            rows.append(
                f"| {osym} | {rec} | {conv_s} | {delta} | {action} "
                f"| {int(o.get('filings_analyzed') or 0)} |"
            )
            change = str(o.get("change") or "").strip()
            first = change.split(". ")[0].strip()[:220]
            links: list[str] = []
            note_path = str(o.get("scratch_note") or "").removesuffix(".md")
            if note_path:
                links.append(f"[[{note_path}|log]]")
            synth_path = str(o.get("synthesis_path") or "").removesuffix(".md")
            if synth_path:
                links.append(f"[[{synth_path}|synthesis]]")
            lines.append(
                f"- **{osym}** — {first or 'no change note produced'}"
                + (f" · {' · '.join(links)}" if links else "")
            )
        sitrep = str(summary.get("sitrep_path") or "").removesuffix(".md")
        body = (
            f"Prospects update completed on {len(outcomes)} position(s) — "
            f"{total_filings} filing(s) analyzed, ${cost:.2f}.\n\n"
            "| Symbol | Call | Conviction | Δ vs prior | Action | Filings |\n"
            "|--------|------|------------|-----------|--------|---------|\n"
            + "\n".join(rows)
            + "\n\n"
            + "\n".join(lines)
            + "\n"
            + (f"\nSitrep: [[{sitrep}]]\n" if sitrep else "")
        )
        resolved = _resolve_open_failures(now, root=root)
        if resolved:
            body += (
                f"\nResolved {resolved} open 'Prospects update failed' "
                "reminder(s) — this run completed clean.\n"
            )
        if total_filings > 0:
            start = _next_session_slot(now)
            ends = start + timedelta(minutes=30)
            return upsert(
                kind="event",
                title="Prospects filings session",
                body=body,
                now=start,
                starts=start.isoformat(),
                ends=ends.isoformat(),
                tags=["prospects", "watchlist"],
                intent="session",
                with_whom="agents",
                root=root,
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

    # Clean run but no outcomes handed over: say so rather than pretending
    # nothing happened — the per-symbol artifacts may still exist.
    body = (
        f"Prospects update {status}. Symbols: {sym}.\n\n"
        "The flow reported no per-symbol outcomes "
        "(current/prospects/last_update_outcomes.json missing or stale) — "
        "see the ProspectsUpdate flow log and current/prospects/ for what "
        "was actually produced.\n"
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


def _resolve_open_failures(
    now: datetime, *, days: int = 14, root: Path | None = None
) -> int:
    """Tick open 'Prospects update failed' reminders after a clean run.

    The failure branch upserts a per-day reminder with an unticked box;
    without this, every later agenda brief re-chews a failure that no
    longer exists (2026-09-12: two stale reminders outlived the fix by
    a day). Direct text surgery on the zettels; fail-open on any error.
    """
    resolved = 0
    try:
        kb = root or kb_root_from_env()
        for back in range(days):
            day = (now - timedelta(days=back)).astimezone(timezone.utc)
            day_dir = kb / "scratch" / day.strftime("%Y-%m-%d")
            if not day_dir.is_dir():
                continue
            for path in day_dir.glob("*prospects-update-failed*.md"):
                text = path.read_text(encoding="utf-8")
                if "- [ ]" not in text:
                    continue
                stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                text = text.replace("- [ ] ", "- [x] ")
                text += (
                    f"\n> Resolved {stamp}: a clean prospects update run "
                    "booked the calls.\n"
                )
                path.write_text(text, encoding="utf-8")
                resolved += 1
    except (OSError, AgendaError) as exc:
        logger.error("%s\n  cause: %s", GURU_EMITFAIL, exc)
    return resolved


def emit_prospects_watch(
    *,
    reason: str,
    stances: list[dict[str, Any]],
    headlines: list[dict[str, Any]],
    root: Path | None = None,
) -> AgendaItem | None:
    """Book the no-update-work readout: standing calls vs the 36h tape.

    A check that finds no filing work must still inform rebalancing —
    'all quiet, no action warranted' is a conclusion, 'nothing to book'
    is not. Data comes from the fmp_roll durable buffer; do not invent
    items the clocks did not produce.
    """
    now = datetime.now(timezone.utc)

    calls = [
        f"{s['symbol']} {str(s.get('recommendation') or '?').upper()}"
        + (
            f" {float(s['conviction']):.0%}"
            if isinstance(s.get("conviction"), (int, float))
            else ""
        )
        for s in stances
        if str(s.get("recommendation") or "").strip()
    ]
    missing = [
        str(s.get("symbol"))
        for s in stances
        if not str(s.get("recommendation") or "").strip()
    ]

    watch_items = [h for h in headlines if h.get("on_watch")]
    general_items = [h for h in headlines if not h.get("on_watch")]

    parts: list[str] = []
    parts.append(f"No filing work pending ({reason or 'converged'}).\n")
    if calls:
        parts.append("Standing calls: " + " · ".join(calls) + "\n")
    if missing:
        parts.append(
            "No thesis on record for: " + ", ".join(missing)
            + " — the next filing-driven update writes one.\n"
        )
    if watch_items:
        parts.append("Watchlist tape (36h, market buffer):\n")
        parts.extend(
            f"- [{h['kind']}] {h['symbol'] or '—'} — {h['title']} ({h['when']})"
            for h in watch_items
        )
        parts.append("")
    if general_items:
        parts.append("Elsewhere on the tape:\n")
        parts.extend(
            f"- [{h['kind']}] {h['symbol'] or '—'} — {h['title']} ({h['when']})"
            for h in general_items
        )
        parts.append("")
    if not watch_items and not general_items:
        parts.append(
            "The market buffer held no watchlist items in the last 36h — "
            "if this persists, check the fmp_roll clock (/health).\n"
        )
    parts.append(
        "No action warranted from the tape alone; filings drive re-synthesis."
    )

    return upsert(
        kind="note",
        title="Prospects watch",
        body="\n".join(parts) + "\n",
        now=now,
        tags=["prospects", "watchlist"],
        intent="brief",
        root=root,
    )


def emit_publish_cards(result: dict[str, Any], root: Path | None = None) -> AgendaItem | None:
    """Fact-line publish entry (fallback when no Brief can be written)."""
    published = int(result.get("published_count") or 0)
    if published <= 0:
        return None
    now = datetime.now(timezone.utc)
    slot = result.get("slot") or "unknown"
    synced = result.get("card_synced_count")
    body = (
        f"Published {published} card(s) to gaius.zndx.org "
        f"(slot={slot}, card pages synced={synced}).\n"
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


def _todays_brief_item(root: Path | None, now: datetime) -> Path | None:
    """Path of today's publish item iff it already carries a rich Brief
    (public card links present); None when absent or a bare fallback."""
    try:
        kb = root or kb_root_from_env()
        day = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
        path = find_by_slug(
            kb, day, skewer("gaius.zndx.org published", "note")
        )
        if path is None:
            return None
        if "https://gaius.zndx.org/cards/" not in path.read_text(
            encoding="utf-8"
        ):
            return None
        return path
    except Exception:  # noqa: BLE001 — probe helper, never load-bearing
        return None


async def emit_publish_brief(
    result: dict[str, Any],
    pool: Any,
    root: Path | None = None,
) -> AgendaItem | None:
    """Publish entry as a real Brief: Qwen3.8-27B's summary-of-summaries.

    The entry must be USEFUL — tell the reader what they will find when
    they visit the live collections, with links to the public card
    pages. The model chooses its own structure (links, a small table,
    plain prose — its call), within Agenda length norms: long-form would
    overwhelm the Agenda item view, so the Brief is capped hard.

    Fail-open to the fact-line entry with an honest note — the Agenda is
    a journal; a missing Brief must never block the publish path.
    """
    published = int(result.get("published_count") or 0)
    if published <= 0:
        return None
    now = datetime.now(timezone.utc)
    slot = result.get("slot") or "unknown"
    synced = result.get("card_synced_count")
    fact_line = (
        f"Published {published} card(s) to gaius.zndx.org "
        f"(slot={slot}, card pages synced={synced})."
    )

    try:
        cards = [
            c for c in (result.get("published") or []) if c.get("card_id")
        ]
        if not cards:
            raise RuntimeError("no card payloads in publish result")

        # Gather each card's existing summaries — the Brief is a summary
        # OF the summaries, not fresh analysis from thin air.
        ids = [c["card_id"] for c in cards]
        summaries: dict[str, list[tuple[str, str]]] = {}
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT card_id, summary_type, summary_text
                FROM collections.card_summaries
                WHERE card_id = ANY($1::text[])
                """,
                ids,
            )
        for row in rows:
            summaries.setdefault(row["card_id"], []).append(
                (row["summary_type"], row["summary_text"] or "")
            )

        card_blocks = []
        for c in cards:
            cid = c["card_id"]
            block = [
                f"### {c.get('title', cid)}",
                f"Public URL: https://gaius.zndx.org/cards/{cid}",
                f"Source date: {c.get('source_date', 'unknown')}",
            ]
            for stype, stext in summaries.get(cid, []):
                block.append(f"[{stype} summary] {stext[:1200]}")
            card_blocks.append("\n".join(block))

        # Multi-turn incorporation: when today's item already carries a
        # rich Brief, the thinking agent merges this slot's cards into
        # it via tool-mediated read/edit (agenda_edit) — a later slot
        # must never clobber an earlier slot's Brief with a rewrite.
        existing = _todays_brief_item(root, now)
        if existing is not None:
            from gaius.engine.services.agenda_edit import (
                incorporate_into_note,
            )

            # CHUNKED incorporation: one compact session per card, then
            # one for the fact line. Sessions with multi-card prompts
            # and long planning turns fail in the agent lane
            # (#ACP.00000005 at ~3-5KB tasks, 2026-09-02); single-card
            # tasks are the proven envelope — and rounds of small edits
            # against disk truth ARE the multi-turn contract.
            merged_any = False
            for c in cards:
                cid = c["card_id"]
                summ = ""
                for _stype, stext in summaries.get(cid, [])[:1]:
                    summ = stext[:500]
                task = (
                    "A new card was published today and must be woven "
                    "into the existing Brief. Append or integrate ONE "
                    "short sentence in the prose before the --- "
                    "separator (same editorial voice), with the card "
                    "title linked to its public URL. Condense an "
                    "existing sentence if the Brief grows past ~200 "
                    "words.\n\n"
                    f"Card: {c.get('title', cid)}\n"
                    f"Public URL: https://gaius.zndx.org/cards/{cid}\n"
                    f"Summary: {summ}"
                )
                if await incorporate_into_note(existing, task):
                    merged_any = True
            fact_task = (
                "Update the fact line(s) after the --- separator so the "
                "day's totals stay accurate: append this slot's fact "
                f"line verbatim on its own line: {fact_line}"
            )
            facts_applied = await incorporate_into_note(existing, fact_task)
            if merged_any or facts_applied:
                # Even facts-only counts: the Brief stays rich and the
                # day record stays accurate — never fall through to an
                # upsert that would rewrite what a session just built
                # (2026-09-02 17:19: the fact session's append was
                # clobbered seconds later by the fallback).
                return None
            raise RuntimeError(
                "incorporation sessions left the note unchanged"
            )

        from gaius.client.engine_client import Message, get_engine_client

        engine = await get_engine_client()
        prompt = (
            "You are writing the Brief for a Gaius Agenda entry announcing "
            "cards just published to the public research-collections site "
            "gaius.zndx.org.\n\n"
            "A Brief is a summary of the summaries: informative enough that "
            "a reader knows what they will find when they visit the live "
            "collections. You choose the structure — flowing prose, inline "
            "links, or a small markdown table are all acceptable; use "
            "whatever serves these particular cards best. Not required to "
            "use any of them.\n\n"
            "Hard constraints:\n"
            "- Markdown. Link every card title to its public URL.\n"
            "- 120-200 words TOTAL. The Agenda item view is compact; "
            "long-form would overwhelm it.\n"
            "- No headings (the entry already has a title). Bold is fine.\n"
            "- High signal: what the material covers and why a reader "
            "would care — no filler, no meta-commentary about this task.\n\n"
            f"Published this slot:\n\n" + "\n\n".join(card_blocks)
        )
        completion = await engine.complete(
            [Message(role="user", content=prompt)],
            model="thinking",
            temperature=0.6,
            max_tokens=LONG_FORM_MAX_TOKENS,
        )
        brief = (completion.content or "").strip()
        if not brief:
            raise RuntimeError("thinking returned empty Brief")
        body = f"{brief}\n\n---\n{fact_line}\n"
    except Exception as e:  # noqa: BLE001 — journal decoration is fail-open
        logger.warning(f"#AG.00000002.BRIEFFAIL publish Brief failed: {e}")
        prior_item = _todays_brief_item(root, now)
        if prior_item is not None:
            # A degraded fallback must never clobber a rich Brief
            # (2026-09-02: the 12:00 slot's token-starved empty
            # completion overwrote the 01:18 Brief with a bare fact
            # line). Keep the Brief; refresh the facts.
            text = prior_item.read_text(encoding="utf-8")
            m = re.search(
                r"^# gaius\.zndx\.org published\s*\n(.*)\Z",
                text,
                re.MULTILINE | re.DOTALL,
            )
            prior_body = (m.group(1) if m else "").strip()
            # Keep the WHOLE prior body — brief AND the day's existing
            # fact lines (2026-09-02 17:19: rsplit dropped the earlier
            # slots' facts) — and append this slot's fact honestly.
            body = (
                f"{prior_body}\n{fact_line}\n"
                f"_Latest slot Brief unavailable: {str(e)[:100]}_\n"
            )
        else:
            body = f"{fact_line}\n\n_Brief unavailable: {str(e)[:120]}_\n"

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
