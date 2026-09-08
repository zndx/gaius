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


def _clip(text: str, n: int = 280) -> str:
    t = " ".join((text or "").split())
    if len(t) <= n:
        return t
    return t[: n - 1].rstrip() + "…"


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
