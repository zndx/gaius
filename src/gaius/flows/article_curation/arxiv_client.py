"""Serialized GET client for export.arxiv.org.

arXiv rate-limits at about one request every three seconds. Parallel calls
from the same IP 429 quickly. POST /api/query bypasses their cache. A
descriptive User-Agent is required. 429s wait Retry-After or exponential
backoff; in-flight requests are one-at-a-time.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

ARXIV_API_HOST = "export.arxiv.org"
USER_AGENT = "Gaius-Curation/0.2.0 (https://github.com/zndx/gaius; lattice article curation)"
MIN_INTERVAL_S = 3.0
MAX_TRIES = 5
MAX_RESULTS_CAP = 25
ROBOTS_URL = "https://arxiv.org/robots.txt"

_async_lock = asyncio.Lock()
_sync_lock = threading.Lock()
_last_mono = 0.0
_robots_ok: bool | None = None
_robots_at = 0.0


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


def _headers() -> dict[str, str]:
    return {"User-Agent": USER_AGENT, "Accept": "application/atom+xml,application/xml,text/xml"}


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


def _assert_api_path(url: str) -> None:
    parsed = urlparse(url)
    if parsed.hostname != ARXIV_API_HOST:
        raise RuntimeError(f"arxiv_client only fetches {ARXIV_API_HOST}, not {parsed.hostname}")
    if not parsed.path.startswith("/api/query"):
        raise RuntimeError(f"arxiv_client refuses path {parsed.path} (robots: API query only)")


def robots_allows_api() -> bool:
    """Cached robots.txt: /api/query must not be disallowed. Fail-open if unread."""
    global _robots_ok, _robots_at
    now = time.monotonic()
    if _robots_ok is not None and now - _robots_at < 3600:
        return _robots_ok
    try:
        import urllib.request

        req = urllib.request.Request(ROBOTS_URL, headers=_headers(), method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 — fixed host
            body = resp.read().decode("utf-8", "replace")
        disallowed = False
        ua_star = False
        for line in body.splitlines():
            low = line.strip().lower()
            if low.startswith("user-agent:"):
                ua_star = "*" in line.split(":", 1)[-1]
            elif ua_star and low.startswith("disallow:"):
                path = line.split(":", 1)[-1].strip()
                if path in ("/api", "/api/", "/api/query"):
                    disallowed = True
        _robots_ok = not disallowed
    except Exception:
        logger.info("arxiv robots.txt unread; allowing /api/query")
        _robots_ok = True
    _robots_at = now
    return bool(_robots_ok)


async def arxiv_get(url: str, *, timeout: float = 30.0) -> Any:
    """One-at-a-time GET. Raises RuntimeError on 429 exhaustion or non-200."""
    _assert_api_path(url)
    if not robots_allows_api():
        raise RuntimeError("arxiv robots.txt disallows /api/query")
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
                # Fastly "Rate exceeded." has no Retry-After. Extra GETs
                # deepen the ban (2026-09-13 curate; 2026-09-14 verify).
                if not raw:
                    raise RuntimeError(
                        "arXiv API returned 429 with no Retry-After; not retrying.\n"
                        "  Guru Meditation: #ACF.00000007.NOSOURCES\n"
                        "  Probe once later; do not loop."
                    )
                delay = _retry_after_s(response, attempt)
                if delay > 120:
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
                    f"arXiv API returned status {response.status_code}.\n"
                    "  Guru Meditation: #ACF.00000007.NOSOURCES\n"
                    "  Check network connectivity and arXiv API status"
                )
            return response
    raise RuntimeError(
        f"{last_exc or 'arXiv GET exhausted retries'}\n"
        "  Guru Meditation: #ACF.00000007.NOSOURCES\n"
        "  Check network connectivity and arXiv API status"
    )


def arxiv_get_sync(url: str, *, timeout: float = 10.0) -> bytes:
    """Serialized sync GET (metadata). Same UA, interval, and path rules."""
    import urllib.request

    _assert_api_path(url)
    if not robots_allows_api():
        raise RuntimeError("arxiv robots.txt disallows /api/query")
    global _last_mono
    with _sync_lock:
        wait = MIN_INTERVAL_S - (time.monotonic() - _last_mono)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers=_headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed host
                body = resp.read()
        finally:
            _last_mono = time.monotonic()
    return body
