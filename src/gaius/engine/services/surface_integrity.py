"""surface_integrity — the composite objective on the public surface.

One objective, four aspects, fourteen gates, all deterministic. Website
gates are defined on what a visitor RECEIVES at gaius.zndx.org (doctrine
rule 2). Conversation gates are defined on the Agenda horizon a voice
session receives (today · tomorrow · week):

  currency      surface_newest_current · surface_band_current ·
                surface_refreshed_within_intent          (ex content_currency)
  integrity     surface_ordered · surface_dates_present (2026-09-07: the page reads
                newest-first by the content's own date, every card dated) ·
                no_marketing_shapes · no_denied_domains · no_duplicate_sources
  conservation  no_unexplained_removals · removal_reasons_declared
  conversation  agenda_lede_is_prose · agenda_session_has_a_question ·
                agenda_brief_matches_horizon · agenda_intents_diverse
                (2026-09-07: AgentRTC UXR — curated cards, not emit reengineering)

The split is the sdg-strategy `objective` pillar's shape (external/sdg-strategy/
objective/): the normative card lives in config/supervision/objectives/
surface-integrity.md, its JSON twin carries `examples[{input, output}]`, and
every example is a specimen this module must resolve identically —
tests/engine/test_surface_integrity.py runs them. `evaluate()` is therefore
pure: facts in, gates out. `collect_facts()` is the only I/O.

Conservation (2026-09-06, user): "expand the objective to also preclude
dropping content" — a currency gate was satisfiable by archiving, and that is
how it was satisfied on 2026-09-05. With `collections.content_events` journaling
every status transition, monotonicity is exactly: no published → archived
transition without a declared reason (category ∈ REMOVAL_REASONS).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlsplit

GATES: tuple[str, ...] = (
    "surface_newest_current",
    "surface_band_current",
    "surface_refreshed_within_intent",
    "surface_ordered",
    "surface_dates_present",
    "no_marketing_shapes",
    "no_denied_domains",
    "no_duplicate_sources",
    "no_unexplained_removals",
    "removal_reasons_declared",
    "agenda_lede_is_prose",
    "agenda_session_has_a_question",
    "agenda_brief_matches_horizon",
    "agenda_intents_diverse",
)
ASPECT: dict[str, str] = {
    "surface_newest_current": "currency",
    "surface_band_current": "currency",
    "surface_refreshed_within_intent": "currency",
    "surface_ordered": "integrity",
    "surface_dates_present": "integrity",
    "no_marketing_shapes": "integrity",
    "no_denied_domains": "integrity",
    "no_duplicate_sources": "integrity",
    "no_unexplained_removals": "conservation",
    "removal_reasons_declared": "conservation",
    "agenda_lede_is_prose": "conversation",
    "agenda_session_has_a_question": "conversation",
    "agenda_brief_matches_horizon": "conversation",
    "agenda_intents_diverse": "conversation",
}
REMOVAL_REASONS: tuple[str, ...] = ("duplicate", "adversarial", "license", "retired", "broken", "operator")

DEFAULT_PARAMS: dict[str, Any] = {
    "newest_days": 2,
    "current_days": 7,
    "band": 26,
    "min_current_share": 0.5,
    "refresh_hours": 13,
    "conservation_window_hours": 168,
    "goggle": "config/brave/web-half.goggle",
    "surface_url": "https://gaius.zndx.org/",
    # (2026-09-07, user) "a casual visitor sees fresh, well-ordered content: proof
    # the pipelines work" — the surface must read newest-first by the content's
    # own date (0 inversions) and every visible card must carry that date (0
    # missing), alongside newest_days = 2 (cards for content published within
    # the last 48 hours). The page followed publish-slot order until then.
    "max_inversions": 0,
    "max_undated": 0,
    # conversation — Agenda horizon the voice speaks (today/tomorrow/week).
    # Operator zone for bucketing; spoken brief is judged against those buckets.
    "agenda_timezone": "America/Denver",
    "agenda_diversity_min_items": 3,
}

# Invite paste, guru packs, stack traces, naked checklists — not a conversational lede.
_AGENDA_DUMP = re.compile(
    r"(?is)^(?:\s*-\s*\[[ xX]\])"
    r"|BEGIN SESSION|episode=|\bHX:"
    r'|File "/|pyiceberg|Traceback \(most recent call last\)'
    r"|Catch-up with a colleague|Guru:|#AG\.|#COG\."
)
# A session card is a conversation if it poses an ask (curated 2026-09-07).
_AGENDA_ASK = re.compile(
    r"(?i)\?|\bwhether\b|\bwould you\b|\bwhat (?:I|we) want\b"
    r"|\bpick one\b|\bthe (?:live |open )?question\b|\bcome with one\b"
)
_EMPTY_TOMORROW = re.compile(r"(?i)tomorrow(?:'s)?(?: and the coming week)? is empty")
_EMPTY_WEEK = re.compile(
    r"(?i)(?:the )?coming week is(?: also)? empty|week ahead is empty"
)


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _ts(s: str | None) -> datetime | None:
    if not s:
        return None
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _gate(name: str, verdict: str, evidence: str) -> dict[str, Any]:
    return {"gate": name, "aspect": ASPECT[name], "verdict": verdict, "evidence": evidence}


def evaluate(facts: dict[str, Any], params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Pure: the fourteen gates from a facts dict (shape documented in the card's
    JSON examples). Verdicts are pass | fail | error — never inconclusive: a gate
    that cannot decide says why in `error` (the 2026-09-03 lesson)."""
    from gaius.flows.article_curation.common import looks_like_marketing

    p = {**DEFAULT_PARAMS, **(params or {})}
    gates: list[dict[str, Any]] = []
    today = _d(facts.get("today")) or datetime.now(timezone.utc).date()
    now = _ts(facts.get("now")) or datetime.now(timezone.utc)

    # ---- currency -------------------------------------------------------
    surface = facts.get("surface")  # ordered [[card_id, "YYYY-MM-DD" | null], ...] as the visitor sees it
    if surface is None:
        err = f"surface unreadable: {facts.get('surface_error', 'no surface facts')}"
        for g in ("surface_newest_current", "surface_band_current", "surface_refreshed_within_intent",
                  "surface_ordered", "surface_dates_present"):
            gates.append(_gate(g, "error", err))
    else:
        cards = [(cid, _d(d)) for cid, d in surface]
        newest_days, current_days = int(p["newest_days"]), int(p["current_days"])
        band, min_share, refresh_hours = int(p["band"]), float(p["min_current_share"]), int(p["refresh_hours"])
        corpus_newest = _d(facts.get("corpus_newest"))
        dated = [d for _, d in cards if d is not None]
        newest = max(dated) if dated else None
        ok = newest is not None and (today - newest).days <= newest_days
        gates.append(_gate(
            "surface_newest_current", "pass" if ok else "fail",
            f"newest visible card date = {newest} (today {today}; within {newest_days}d required: daily curate + "
            f"day-granular source dates); {len(dated)}/{len(cards)} cards dated; corpus newest source_date = {corpus_newest}"
            + ("" if ok or corpus_newest is None or (today - corpus_newest).days <= current_days
               else " — DAG stage: curation inflow (article_curate) is stale"),
        ))
        head = cards[:band]
        head_current = sum(1 for _, d in head if d is not None and (today - d).days <= current_days)
        share = head_current / len(head) if head else 0.0
        ok = share >= min_share
        gates.append(_gate(
            "surface_band_current", "pass" if ok else "fail",
            f"{head_current}/{len(head)} of the first {band} cards dated within {current_days}d (share {share:.2f}; "
            f"≥ {min_share:.2f} required — intent ≈ 20 curate : 6 slot publishes per day)"
            + ("" if ok else " — DAG stage: article_curate's selection returned mostly non-current sources, "
               "or publish_cards' picks are outweighing it, or the curate did not run"),
        ))
        # ---- integrity: the page reads as well-ordered, and every card is dated
        dated_seq = [(i + 1, cid, d) for i, (cid, d) in enumerate(cards) if d is not None]
        inversions = [
            (a, b) for a, b in zip(dated_seq, dated_seq[1:]) if b[2] > a[2]
        ]
        max_inv = int(p.get("max_inversions", 0))
        ok = len(inversions) <= max_inv
        first = (
            f"; first: #{inversions[0][0][0]} {inversions[0][0][1]} {inversions[0][0][2]} above "
            f"#{inversions[0][1][0]} {inversions[0][1][1]} {inversions[0][1][2]}"
            if inversions else ""
        )
        gates.append(_gate(
            "surface_ordered", "pass" if ok else "fail",
            f"{len(inversions)} date inversion(s) among {len(dated_seq)} dated cards top to bottom "
            f"(≤ {max_inv} required: the page lists the content's own date newest first){first}"
            + ("" if ok else " — DAG stage: publish_cards KV sync order (get_cards_for_kv / get_published_cards "
               "must ORDER BY source_date DESC NULLS LAST)"),
        ))
        undated = [(i + 1, cid) for i, (cid, d) in enumerate(cards) if d is None]
        max_und = int(p.get("max_undated", 0))
        ok = len(undated) <= max_und
        gates.append(_gate(
            "surface_dates_present", "pass" if ok else "fail",
            f"{len(undated)}/{len(cards)} visible cards carry no date (≤ {max_und} required)"
            + (": " + ", ".join(f"#{i} {cid}" for i, cid in undated[:6]) if undated else "")
            + ("" if ok else " — DAG stage: article_curate card creation left source_date NULL and "
               "publish let it through (publish_cards_by_ids now keeps undated cards pending)"),
        ))
        top_id = cards[0][0] if cards else None
        top_pub = _ts(facts.get("top_published_at"))
        if top_id is None:
            gates.append(_gate("surface_refreshed_within_intent", "error", "no cards on the surface"))
        elif top_pub is None:
            gates.append(_gate("surface_refreshed_within_intent", "fail",
                               f"top card {top_id} on the surface is unknown to the DB — surface/DB incoherence "
                               "(DAG stage: publish_cards KV sync)"))
        else:
            age_h = (now - top_pub).total_seconds() / 3600.0
            ok = age_h <= refresh_hours
            gates.append(_gate(
                "surface_refreshed_within_intent", "pass" if ok else "fail",
                f"top card {top_id} published {age_h:.1f}h ago (≤ {refresh_hours}h required: slots at 12/17/21/02 UTC, "
                f"longest gap 10h → next Fibonacci hour 13)"
                + ("" if ok else " — DAG stage: publish_cards slot missed or deferred"),
            ))

    # ---- integrity ------------------------------------------------------
    published = facts.get("published")  # [{card_id, source_url, title}] everything with status='published'
    if published is None:
        err = f"collections.cards unreadable: {facts.get('published_error', 'no rows')}"
        for g in ("no_marketing_shapes", "no_denied_domains", "no_duplicate_sources"):
            gates.append(_gate(g, "error", err))
    else:
        flagged = [(r["card_id"], why) for r in published
                   if (why := looks_like_marketing(r.get("source_url") or "", r.get("title") or ""))]
        gates.append(_gate(
            "no_marketing_shapes", "pass" if not flagged else "fail",
            f"{len(flagged)}/{len(published)} published cards match a marketing shape"
            + (": " + "; ".join(f"{c} ({w})" for c, w in flagged[:5]) if flagged else "")
            + ("" if not flagged else " — DAG stage: article_curate acquisition (goggle/reflex) let it in; "
               "archive with reason 'adversative'".replace("adversative", "adversarial")),
        ))
        denied = facts.get("denied_domains")
        if denied is None:
            gates.append(_gate("no_denied_domains", "error",
                               f"goggle unreadable: {facts.get('goggle_error', 'no denied_domains facts')} (#ACF.00000021.NOGOGGLE)"))
        else:
            dset = {d.lower().removeprefix("www.") for d in denied}
            bad = [r["card_id"] for r in published
                   if (urlsplit(r.get("source_url") or "").hostname or "").lower().removeprefix("www.") in dset]
            gates.append(_gate(
                "no_denied_domains", "pass" if not bad else "fail",
                f"{len(bad)}/{len(published)} published cards from a discarded domain ({len(dset)} domains in {p['goggle']})"
                + (": " + ", ".join(bad[:8]) if bad else ""),
            ))
        seen: dict[str, list[str]] = {}
        for r in published:
            seen.setdefault((r.get("source_url") or "").strip(), []).append(r["card_id"])
        dupes = {u: ids for u, ids in seen.items() if u and len(ids) > 1}
        gates.append(_gate(
            "no_duplicate_sources", "pass" if not dupes else "fail",
            f"{len(dupes)} source URL(s) published more than once"
            + (": " + "; ".join(f"{u[:50]} x{len(ids)}" for u, ids in list(dupes.items())[:4]) if dupes else ""),
        ))

    # ---- conservation ---------------------------------------------------
    ev = facts.get("events")  # {window_hours, journal_since, added, removed: [{content_id, reason}]}
    if ev is None:
        err = f"collections.content_events unreadable: {facts.get('events_error', 'no journal')} — apply migration 20260906000001"
        for g in ("no_unexplained_removals", "removal_reasons_declared"):
            gates.append(_gate(g, "error", err))
    else:
        window_h = int(ev.get("window_hours", p["conservation_window_hours"]))
        since = ev.get("journal_since")
        coverage = "" if not since else f"; journal since {since}"
        removed = list(ev.get("removed") or [])
        unexplained = [r["content_id"] for r in removed if not (r.get("reason") or "").strip()]
        gates.append(_gate(
            "no_unexplained_removals", "pass" if not unexplained else "fail",
            f"{len(unexplained)}/{len(removed)} published→archived transitions in {window_h}h carry no reason"
            f" (added {int(ev.get('added', 0))}{coverage})"
            + (": " + ", ".join(unexplained[:8]) if unexplained else "")
            + ("" if not unexplained else " — the surface may not shrink silently: archive with SET LOCAL gaius.content_reason"),
        ))
        explained = [r for r in removed if (r.get("reason") or "").strip()]
        undeclared = [(r["content_id"], r["reason"]) for r in explained
                      if r["reason"].split(":", 1)[0].strip().lower() not in REMOVAL_REASONS]
        gates.append(_gate(
            "removal_reasons_declared", "pass" if not undeclared else "fail",
            f"{len(explained) - len(undeclared)}/{len(explained)} explained removals use a declared category "
            f"({'|'.join(REMOVAL_REASONS)})"
            + (": " + "; ".join(f"{c} ({w[:40]!r})" for c, w in undeclared[:4]) if undeclared else ""),
        ))

    # ---- conversation (Agenda horizon a voice session receives) ----------
    agenda = facts.get("agenda")
    conv = (
        "agenda_lede_is_prose",
        "agenda_session_has_a_question",
        "agenda_brief_matches_horizon",
        "agenda_intents_diverse",
    )
    if agenda is None:
        err = f"agenda unreadable: {facts.get('agenda_error', 'no agenda facts')}"
        for g in conv:
            gates.append(_gate(g, "error", err))
    else:
        horizon = [r for r in (agenda.get("horizon") or []) if isinstance(r, dict)]
        dumps = []
        for r in horizon:
            lede = (r.get("summary") or r.get("title") or "").strip()
            if _AGENDA_DUMP.search(lede):
                dumps.append(r.get("id") or r.get("title") or "?")
        gates.append(_gate(
            "agenda_lede_is_prose", "pass" if not dumps else "fail",
            f"{len(dumps)}/{len(horizon)} horizon items open with a dump "
            "(checklist, invite paste, traceback, guru) not conversational prose"
            + (": " + ", ".join(dumps[:6]) if dumps else "")
            + ("" if not dumps else " — DAG stage: agenda_emit / session_invite_description"),
        ))
        sessions = [r for r in horizon if (r.get("intent") or "") == "session"]
        mute = []
        for r in sessions:
            text = " ".join(str(r.get(k) or "") for k in ("title", "summary", "body_head"))
            if not _AGENDA_ASK.search(text):
                mute.append(r.get("id") or r.get("title") or "?")
        gates.append(_gate(
            "agenda_session_has_a_question", "pass" if not mute else "fail",
            f"{len(sessions) - len(mute)}/{len(sessions)} horizon sessions pose an ask "
            "(?, whether, would you, pick one)"
            + (": " + ", ".join(mute[:6]) if mute else " — none in horizon" if not sessions else "")
            + ("" if not mute else " — DAG stage: agenda_emit session copy"),
        ))
        spoken = f"{agenda.get('spoken') or ''} {agenda.get('brief') or ''}"
        days = {str(r.get("day") or "") for r in horizon}
        lies = []
        if _EMPTY_TOMORROW.search(spoken) and "tomorrow" in days:
            lies.append("spoken says tomorrow is empty but the horizon has tomorrow")
        if _EMPTY_WEEK.search(spoken) and "week" in days:
            lies.append("spoken says the coming week is empty but the horizon has week")
        gates.append(_gate(
            "agenda_brief_matches_horizon", "pass" if not lies else "fail",
            ("; ".join(lies) if lies else "spoken brief matches tomorrow/week occupancy")
            + ("" if not lies else " — DAG stage: agenda_brief"),
        ))
        min_n = int(p.get("agenda_diversity_min_items", 3))
        intents = {str(r.get("intent") or "") for r in horizon if r.get("intent")}
        n = len(horizon)
        has_session = "session" in intents
        if n < min_n:
            ok = True
            ev = f"{n} horizon items (< {min_n}); diversity applies at ≥{min_n}"
        else:
            ok = len(intents) >= 2 and has_session
            ev = (
                f"{n} horizon items, intents={sorted(intents) or ['—']} "
                f"(≥2 intents and ≥1 session required)"
            )
            if not ok:
                ev += " — DAG stage: cognition agenda_policy density / agenda_emit kind choice"
        gates.append(_gate("agenda_intents_diverse", "pass" if ok else "fail", ev))
    return gates


