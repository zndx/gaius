"""SEC EDGAR Filing Sync Client for the Gaius Engine.

Fetches raw filing content from SEC EDGAR with sync semantics:
- Check if filing exists in HX before fetching (by accession_number)
- Skip fetch if content already synced
- Sync new filings to HX Iceberg storage

Architecture:
1. EdgarSyncClient: Check-then-fetch with deduplication
2. ProspectsFlow (Metaflow): Batch sync + docling extraction
3. ProspectsService: Query extracted content for LLM analysis

SEC EDGAR Access Requirements:
- User-Agent header with contact email (SEC policy)
- Rate limiting: max 10 requests/second (we use 2/sec conservative)
- No authentication required

Guru Meditation Codes:
- #EDGAR.00000001.FETCHFAIL: Failed to fetch filing from SEC
- #EDGAR.00000002.PARSEFAIL: Failed to parse filing content
- #EDGAR.00000003.RATELIMIT: Rate limit exceeded
- #EDGAR.00000004.NOLINK: No valid filing link provided
- #EDGAR.00000005.SYNCFAIL: Failed to sync filing to HX
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from gaius.hx.edgar import EdgarFiling, EdgarFilingSync, SyncResult, get_edgar_sync

logger = logging.getLogger(__name__)


class EdgarClientError(Exception):
    """EDGAR client error with Guru Meditation code."""

    def __init__(self, message: str, guru_code: str | None = None):
        super().__init__(message)
        self.guru_code = guru_code

    def __str__(self) -> str:
        if self.guru_code:
            return f"{super().__str__()}\n  Guru Meditation: {self.guru_code}"
        return super().__str__()


@dataclass
class EdgarClientConfig:
    """Configuration for SEC EDGAR client."""

    # User-Agent with contact email (required by SEC)
    user_agent: str = "Gaius Research gaius@zndx.dev"

    # Rate limiting (SEC allows 10/sec, we use 2/sec conservative)
    requests_per_second: float = 2.0

    # Request settings
    timeout_s: float = 30.0
    max_retries: int = 3
    retry_delay_s: float = 2.0

    # Content extraction settings
    max_content_chars: int = 100000  # ~25K tokens max


@dataclass
class RateLimiter:
    """Simple rate limiter for SEC EDGAR requests."""

    requests_per_second: float = 2.0
    _last_request: float = field(default=0.0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def acquire(self) -> None:
        """Wait until we can make another request."""
        async with self._lock:
            now = time.monotonic()
            min_interval = 1.0 / self.requests_per_second
            elapsed = now - self._last_request

            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)

            self._last_request = time.monotonic()


@dataclass
class FilingContent:
    """Content fetched from an SEC filing.

    Used for immediate access to filing content. For sync operations,
    use EdgarFiling directly.
    """

    url: str
    filing_type: str
    symbol: str

    # Raw content
    raw_html: str
    raw_html_length: int

    # Metadata
    title: str = ""
    filing_date: str = ""
    cik: str = ""
    accession_number: str = ""

    # Fetch metadata
    fetch_latency_ms: int = 0

    # Extracted text (populated by Metaflow docling step, empty initially)
    extracted_text: str = ""
    extracted_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "url": self.url,
            "filing_type": self.filing_type,
            "symbol": self.symbol,
            "raw_html_length": self.raw_html_length,
            "title": self.title,
            "filing_date": self.filing_date,
            "cik": self.cik,
            "accession_number": self.accession_number,
            "fetch_latency_ms": self.fetch_latency_ms,
            "extracted_text": self.extracted_text,
            "extracted_at": self.extracted_at,
        }


class EdgarClient:
    """Async client for fetching SEC EDGAR filing content with sync semantics.

    Integrates with EdgarFilingSync for idempotent sync operations:
    - Checks if filing exists before fetching
    - Syncs new filings to HX Iceberg storage
    - Skips already-synced filings

    Usage:
        async with EdgarClient() as client:
            # Sync a filing (checks if exists, fetches if not)
            filing = await client.sync_filing(
                accession_number="0001104659-26-001107",
                url="https://www.sec.gov/Archives/edgar/data/...",
                symbol="CHTR",
                filing_type="8-K",
            )

            # Or fetch without sync for immediate use
            content = await client.fetch_filing(
                url="https://www.sec.gov/...",
                filing_type="8-K",
                symbol="CHTR",
            )
    """

    def __init__(
        self,
        config: EdgarClientConfig | None = None,
        sync_enabled: bool = True,
    ):
        """Initialize EDGAR client.

        Args:
            config: Client configuration.
            sync_enabled: Whether to sync filings to HX.
        """
        self._config = config or EdgarClientConfig()
        self._rate_limiter = RateLimiter(
            requests_per_second=self._config.requests_per_second
        )
        self._http_client: httpx.AsyncClient | None = None
        self._sync_enabled = sync_enabled
        self._sync = get_edgar_sync() if sync_enabled else None

    async def __aenter__(self) -> "EdgarClient":
        """Async context manager entry."""
        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._config.timeout_s),
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def exists(self, accession_number: str) -> bool:
        """Check if a filing exists in HX.

        Args:
            accession_number: SEC accession number.

        Returns:
            True if filing already synced.
        """
        if not self._sync:
            return False
        return await self._sync.exists(accession_number)

    async def sync_filing(
        self,
        accession_number: str,
        url: str,
        symbol: str,
        filing_type: str,
        cik: str = "",
        filing_date: str = "",
    ) -> EdgarFiling | None:
        """Sync a filing to HX (idempotent - skips if exists).

        Args:
            accession_number: SEC accession number (primary key).
            url: Direct URL to filing.
            symbol: Stock symbol.
            filing_type: Filing type (10-K, 10-Q, 8-K, etc.).
            cik: Central Index Key.
            filing_date: Filing date.

        Returns:
            EdgarFiling if synced or already exists, None if sync disabled.
        """
        if not self._sync:
            return None

        # Check if already exists
        if await self._sync.exists(accession_number):
            logger.debug(f"Filing {accession_number} already synced, skipping fetch")
            return None  # Already synced

        # Fetch from SEC
        content = await self.fetch_filing(
            url=url,
            filing_type=filing_type,
            symbol=symbol,
            filing_date=filing_date,
            cik=cik,
            accession_number=accession_number,
        )

        # Create filing record
        filing = EdgarFiling(
            accession_number=accession_number,
            symbol=symbol,
            cik=cik,
            filing_type=filing_type,
            filing_date=filing_date,
            url=url,
            raw_html=content.raw_html,
            title=content.title,
            fetched_at=datetime.now(timezone.utc),
            fetch_latency_ms=content.fetch_latency_ms,
        )

        # Sync to HX
        result = await self._sync.sync_filing(filing)
        if not result.success:
            raise EdgarClientError(
                f"Failed to sync filing {accession_number}: {result.errors}",
                guru_code="#EDGAR.00000005.SYNCFAIL",
            )

        return filing

    async def sync_filings_batch(
        self,
        filings_metadata: list[dict],
        symbol: str,
    ) -> SyncResult:
        """Sync multiple filings (batch operation).

        Args:
            filings_metadata: List of filing metadata dicts from FMP.
            symbol: Stock symbol.

        Returns:
            SyncResult with counts.
        """
        if not self._sync:
            return SyncResult(success=True)

        # Create EdgarFiling objects from metadata (without content)
        filings = [EdgarFiling.from_fmp_filing(m, symbol) for m in filings_metadata]

        # Check which already exist
        accessions = [f.accession_number for f in filings]
        existing = await self._sync.get_existing_accessions(accessions)

        # Filter to net-new filings
        new_filings = [f for f in filings if f.accession_number not in existing]

        result = SyncResult(
            success=True,
            filings_checked=len(filings),
            filings_skipped=len(existing),
            filings_new=len(new_filings),
        )

        if not new_filings:
            logger.info(f"All {len(filings)} filings already synced for {symbol}")
            return result

        # Fetch and sync new filings
        for filing in new_filings:
            try:
                synced = await self.sync_filing(
                    accession_number=filing.accession_number,
                    url=filing.url,
                    symbol=filing.symbol,
                    filing_type=filing.filing_type,
                    cik=filing.cik,
                    filing_date=filing.filing_date,
                )
                if synced:
                    result.filings_fetched += 1
            except EdgarClientError as e:
                logger.warning(f"Failed to sync {filing.accession_number}: {e}")
                result.errors.append(str(e))

        result.success = len(result.errors) == 0
        logger.info(str(result))
        return result

    async def fetch_filing(
        self,
        url: str,
        filing_type: str,
        symbol: str,
        filing_date: str = "",
        cik: str = "",
        accession_number: str = "",
    ) -> FilingContent:
        """Fetch raw content from an SEC filing (without syncing).

        Use sync_filing() for idempotent sync operations.

        Args:
            url: Direct URL to filing (finalLink from FMP).
            filing_type: Filing type (10-K, 10-Q, 8-K, etc.).
            symbol: Stock symbol.
            filing_date: Filing date for metadata.
            cik: Central Index Key.
            accession_number: SEC accession number.

        Returns:
            FilingContent with raw HTML.

        Raises:
            EdgarClientError: If fetch fails.
        """
        if not url:
            raise EdgarClientError(
                "No filing URL provided",
                guru_code="#EDGAR.00000004.NOLINK",
            )

        if not url.startswith("https://www.sec.gov/"):
            raise EdgarClientError(
                f"Invalid SEC EDGAR URL: {url}",
                guru_code="#EDGAR.00000004.NOLINK",
            )

        if self._http_client is None:
            raise EdgarClientError(
                "EdgarClient must be used as async context manager",
                guru_code="#EDGAR.00000001.FETCHFAIL",
            )

        # Rate limit
        await self._rate_limiter.acquire()

        headers = {
            "User-Agent": self._config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        start_time = time.monotonic()
        last_error: Exception | None = None

        for attempt in range(self._config.max_retries):
            try:
                response = await self._http_client.get(url, headers=headers)
                latency_ms = int((time.monotonic() - start_time) * 1000)

                if response.status_code == 200:
                    raw_html = response.text

                    # Extract title from HTML
                    title_match = re.search(r"<title[^>]*>([^<]+)</title>", raw_html, re.I)
                    title = title_match.group(1).strip() if title_match else ""

                    content = FilingContent(
                        url=url,
                        filing_type=filing_type,
                        symbol=symbol,
                        raw_html=raw_html,
                        raw_html_length=len(raw_html),
                        title=title,
                        filing_date=filing_date,
                        cik=cik,
                        accession_number=accession_number,
                        fetch_latency_ms=latency_ms,
                    )

                    logger.info(
                        f"Fetched {filing_type} for {symbol}: "
                        f"{content.raw_html_length} bytes, {latency_ms}ms"
                    )

                    return content

                elif response.status_code == 403:
                    raise EdgarClientError(
                        "SEC EDGAR access forbidden (403). Check User-Agent header.",
                        guru_code="#EDGAR.00000001.FETCHFAIL",
                    )

                elif response.status_code == 429:
                    raise EdgarClientError(
                        "SEC EDGAR rate limit hit (429). Slow down requests.",
                        guru_code="#EDGAR.00000003.RATELIMIT",
                    )

                elif response.status_code == 503:
                    # SEC often returns 503 for temporary overload
                    if attempt < self._config.max_retries - 1:
                        await asyncio.sleep(self._config.retry_delay_s * (attempt + 1))
                        continue
                    raise EdgarClientError(
                        f"SEC EDGAR service unavailable (503) after {self._config.max_retries} attempts",
                        guru_code="#EDGAR.00000001.FETCHFAIL",
                    )

                else:
                    raise EdgarClientError(
                        f"SEC EDGAR error: HTTP {response.status_code}",
                        guru_code="#EDGAR.00000001.FETCHFAIL",
                    )

            except httpx.RequestError as e:
                last_error = e
                if attempt < self._config.max_retries - 1:
                    await asyncio.sleep(self._config.retry_delay_s * (attempt + 1))
                    continue
                raise EdgarClientError(
                    f"SEC EDGAR request failed after {self._config.max_retries} attempts: {e}",
                    guru_code="#EDGAR.00000001.FETCHFAIL",
                ) from e

        raise EdgarClientError(
            f"SEC EDGAR request failed: {last_error}",
            guru_code="#EDGAR.00000001.FETCHFAIL",
        )


# Module-level convenience functions
async def sync_filing(
    accession_number: str,
    url: str,
    symbol: str,
    filing_type: str,
    cik: str = "",
    filing_date: str = "",
    config: EdgarClientConfig | None = None,
) -> EdgarFiling | None:
    """Convenience function to sync a single filing.

    Args:
        accession_number: SEC accession number.
        url: Direct URL to filing.
        symbol: Stock symbol.
        filing_type: Filing type.
        cik: Central Index Key.
        filing_date: Filing date.
        config: Optional client config.

    Returns:
        EdgarFiling if synced, None if already exists.
    """
    async with EdgarClient(config) as client:
        return await client.sync_filing(
            accession_number, url, symbol, filing_type, cik, filing_date
        )


async def fetch_filing_content(
    url: str,
    filing_type: str,
    symbol: str,
    filing_date: str = "",
    cik: str = "",
    accession_number: str = "",
    config: EdgarClientConfig | None = None,
) -> FilingContent:
    """Convenience function to fetch a single filing without syncing.

    Args:
        url: Direct URL to filing.
        filing_type: Filing type.
        symbol: Stock symbol.
        filing_date: Filing date.
        cik: Central Index Key.
        accession_number: SEC accession number.
        config: Optional client config.

    Returns:
        FilingContent with raw HTML.
    """
    async with EdgarClient(config, sync_enabled=False) as client:
        return await client.fetch_filing(
            url, filing_type, symbol, filing_date, cik, accession_number
        )
