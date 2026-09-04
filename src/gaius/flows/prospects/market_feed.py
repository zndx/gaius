"""Market-wide FMP streams as prospects FIFO entries.

Moved out of ProspectsService.ingest_market_buffer (2026-09-04) so the
``fmp_roll`` flow owns the pull; the engine no longer rolls this buffer on
its own timer. Pure formatting + one FMP session; no buffer or DB here.
"""

from __future__ import annotations

from typing import Any

from gaius.engine.services.ambient_buffer import BufferEntry


def format_market_row(kind: str, row: dict[str, Any]) -> str:
    """Turn one FMP market row into FIFO prose."""
    symbol = str(row.get("symbol") or row.get("ticker") or "")
    title = str(
        row.get("title")
        or row.get("companyName")
        or row.get("targetedCompanyName")
        or row.get("reportingName")
        or symbol
    )
    when = str(
        row.get("publishedDate")
        or row.get("filingDate")
        or row.get("transactionDate")
        or row.get("acceptedDate")
        or row.get("date")
        or ""
    )
    body = str(
        row.get("text")
        or row.get("content")
        or row.get("snippet")
        or row.get("description")
        or row.get("formType")
        or row.get("transactionType")
        or ""
    )
    extra = ""
    if row.get("formType"):
        extra = f" form={row.get('formType')}"
    if row.get("chamber"):
        extra += f" chamber={row.get('chamber')}"
    if row.get("link") or row.get("url") or row.get("finalLink"):
        extra += f" {row.get('finalLink') or row.get('link') or row.get('url')}"
    text = f"{kind} {symbol} {when}\n{title}{extra}\n{body}".strip()
    return text[:2500]


async def fetch_market_entries(watch: set[str]) -> tuple[list[BufferEntry], list[str]]:
    """Pull the seven market-wide FMP streams; returns (entries, errors).

    Each stream failing is an error string, not an exception: one dark
    endpoint must not lose the other six. Zero entries overall is the
    caller's failure (#PS.00000007.FMPEMPTY).
    """
    from gaius.engine.services.fmp_client import FMPClient, FMPClientConfig
    from gaius.engine.services.prospects_buffer import ProspectsRole, entry

    errors: list[str] = []
    pulls: list[tuple[str, list[dict], str]] = []
    async with FMPClient(FMPClientConfig(capture_enabled=False)) as fmp:
        for stream, kind, call in (
            ("stock-news", "news", lambda: fmp.get_latest_stock_news(limit=15)),
            ("general-news", "news", lambda: fmp.get_latest_general_news(limit=8)),
            ("fmp-articles", "article", lambda: fmp.get_fmp_articles(limit=8)),
            ("8k", "8-K", lambda: fmp.get_latest_8k(days=7, limit=20)),
            ("insider", "insider", lambda: fmp.get_latest_insider(limit=15)),
            ("ma", "m&a", lambda: fmp.get_latest_mergers(limit=10)),
            ("congress", "congress", lambda: fmp.get_latest_congress(limit=8)),
        ):
            try:
                pulls.append((stream, await call(), kind))
            except Exception as e:  # noqa: BLE001 — collected, reported
                errors.append(f"{stream}: {e}")

    out: list[BufferEntry] = []
    for stream, rows, kind in pulls:
        for row in rows:
            text = format_market_row(kind, row)
            if not text:
                continue
            symbol = str(row.get("symbol") or row.get("ticker") or "")
            out.append(
                entry(
                    ProspectsRole.FMP,
                    text,
                    stream=stream,
                    kind=kind,
                    symbol=symbol,
                    primary=symbol in watch,
                    title=str(row.get("title") or row.get("companyName") or symbol),
                )
            )
    return out, errors