async def collect_facts(pool: Any, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """The only I/O: the live page (as the visitor sees it), the published rows,
    the goggle's discard list, and the content_events window. Every failure lands
    in the facts as `<section>_error` so evaluate() renders an honest `error`."""
    import aiohttp
    from pathlib import Path

    from gaius.engine.services.objective_service import surface_cards

    p = {**DEFAULT_PARAMS, **(params or {})}
    facts: dict[str, Any] = {}
    now_ts: datetime | None = None
    today: date | None = None
    try:
        async with pool.acquire() as conn:
            now_ts = await conn.fetchval("SELECT NOW()")
            today = await conn.fetchval("SELECT CURRENT_DATE")
    except Exception as e:  # noqa: BLE001
        facts["clock_error"] = str(e)[:160]
    now_ts = now_ts or datetime.now(timezone.utc)
    today = today or now_ts.date()
    facts["now"] = now_ts.isoformat()
    facts["today"] = today.isoformat()

    url = str(p["surface_url"])
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                status, html = resp.status, await resp.text()
        if status != 200:
            raise RuntimeError(f"GET {url} -> {status}")
        cards = surface_cards(html, today)
        if not cards:
            raise RuntimeError(f"no cards parsed from {url} ({len(html)} bytes)")
        facts["surface"] = [[cid, d.isoformat() if d else None] for cid, d in cards]
        top_id = cards[0][0]
    except Exception as e:  # noqa: BLE001
        facts["surface_error"] = str(e)[:200]
        top_id = None

    try:
        async with pool.acquire() as conn:
            facts["corpus_newest"] = (await conn.fetchval("SELECT max(source_date) FROM collections.cards")) and \
                (await conn.fetchval("SELECT max(source_date) FROM collections.cards")).isoformat()
            if top_id:
                tp = await conn.fetchval("SELECT published_at FROM collections.cards WHERE card_id = $1", top_id)
                facts["top_published_at"] = tp.isoformat() if tp else None
            rows = await conn.fetch(
                "SELECT card_id, source_url, title FROM collections.cards WHERE status = 'published'"
            )
            facts["published"] = [dict(r) for r in rows]
    except Exception as e:  # noqa: BLE001
        facts["published_error"] = str(e)[:200]

    goggle_path = Path(__file__).resolve().parents[4] / str(p["goggle"])
    if goggle_path.is_file():
        facts["denied_domains"] = sorted({
            line.split("site=", 1)[1].strip()
            for line in goggle_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("$discard,site=")
        })
    else:
        facts["goggle_error"] = f"missing {goggle_path}"

    window_h = int(p["conservation_window_hours"])
    try:
        async with pool.acquire() as conn:
            since = await conn.fetchval("SELECT min(at) FROM collections.content_events")
            added = await conn.fetchval(
                "SELECT count(*) FROM collections.content_events WHERE content_kind = 'card' AND to_status = 'published' "
                "AND at > NOW() - make_interval(hours => $1)", window_h)
            removed = await conn.fetch(
                "SELECT content_id, reason FROM collections.content_events WHERE content_kind = 'card' AND from_status = 'published' "
                "AND to_status <> 'published' AND at > NOW() - make_interval(hours => $1) ORDER BY at", window_h)
        facts["events"] = {
            "window_hours": window_h,
            "journal_since": since.isoformat() if since else None,
            "added": int(added or 0),
            "removed": [{"content_id": r["content_id"], "reason": r["reason"]} for r in removed],
        }
    except Exception as e:  # noqa: BLE001
        facts["events_error"] = str(e)[:200]

    zone = str(p.get("agenda_timezone") or "America/Denver")
    try:
        from gaius.engine.services.agenda_brief import gather_items, latest_brief
        from gaius.engine.services.agenda_notes import kb_root_from_env

        kb = kb_root_from_env()
        rows, _, _total = gather_items(kb, zone=zone, now=now_ts)
        horizon = [
            {
                "id": r.get("id") or "",
                "day": r.get("day") or "",
                "intent": r.get("intent") or "",
                "title": r.get("title") or "",
                "summary": r.get("summary") or "",
            }
            for r in rows
            if r.get("day") in ("today", "tomorrow", "week")
        ]
        spoken, brief = "", ""
        try:
            b = await latest_brief(pool)
            if b:
                spoken = str(b.get("spoken") or "")
                brief = str(b.get("body") or b.get("brief") or "")
        except Exception as e:  # noqa: BLE001
            facts["agenda_brief_error"] = str(e)[:160]
        facts["agenda"] = {
            "timezone": zone,
            "horizon": horizon,
            "spoken": spoken,
            "brief": brief,
        }
    except Exception as e:  # noqa: BLE001
        facts["agenda_error"] = str(e)[:200]
    return facts
