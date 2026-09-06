"""surface_integrity — the composite objective on the public surface.

One objective, three aspects, eight gates, all deterministic and all defined
on what a visitor RECEIVES at gaius.zndx.org (doctrine rule 2):

  currency      surface_newest_current · surface_band_current ·
                surface_refreshed_within_intent          (ex content_currency)
  integrity     no_marketing_shapes · no_denied_domains · no_duplicate_sources
  conservation  no_unexplained_removals · removal_reasons_declared

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

from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlsplit

GATES: tuple[str, ...] = (
    "surface_newest_current",
    "surface_band_current",
    "surface_refreshed_within_intent",
    "no_marketing_shapes",
    "no_denied_domains",
    "no_duplicate_sources",
    "no_unexplained_removals",
    "removal_reasons_declared",
)
ASPECT: dict[str, str] = {
    "surface_newest_current": "currency",
    "surface_band_current": "currency",
    "surface_refreshed_within_intent": "currency",
    "no_marketing_shapes": "integrity",
    "no_denied_domains": "integrity",
    "no_duplicate_sources": "integrity",
    "no_unexplained_removals": "conservation",
    "removal_reasons_declared": "conservation",
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
}


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
    """Pure: the eight gates from a facts dict (shape documented in the card's
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
        for g in ("surface_newest_current", "surface_band_current", "surface_refreshed_within_intent"):
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
    return facts
