"""ServerQuery SEARCH — Gaius KB + Brave web, no GPU vector load.

AgentRTC looks things up on interrupt without evicting thinking. Empty
hits plus `note` is honest (no key, no matches, store error).
"""
from __future__ import annotations

import logging
import os
from typing import Any

from gaius.engine.services.buffer_hint import BUFFER_STREAMS, collect_buffer

log = logging.getLogger("gaius.engine.services.search_hint")

_MAX = 8
_CARD_URL = "https://gaius.zndx.org/cards/{card_id}"


def _clip(text: str, n: int = 280) -> str:
    t = " ".join((text or "").split())
    if len(t) <= n:
        return t
    return t[: n - 1].rstrip() + "…"


def _pool_of(services: Any | None) -> Any | None:
    pool = getattr(services, "db_pool", None)
    if pool is not None:
        return pool
    cog = getattr(services, "cognition_service", None)
    return getattr(cog, "_db_pool", None) if cog is not None else None


async def published_card_hits(pool: Any | None, query: str, limit: int) -> list[dict[str, Any]]:
    """Published cards are the local rows gaius.zndx.org serves.

    A voice query often adds words that are not in the card. Title coverage
    still returns the card; a summary-only scrape of one shared word does not.
    """
    from gaius.storage.kb_ops import document_rank_key, query_tokens

    tokens = query_tokens(query)
    if pool is None or not tokens:
        return []
    patterns = [f"%{token}%" for token in tokens[:6]]
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT card_id, title, COALESCE(summary, '') AS summary
                  FROM collections.cards
                 WHERE status = 'published'
                   AND (
                        title ILIKE ANY($1::text[])
                     OR summary ILIKE ANY($1::text[])
                   )
                 ORDER BY published_at DESC NULLS LAST
                 LIMIT 80
                """,
                patterns,
            )
    except Exception as e:
        log.warning("published card search failed: %s", e)
        raise
    ranked: list[tuple[tuple[int, int, int, int], dict[str, Any]]] = []
    for row in rows:
        title = str(row["title"] or "")
        summary = str(row["summary"] or "")
        text = f"# {title}\n{summary}"
        key = document_rank_key(f"cards/{row['card_id']}.md", text, query)
        # One shared word ("state") is not the published note. Two title
        # words are, and a one-word query still matches that one word.
        need = 2 if len(tokens) >= 2 else 1
        if key is None or key[0] < need:
            continue
        ranked.append((key, {
            "title": title,
            "url": _CARD_URL.format(card_id=row["card_id"]),
            "snippet": _clip(summary or title),
            "source": "card",
            "score": 1.0,
        }))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [hit for _key, hit in ranked[: max(1, limit)]]


async def collect_search(
    query: str,
    *,
    stream: str = "",
    limit: int = 0,
    services: Any | None = None,
) -> dict[str, Any]:
    q = " ".join((query or "").split())
    kind = (stream or "all").strip().lower() or "all"
    if kind in BUFFER_STREAMS:
        return await collect_buffer(services, stream=kind, limit=limit)
    if kind not in ("kb", "web", "all"):
        kind = "all"
    n = int(limit or 0) or 6
    n = max(1, min(n, _MAX))
    notes: list[str] = []
    hits: list[dict[str, Any]] = []
    if not q:
        return {
            "project": "gaius",
            "query": "",
            "stream": kind,
            "hits": [],
            "note": "empty query",
        }
    if kind in ("kb", "all"):
        try:
            hits.extend(await published_card_hits(_pool_of(services), q, min(2, n)))
        except Exception as e:
            log.warning("published card search failed: %s", e)
            notes.append(f"cards: {e}"[:160])
        try:
            from gaius.storage.kb_ops import search_kb

            rows = await search_kb(q, max_results=n)
            for r in rows:
                hits.append(
                    {
                        "title": (r.path or "").rsplit("/", 1)[-1],
                        "url": r.path or "",
                        "snippet": _clip(r.preview or ""),
                        "source": "kb",
                        "score": 1.0 if r.match_type == "filename" else 0.6,
                    }
                )
        except Exception as e:
            log.warning("kb search failed: %s", e)
            notes.append(f"kb: {e}"[:160])
    if kind in ("web", "all"):
        key = (
            os.environ.get("BRAVE_API_KEY")
            or os.environ.get("BRAVE_SEARCH_API_KEY")
            or ""
        ).strip()
        if not key:
            notes.append("web: Brave key not configured")
        else:
            try:
                from gaius.search.brave import BraveSearch

                brave = BraveSearch(api_key=key)
                rows = await brave.search(q, count=n)
                for r in rows:
                    hits.append(
                        {
                            "title": r.title or "",
                            "url": r.url or "",
                            "snippet": _clip(r.snippet or ""),
                            "source": "web",
                            "score": 0.0,
                        }
                    )
            except Exception as e:
                log.warning("brave search failed: %s", e)
                notes.append(f"web: {e}"[:160])
    note = "; ".join(notes)
    if not hits and not note:
        note = "no matches"
    return {
        "project": "gaius",
        "query": q,
        "stream": kind,
        "hits": hits[: n * (2 if kind == "all" else 1)],
        "note": note,
    }


def to_proto(d: dict[str, Any]):
    from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb

    hint = zpb.SearchHint(
        project=str(d.get("project") or "gaius"),
        query=str(d.get("query") or ""),
        stream=str(d.get("stream") or ""),
        note=str(d.get("note") or ""),
    )
    for h in d.get("hits") or []:
        hint.hits.add(
            title=str(h.get("title") or ""),
            url=str(h.get("url") or ""),
            snippet=str(h.get("snippet") or ""),
            source=str(h.get("source") or ""),
            score=float(h.get("score") or 0.0),
        )
    return hint
