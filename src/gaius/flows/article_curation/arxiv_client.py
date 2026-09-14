"""Polite arXiv access for curation.

ToU (info.arxiv.org/help/api/tou.html): GET export.arxiv.org/api/query,
one request every three seconds, single connection. POST bypasses Fastly
cache and trips origin limits. A 429 with body "Rate exceeded." and no
Retry-After is *capacity*, not the 3s rule — staff: try later; a 503 is
what they use for *your* excessive use. Fastly penalty boxes are often
1–15 min; we open a 15 min circuit and do not retry.

Discovery for the content objective is RSS-first (rss.arxiv.org/rss/CAT,
one GET per category, 6h cache). Keyword ranking is local. The search
API is a last resort only when RSS is empty and the circuit is closed.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

ARXIV_API_HOST = "export.arxiv.org"
ARXIV_RSS_HOST = "rss.arxiv.org"
USER_AGENT = "Gaius-Curation/0.2.0 (https://github.com/zndx/gaius; lattice article curation)"
MIN_INTERVAL_S = 3.0
MAX_TRIES = 5
MAX_RESULTS_CAP = 25
CIRCUIT_OPEN_S = 15 * 60
RSS_TTL_S = 6 * 3600
QUERY_TTL_S = 24 * 3600
ROBOTS_URL = "https://arxiv.org/robots.txt"

_async_lock = asyncio.Lock()
_sync_lock = threading.Lock()
_last_mono = 0.0
_robots_ok: bool | None = None
_robots_at = 0.0


class CircuitOpen(RuntimeError):
    """arXiv 429 without Retry-After — do not GET until the circuit closes."""


@dataclass
class ArxivPaper:
    arxiv_id: str
    url: str
    title: str
    summary: str = ""
    authors: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    published: str = ""
    via: str = "rss"


def cache_root() -> Path:
    raw = os.environ.get("GAIUS_ARXIV_CACHE")
    if raw:
        return Path(raw)
    return Path.home() / ".cache" / "gaius" / "arxiv-atom"


def _circuit_path() -> Path:
    return cache_root() / "circuit_open_until"


def circuit_blocked() -> bool:
    p = _circuit_path()
    if not p.is_file():
        return False
    try:
        until = float(p.read_text().strip())
    except ValueError:
        p.unlink(missing_ok=True)
        return False
    if time.time() < until:
        return True
    p.unlink(missing_ok=True)
    return False


def open_circuit(seconds: float = CIRCUIT_OPEN_S) -> None:
    root = cache_root()
    root.mkdir(parents=True, exist_ok=True)
    _circuit_path().write_text(str(time.time() + float(seconds)))
    logger.warning("arXiv circuit open for %.0fs (headerless 429)", seconds)


def cap_max_results(n: int) -> int:
    try:
        want = int(n)
    except (TypeError, ValueError):
        want = 10
    return max(1, min(want, MAX_RESULTS_CAP))


def query_url(params: dict[str, Any]) -> str:
    from urllib.parse import urlencode

    capped = dict(params)
    if "max_results" in capped:
        capped["max_results"] = cap_max_results(capped["max_results"])
    return f"https://{ARXIV_API_HOST}/api/query?{urlencode(capped)}"


def rss_url(category: str) -> str:
    cat = re.sub(r"[^A-Za-z0-9.-]", "", (category or "").strip())
    if not cat:
        raise RuntimeError("arxiv rss category empty")
    return f"https://{ARXIV_RSS_HOST}/rss/{cat}"


def id_list_url(arxiv_ids: list[str]) -> str:
    ids = [i.strip() for i in arxiv_ids if i and i.strip()][:MAX_RESULTS_CAP]
    return query_url({"id_list": ",".join(ids), "max_results": len(ids) or 1})


def _headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/atom+xml,application/rss+xml,application/xml,text/xml",
    }


def _retry_after_s(response: Any, attempt: int) -> float:
    raw = ""
    try:
        if response is not None:
            raw = (response.headers.get("Retry-After") or "").strip()
    except Exception:
        raw = ""
    if raw.isdigit():
        return max(MIN_INTERVAL_S, float(raw))
    if raw:
        try:
            when = parsedate_to_datetime(raw)
            return max(MIN_INTERVAL_S, (when.timestamp() - time.time()))
        except Exception:
            pass
    return MIN_INTERVAL_S * (2 ** max(0, attempt))


def _assert_allowed(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    path = parsed.path or ""
    if host == ARXIV_API_HOST and path.startswith("/api/query"):
        return
    if host == ARXIV_RSS_HOST and path.startswith("/rss/"):
        return
    raise RuntimeError(f"arxiv_client refuses {host}{path}")


def robots_allows_api() -> bool:
    """www robots.txt is not the export.arxiv.org ToU. Fail-open; ToU governs GET."""
    global _robots_ok, _robots_at
    now = time.monotonic()
    if _robots_ok is not None and now - _robots_at < 3600:
        return _robots_ok
    _robots_ok = True
    _robots_at = now
    return True


class _CachedResp:
    def __init__(self, body: bytes, url: str):
        self.content = body
        self.text = body.decode("utf-8", "replace")
        self.status_code = 200
        self.headers: dict[str, str] = {}
        self.url = url


def _cache_file(url: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()
    return cache_root() / "bodies" / f"{digest}.xml"


def _read_cache(url: str, ttl_s: float, *, allow_stale: bool) -> bytes | None:
    path = _cache_file(url)
    if not path.is_file():
        return None
    age = time.time() - path.stat().st_mtime
    if age <= ttl_s or allow_stale:
        return path.read_bytes()
    return None


def _write_cache(url: str, body: bytes) -> None:
    path = _cache_file(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def _raise_headerless_429() -> None:
    open_circuit()
    raise CircuitOpen(
        "arXiv API returned 429 with no Retry-After; circuit open "
        f"{CIRCUIT_OPEN_S:.0f}s.\n"
        "  Guru Meditation: #ACF.00000007.NOSOURCES\n"
        "  Probe once later; do not loop."
    )


async def arxiv_get(url: str, *, timeout: float = 30.0) -> Any:
    """One-at-a-time GET. Headerless 429 opens the 15 min circuit."""
    _assert_allowed(url)
    if circuit_blocked():
        raise CircuitOpen("arXiv circuit open; not GET-ing")
    last_exc: Exception | None = None
    global _last_mono
    async with httpx.AsyncClient(timeout=timeout, headers=_headers()) as client:
        for attempt in range(MAX_TRIES):
            async with _async_lock:
                wait = MIN_INTERVAL_S - (time.monotonic() - _last_mono)
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    response = await client.get(url)
                except httpx.RequestError as e:
                    last_exc = e
                    _last_mono = time.monotonic()
                    response = None
                else:
                    _last_mono = time.monotonic()
            if response is None:
                await asyncio.sleep(MIN_INTERVAL_S * (2 ** attempt))
                continue
            if response.status_code == 429:
                raw = ""
                try:
                    raw = (response.headers.get("Retry-After") or "").strip()
                except Exception:
                    raw = ""
                if not raw:
                    _raise_headerless_429()
                delay = _retry_after_s(response, attempt)
                if delay > 120:
                    open_circuit()
                    raise RuntimeError(
                        f"arXiv API returned 429 Retry-After {delay:.0f}s; not waiting.\n"
                        "  Guru Meditation: #ACF.00000007.NOSOURCES"
                    )
                logger.warning("arXiv 429; backoff %.1fs (attempt %s)", delay, attempt + 1)
                await asyncio.sleep(delay)
                last_exc = RuntimeError(f"arXiv API returned status 429 (attempt {attempt + 1})")
                continue
            if response.status_code != 200:
                raise RuntimeError(
                    f"arXiv GET status {response.status_code}.\n"
                    "  Guru Meditation: #ACF.00000007.NOSOURCES"
                )
            return response
    raise RuntimeError(
        f"{last_exc or 'arXiv GET exhausted retries'}\n"
        "  Guru Meditation: #ACF.00000007.NOSOURCES"
    )


def arxiv_get_sync(url: str, *, timeout: float = 10.0) -> bytes:
    """Serialized sync GET. Same hosts, interval, and 429 circuit."""
    import urllib.error
    import urllib.request

    _assert_allowed(url)
    if circuit_blocked():
        raise CircuitOpen("arXiv circuit open; not GET-ing")
    global _last_mono
    with _sync_lock:
        wait = MIN_INTERVAL_S - (time.monotonic() - _last_mono)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers=_headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                body = resp.read()
        except urllib.error.HTTPError as e:
            _last_mono = time.monotonic()
            if e.code == 429:
                _raise_headerless_429()
            raise
        finally:
            _last_mono = time.monotonic()
    return body


async def cached_get(url: str, *, ttl_s: float) -> _CachedResp:
    """Fresh cache, else GET (or stale cache if the circuit is open)."""
    allow_stale = circuit_blocked()
    hit = _read_cache(url, ttl_s, allow_stale=allow_stale)
    if hit is not None:
        return _CachedResp(hit, url)
    if circuit_blocked():
        raise CircuitOpen("arXiv circuit open and no cached body")
    resp = await arxiv_get(url)
    body = resp.content if hasattr(resp, "content") else resp.text.encode("utf-8")
    _write_cache(url, body)
    return _CachedResp(body, url)


def _extract_arxiv_id(text: str) -> str:
    m = re.search(r"(\d{4}\.\d{4,5})", text or "")
    if m:
        return m.group(1)
    m = re.search(r"([a-z-]+/\d{7})", text or "")
    return m.group(1) if m else ""


def parse_feed(body: bytes | str, *, via: str) -> list[ArxivPaper]:
    import feedparser

    feed = feedparser.parse(body)
    papers: list[ArxivPaper] = []
    seen: set[str] = set()
    for entry in feed.entries:
        raw_id = entry.get("id") or entry.get("link") or ""
        arxiv_id = _extract_arxiv_id(str(raw_id))
        if not arxiv_id or arxiv_id in seen:
            continue
        seen.add(arxiv_id)
        authors = []
        for author in entry.get("authors") or []:
            name = author.get("name") if isinstance(author, dict) else str(author)
            if name:
                authors.append(name)
        if not authors and entry.get("author"):
            authors = [str(entry.get("author"))]
        categories = []
        for tag in entry.get("tags") or []:
            term = tag.get("term") if isinstance(tag, dict) else str(tag)
            if term:
                categories.append(term)
        published = str(entry.get("published") or entry.get("updated") or "")
        title = str(entry.get("title") or "").replace("\n", " ").strip()
        summary = str(entry.get("summary") or entry.get("description") or "").strip()
        link = str(entry.get("link") or f"https://arxiv.org/abs/{arxiv_id}")
        papers.append(
            ArxivPaper(
                arxiv_id=arxiv_id,
                url=link if "arxiv.org" in link else f"https://arxiv.org/abs/{arxiv_id}",
                title=title,
                summary=summary[:2000],
                authors=authors,
                categories=categories,
                published=published,
                via=via,
            )
        )
    return papers


def _rank(papers: list[ArxivPaper], keywords: list[str]) -> list[ArxivPaper]:
    tokens = [k for k in keywords if k and len(k) >= 4]
    if not tokens:
        return papers
    hits: list[ArxivPaper] = []
    rest: list[ArxivPaper] = []
    lowered = [t.lower() for t in tokens]
    for p in papers:
        blob = f"{p.title} {p.summary}".lower()
        if any(t in blob for t in lowered):
            hits.append(p)
        else:
            rest.append(p)
    return hits + rest


async def _rss_papers(category: str) -> list[ArxivPaper]:
    """One RSS GET per category. Empty weekend feeds do not clobber a good cache."""
    url = rss_url(category)
    stale = _read_cache(url, 7 * 86400, allow_stale=True)
    fresh = _read_cache(url, RSS_TTL_S, allow_stale=False)
    if fresh:
        papers = parse_feed(fresh, via="rss")
        if papers:
            return papers
    if circuit_blocked():
        return parse_feed(stale, via="rss") if stale else []
    try:
        resp = await arxiv_get(url)
    except CircuitOpen:
        return parse_feed(stale, via="rss") if stale else []
    except RuntimeError as e:
        logger.warning("arXiv RSS %s failed: %s", category, e)
        return parse_feed(stale, via="rss") if stale else []
    body = resp.content if hasattr(resp, "content") else resp.text.encode("utf-8")
    papers = parse_feed(body, via="rss")
    if papers:
        _write_cache(url, body)
        return papers
    # skipDays Sat/Sun: channel exists, items empty. Keep Friday's cache.
    logger.info("arXiv RSS %s empty (weekend skipDays?); keeping stale cache", category)
    return parse_feed(stale, via="rss") if stale else []


async def discover_papers(
    categories: list[str],
    keywords: list[str] | None = None,
    max_results: int = 10,
) -> list[ArxivPaper]:
    """RSS-first discovery. Search API only if every RSS miss and circuit closed."""
    n = cap_max_results(max_results)
    cats = [c for c in (categories or []) if c][:3]
    if not cats:
        raise RuntimeError("discover_papers needs arxiv_categories")
    papers: list[ArxivPaper] = []
    for cat in cats:
        papers.extend(await _rss_papers(cat))
    if papers:
        return _rank(papers, keywords or [])[:n]
    if circuit_blocked():
        raise CircuitOpen("arXiv circuit open and RSS cache empty")
    # Last resort: one capped category search GET, cached a day.
    cat_q = " OR ".join(f"cat:{c}" for c in cats)
    url = query_url(
        {
            "search_query": cat_q,
            "start": 0,
            "max_results": n,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    resp = await cached_get(url, ttl_s=QUERY_TTL_S)
    return parse_feed(resp.content, via="search")[:n]
