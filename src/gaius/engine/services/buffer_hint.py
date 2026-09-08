"""Succinct dual-cognition glance for AgentRTC silence (CPU only).

Scratchpad streams are the live FIFOs: HN ambient + FMP prospects.
The attention-schema upper buffer is ``CognitionBuffer.succinct`` when
the RAM object is attached; otherwise SUMMARY-role FIFO rows (already
distilled) stand in. No Aperture / ColBERT — ServerQuery must not
touch thinking's GPU.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("gaius.engine.services.buffer_hint")

BUFFER_STREAMS = frozenset({"hn", "fmp", "buffer"})
_MAX = 8
_EXCERPT = 180


def _clip(text: str, n: int = _EXCERPT) -> str:
    t = " ".join((text or "").split())
    if len(t) <= n:
        return t
    return t[: n - 1].rstrip() + "…"


def _title(entry: Any) -> str:
    meta = getattr(entry, "metadata", None) or {}
    if not isinstance(meta, dict):
        meta = {}
    for key in ("story_title", "title", "symbol", "headline"):
        val = str(meta.get(key) or "").strip()
        if val:
            return val
    role = getattr(getattr(entry, "role", None), "value", None) or ""
    return role or "item"


def _hit(*, title: str, url: str, snippet: str, source: str, score: float) -> dict[str, Any]:
    return {
        "title": title,
        "url": url or "",
        "snippet": snippet,
        "source": source,
        "score": float(score),
    }


async def _fifo_hits(buf: Any, *, source: str, limit: int) -> list[dict[str, Any]]:
    if buf is None:
        return []
    try:
        snap = await buf.snapshot()
    except Exception as e:
        log.warning("%s snapshot failed: %s", source, e)
        return []
    newest = list(reversed(list(snap or [])))[:limit]
    hits: list[dict[str, Any]] = []
    for e in newest:
        hits.append(
            _hit(
                title=_title(e),
                url=str(getattr(e, "source_url", "") or ""),
                snippet=_clip(getattr(e, "content", "") or ""),
                source=source,
                score=0.7,
            )
        )
    return hits


def _attention_hits(buf: Any, *, limit: int) -> list[dict[str, Any]]:
    succinct = getattr(buf, "succinct", None)
    if not callable(succinct):
        return []
    rows = succinct(max_items=limit, excerpt=_EXCERPT) or []
    hits: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        flag = str(row.get("flag") or "HOLD")
        stream = str(row.get("stream") or "")
        role = str(row.get("role") or stream)
        code = str(row.get("code") or "")
        title = " ".join(p for p in (flag, stream, role) if p)
        if code:
            title = f"{title} {code}"
        hits.append(
            _hit(
                title=title.strip(),
                url="",
                snippet=str(row.get("excerpt") or ""),
                source="attention",
                score=1.0,
            )
        )
    return hits


def _spoken(hits: list[dict[str, Any]]) -> str:
    by: dict[str, list[dict[str, Any]]] = {}
    for h in hits:
        by.setdefault(str(h.get("source") or "other"), []).append(h)
    parts: list[str] = []
    att = by.get("attention") or []
    if att:
        bits = [f"{h['title']}: {h['snippet']}" for h in att[:4] if h.get("snippet")]
        if bits:
            parts.append("Attending " + "; ".join(bits))
    hn = by.get("hn") or []
    if hn:
        bits = [str(h.get("title") or h.get("snippet") or "") for h in hn[:4]]
        parts.append("HN: " + "; ".join(b for b in bits if b))
    fmp = by.get("fmp") or []
    if fmp:
        bits = [str(h.get("title") or h.get("snippet") or "") for h in fmp[:4]]
        parts.append("FMP: " + "; ".join(b for b in bits if b))
    return " ".join(parts)


async def collect_buffer(
    services: Any | None,
    *,
    stream: str = "buffer",
    limit: int = 6,
) -> dict[str, Any]:
    kind = (stream or "buffer").strip().lower() or "buffer"
    if kind not in BUFFER_STREAMS:
        kind = "buffer"
    n = max(1, min(int(limit or 6), _MAX))
    ambient = getattr(services, "ambient_service", None) if services is not None else None
    prospects = getattr(services, "prospects_service", None) if services is not None else None
    schema_buf = getattr(services, "cognition_buffer", None) if services is not None else None
    hits: list[dict[str, Any]] = []
    if kind in ("buffer",) and schema_buf is not None:
        hits.extend(_attention_hits(schema_buf, limit=n))
    if kind in ("hn", "buffer"):
        buf = getattr(ambient, "_buffer", None) if ambient is not None else None
        hits.extend(await _fifo_hits(buf, source="hn", limit=n))
    if kind in ("fmp", "buffer"):
        buf = getattr(prospects, "_buffer", None) if prospects is not None else None
        hits.extend(await _fifo_hits(buf, source="fmp", limit=n))
    spoken = _spoken(hits)
    note = spoken or "dual cognition buffer empty (HN ambient / FMP prospects / AST upper)"
    return {
        "project": "gaius",
        "query": "",
        "stream": kind,
        "hits": hits[: n * 3],
        "note": note,
        "spoken": spoken,
    }
