"""FMP (Financial Modeling Prep) API Client for the Gaius Engine.

Provides rate-limited access to FMP endpoints with automatic exchange capture
to Iceberg for full provenance. All responses are persisted before being returned.

Endpoints (Starter tier):
- SEC filings by symbol: Direct queries for specific tickers with date filtering
- SEC filings by form type: Filter by 10-K, 10-Q, 8-K across all companies
- Company profile: Sector, industry, market cap, description
- (Premium only) Institutional holders: 13F filings

Rate Limiting:
- Starter tier: 300 requests/minute, 10,000/day
- Token bucket with configurable rate (default: 30/min conservative)

Guru Meditation Codes:
- #FMP.00000001.NOKEY: FMP_API_KEY not configured
- #FMP.00000002.RATELIMIT: Rate limit exceeded
- #FMP.00000003.HTTPERR: HTTP request failed
- #FMP.00000004.PARSEERR: Response parsing failed
- #FMP.00000005.CAPTUREFAIL: Exchange capture failed (non-fatal)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from gaius.hx.fmp import (
    FMPEndpoint,
    FMPExchangeRecord,
    get_fmp_capture,
)

logger = logging.getLogger(__name__)


def _fmp_rows(data: Any) -> list[dict]:
    """Stable news endpoints return a list; older wrappers used {content|data}."""
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("content", "data", "news"):
            inner = data.get(key)
            if isinstance(inner, list):
                return [r for r in inner if isinstance(r, dict)]
    return []


class FMPClientError(Exception):
    """FMP client error with Guru Meditation code."""

    def __init__(self, message: str, guru_code: str | None = None):
        super().__init__(message)
        self.guru_code = guru_code

    def __str__(self) -> str:
        if self.guru_code:
            return f"{super().__str__()}\n  Guru Meditation: {self.guru_code}"
        return super().__str__()


@dataclass
class FMPClientConfig:
    """Configuration for FMP API client."""

    # API key (required)
    api_key: str = ""

    # Base URL (note: stable API doesn't use /api prefix)
    base_url: str = "https://financialmodelingprep.com"

    # Rate limiting (Starter tier: 300 req/min, 10,000/day)
    requests_per_minute: int = 30  # Conservative: 10% of Starter limit
    daily_limit: int = 10000  # Starter tier limit

    # Request settings
    timeout_s: float = 30.0
    max_retries: int = 3
    retry_delay_s: float = 1.0

    # Exchange capture
    capture_enabled: bool = True

    def __post_init__(self):
        # Try to get API key from environment if not provided
        if not self.api_key:
            self.api_key = os.environ.get("FMP_API_KEY", "")


@dataclass
class RateLimiter:
    """Token bucket rate limiter for API calls."""

    requests_per_minute: int = 10
    daily_limit: int = 250

    # Internal state
    _tokens: float = field(default=0.0, init=False)
    _last_refill: float = field(default=0.0, init=False)
    _daily_count: int = field(default=0, init=False)
    _daily_reset: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc), init=False
    )
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self):
        self._tokens = float(self.requests_per_minute)
        self._last_refill = time.monotonic()
        self._daily_reset = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)

    async def acquire(self) -> bool:
        """Acquire a token for making a request.

        Returns:
            True if token acquired, False if rate limited.

        Raises:
            FMPClientError: If daily limit exceeded.
        """
        async with self._lock:
            now = time.monotonic()
            now_dt = datetime.now(timezone.utc)

            # Reset daily counter if new day
            if now_dt >= self._daily_reset:
                self._daily_count = 0
                self._daily_reset = now_dt.replace(
                    hour=0, minute=0, second=0, microsecond=0
                ) + timedelta(days=1)

            # Check daily limit
            if self._daily_count >= self.daily_limit:
                raise FMPClientError(
                    f"Daily FMP API limit exceeded ({self.daily_limit} requests). "
                    f"Resets at {self._daily_reset.isoformat()}",
                    guru_code="#FMP.00000002.RATELIMIT",
                )

            # Refill tokens based on elapsed time
            elapsed = now - self._last_refill
            refill_amount = elapsed * (self.requests_per_minute / 60.0)
            self._tokens = min(
                float(self.requests_per_minute),
                self._tokens + refill_amount,
            )
            self._last_refill = now

            # Try to consume a token
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                self._daily_count += 1
                return True

            return False

    async def wait_for_token(self, timeout_s: float = 60.0) -> None:
        """Wait until a token is available.

        Args:
            timeout_s: Maximum time to wait.

        Raises:
            FMPClientError: If timeout exceeded or daily limit hit.
        """
        start = time.monotonic()
        while time.monotonic() - start < timeout_s:
            if await self.acquire():
                return
            await asyncio.sleep(0.5)

        raise FMPClientError(
            f"Rate limit wait timeout after {timeout_s}s",
            guru_code="#FMP.00000002.RATELIMIT",
        )

    @property
    def daily_remaining(self) -> int:
        """Remaining requests for today."""
        return max(0, self.daily_limit - self._daily_count)

    @property
    def tokens_available(self) -> float:
        """Current token count (may be stale)."""
        return self._tokens


def _extract_accession_from_url(url: str) -> str:
    """Extract accession number from SEC EDGAR URL.

    URL format: https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/...
    The accession in the URL is without dashes, e.g., 000110465926001107
    We normalize to dashed format: 0001104659-26-001107

    Args:
        url: SEC EDGAR filing URL.

    Returns:
        Normalized accession number with dashes, or empty string if not found.
    """
    import re
    # Match the accession number part of the URL (18 digits without dashes)
    match = re.search(r"/Archives/edgar/data/\d+/(\d{18})/", url)
    if match:
        accession = match.group(1)
        # Format: NNNNNNNNNN-YY-NNNNNN
        return f"{accession[:10]}-{accession[10:12]}-{accession[12:]}"
    return ""


@dataclass
class SECFiling:
    """A parsed SEC filing from FMP."""

    symbol: str
    filing_type: str  # 10-K, 10-Q, 8-K
    filing_date: str  # YYYY-MM-DD
    accepted_date: str  # Full datetime
    cik: str
    accession_number: str
    final_link: str  # URL to full filing

    @classmethod
    def from_fmp_response(cls, data: dict) -> SECFiling:
        """Create from FMP API response (stable API format)."""
        # Stable API uses 'formType' and 'filingDate' (different from legacy)
        final_link = data.get("finalLink", "")

        # Try to get accession_number from response, fall back to URL extraction
        accession = data.get("accessionNumber", "")
        if not accession and final_link:
            accession = _extract_accession_from_url(final_link)

        return cls(
            symbol=data.get("symbol", ""),
            filing_type=data.get("formType", data.get("type", "")),
            filing_date=data.get("filingDate", data.get("fillingDate", "")),
            accepted_date=data.get("acceptedDate", ""),
            cik=data.get("cik", ""),
            accession_number=accession,
            final_link=final_link,
        )


@dataclass
class InstitutionalHolder:
    """A parsed institutional holder from FMP 13F data."""

    holder_name: str
    shares: int
    shares_change: int
    shares_change_pct: float
    value_usd: int
    filing_date: str

    @classmethod
    def from_fmp_response(cls, data: dict) -> InstitutionalHolder:
        """Create from FMP API response."""
        return cls(
            holder_name=data.get("holder", ""),
            shares=data.get("shares", 0),
            shares_change=data.get("change", 0),
            shares_change_pct=data.get("changePercentage", 0.0),
            value_usd=data.get("value", 0),
            filing_date=data.get("dateReported", ""),
        )


@dataclass
class CompanyProfile:
    """A parsed company profile from FMP."""

    symbol: str
    company_name: str
    exchange: str
    cik: str
    sector: str
    industry: str
    market_cap: int
    description: str
    website: str

    @classmethod
    def from_fmp_response(cls, data: dict) -> CompanyProfile:
        """Create from FMP API response (stable API format)."""
        return cls(
            symbol=data.get("symbol", ""),
            company_name=data.get("companyName", ""),
            exchange=data.get("exchange", ""),  # 'exchange' in stable API
            cik=data.get("cik", ""),
            sector=data.get("sector", ""),
            industry=data.get("industry", ""),
            market_cap=data.get("marketCap", 0),  # 'marketCap' in stable API
            description=data.get("description", ""),
            website=data.get("website", ""),
        )


class FMPClient:
    """Async client for FMP API with rate limiting and exchange capture.

    All API responses are automatically captured to Iceberg before being
    returned, ensuring full provenance for financial data.

    Usage:
        async with FMPClient() as client:
            filings = await client.get_sec_filings("AAPL", limit=10)
            holders = await client.get_institutional_holders("AAPL")
            profile = await client.get_company_profile("AAPL")
    """

    def __init__(self, config: FMPClientConfig | None = None):
        self._config = config or FMPClientConfig()
        self._rate_limiter = RateLimiter(
            requests_per_minute=self._config.requests_per_minute,
            daily_limit=self._config.daily_limit,
        )
        self._http_client: httpx.AsyncClient | None = None
        self._capture = get_fmp_capture() if self._config.capture_enabled else None

    async def __aenter__(self) -> FMPClient:
        """Async context manager entry."""
        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._config.timeout_s),
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    def _ensure_api_key(self) -> str:
        """Ensure API key is configured.

        Raises:
            FMPClientError: If API key not configured.
        """
        if not self._config.api_key:
            raise FMPClientError(
                "FMP_API_KEY not configured.\n"
                "  Set environment variable: export FMP_API_KEY=your_key\n"
                "  Or pass to FMPClientConfig(api_key='...')\n"
                "  Get a key at: https://financialmodelingprep.com/developer",
                guru_code="#FMP.00000001.NOKEY",
            )
        return self._config.api_key

    async def _request(
        self,
        endpoint: str,
        path: str,
        symbol: str | None = None,
        params: dict | None = None,
        source_context: dict | None = None,
    ) -> Any:
        """Make a rate-limited request to FMP API with exchange capture.

        Args:
            endpoint: FMP endpoint type (for categorization).
            path: API path (e.g., "/v3/sec_filings/AAPL").
            symbol: Stock symbol if applicable.
            params: Additional query parameters.
            source_context: Context for exchange capture.

        Returns:
            Parsed JSON response.

        Raises:
            FMPClientError: On API errors.
        """
        api_key = self._ensure_api_key()

        if self._http_client is None:
            raise FMPClientError(
                "FMPClient must be used as async context manager",
                guru_code="#FMP.00000003.HTTPERR",
            )

        # Wait for rate limit token
        await self._rate_limiter.wait_for_token()

        # Build URL and params
        url = f"{self._config.base_url}{path}"
        request_params = {"apikey": api_key}
        if params:
            request_params.update(params)

        # Make request with retries
        start_time = time.monotonic()
        last_error: Exception | None = None

        for attempt in range(self._config.max_retries):
            try:
                response = await self._http_client.get(url, params=request_params)
                latency_ms = int((time.monotonic() - start_time) * 1000)

                # Parse response
                if response.status_code == 200:
                    data = response.json()

                    # Capture exchange (fire-and-forget, non-blocking)
                    if self._capture:
                        await self._capture_exchange(
                            endpoint=endpoint,
                            url=url,
                            symbol=symbol,
                            params={k: v for k, v in request_params.items() if k != "apikey"},
                            response_data=data,
                            status_code=response.status_code,
                            latency_ms=latency_ms,
                            source_context=source_context or {},
                        )

                    return data

                elif response.status_code == 429:
                    # Rate limited by FMP
                    raise FMPClientError(
                        f"FMP rate limit hit (HTTP 429). "
                        f"Remaining today: {self._rate_limiter.daily_remaining}",
                        guru_code="#FMP.00000002.RATELIMIT",
                    )

                else:
                    raise FMPClientError(
                        f"FMP API error: HTTP {response.status_code} - {response.text[:200]}",
                        guru_code="#FMP.00000003.HTTPERR",
                    )

            except httpx.RequestError as e:
                last_error = e
                if attempt < self._config.max_retries - 1:
                    await asyncio.sleep(self._config.retry_delay_s * (attempt + 1))
                    continue
                raise FMPClientError(
                    f"FMP request failed after {self._config.max_retries} attempts: {e}",
                    guru_code="#FMP.00000003.HTTPERR",
                ) from e

        # Should not reach here, but just in case
        raise FMPClientError(
            f"FMP request failed: {last_error}",
            guru_code="#FMP.00000003.HTTPERR",
        )

    async def _capture_exchange(
        self,
        endpoint: str,
        url: str,
        symbol: str | None,
        params: dict,
        response_data: Any,
        status_code: int,
        latency_ms: int,
        source_context: dict,
    ) -> None:
        """Capture exchange to Iceberg (fire-and-forget)."""
        # Type narrowing: caller checks self._capture before calling this method
        if self._capture is None:
            return

        try:
            record = FMPExchangeRecord(
                endpoint=endpoint,
                url=url,
                symbol=symbol,
                params=params,
                response_data=response_data,
                status_code=status_code,
                latency_ms=latency_ms,
                source_context=source_context,
            )
            result = await self._capture.capture_fmp(record)
            if not result.success:
                logger.warning(
                    f"FMP exchange capture failed (non-fatal): {result.errors}"
                )
        except Exception as e:
            # Exchange capture failure is non-fatal - log and continue
            logger.warning(
                f"FMP exchange capture error (non-fatal): {e}\n"
                f"  Guru: #FMP.00000005.CAPTUREFAIL"
            )

    # =========================================================================
    # Public API Methods
    # =========================================================================

    async def get_sec_filings(
        self,
        symbol: str,
        filing_type: str | None = None,
        limit: int = 100,
        from_date: str | None = None,
        to_date: str | None = None,
        source_context: dict | None = None,
    ) -> list[SECFiling]:
        """Get SEC filings for a symbol.

        Uses the /stable/sec-filings-search/symbol endpoint which provides
        direct symbol queries with date filtering (requires Starter tier+).

        Args:
            symbol: Stock symbol (e.g., "AAPL").
            filing_type: Filter by type (10-K, 10-Q, 8-K) or None for all.
            limit: Maximum filings to return.
            from_date: Start date (YYYY-MM-DD). Defaults to 90 days ago.
            to_date: End date (YYYY-MM-DD). Defaults to today.
            source_context: Context for exchange capture.

        Returns:
            List of SEC filings, most recent first.
        """
        # Default date range: last 90 days
        if not to_date:
            to_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if not from_date:
            from_date = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")

        params = {
            "symbol": symbol,
            "from": from_date,
            "to": to_date,
            "limit": str(limit),
        }

        data = await self._request(
            endpoint=FMPEndpoint.SEC_FILINGS,
            path="/stable/sec-filings-search/symbol",
            symbol=symbol,
            params=params,
            source_context=source_context,
        )

        if not isinstance(data, list):
            return []

        # Parse all filings
        filings = [SECFiling.from_fmp_response(item) for item in data]

        # Filter by type if specified
        if filing_type:
            filings = [f for f in filings if f.filing_type == filing_type]

        return filings[:limit]

    async def get_institutional_holders(
        self,
        symbol: str,
        source_context: dict | None = None,
    ) -> list[InstitutionalHolder]:
        """Get institutional holders for a symbol (13F data).

        Uses the /stable/ API endpoint. Note: This endpoint requires
        a premium subscription.

        Args:
            symbol: Stock symbol.
            source_context: Context for exchange capture.

        Returns:
            List of institutional holders.

        Raises:
            FMPClientError: If endpoint unavailable (premium required) or other API error.
        """
        params = {"symbol": symbol}
        data = await self._request(
            endpoint=FMPEndpoint.INSTITUTIONAL_HOLDER,
            path="/stable/institutional-ownership/symbol-positions-summary",
            symbol=symbol,
            params=params,
            source_context=source_context,
        )

        if not isinstance(data, list):
            return []

        return [InstitutionalHolder.from_fmp_response(item) for item in data]

    async def get_company_profile(
        self,
        symbol: str,
        source_context: dict | None = None,
    ) -> CompanyProfile | None:
        """Get company profile for a symbol.

        Uses the new /stable/ API endpoints.

        Args:
            symbol: Stock symbol.
            source_context: Context for exchange capture.

        Returns:
            Company profile or None if not found.
        """
        params = {"symbol": symbol}
        data = await self._request(
            endpoint=FMPEndpoint.PROFILE,
            path="/stable/profile",
            symbol=symbol,
            params=params,
            source_context=source_context,
        )

        if isinstance(data, list) and len(data) > 0:
            return CompanyProfile.from_fmp_response(data[0])

        return None

    async def search_ticker(
        self,
        query: str,
        *,
        limit: int = 5,
        source_context: dict | None = None,
    ) -> list[dict[str, str]]:
        """Resolve a company name or fragment to ticker symbols."""
        q = (query or "").strip()
        if not q:
            return []
        data = await self._request(
            endpoint=FMPEndpoint.SEARCH_NAME,
            path="/stable/search-name",
            params={"query": q, "limit": str(limit)},
            source_context=source_context or {"source": "ask_present_resolve"},
        )
        rows = data if isinstance(data, list) else []
        if isinstance(data, dict):
            inner = data.get("results") or data.get("data") or []
            if isinstance(inner, list):
                rows = inner
        out: list[dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").strip().upper()
            if not sym:
                continue
            out.append(
                {
                    "symbol": sym,
                    "name": str(row.get("name") or row.get("companyName") or ""),
                    "exchange": str(
                        row.get("exchangeShortName") or row.get("exchange") or ""
                    ),
                }
            )
        us = {"NYSE", "NASDAQ", "AMEX", "NYSEARCA", "BATS", "CBOE"}

        def _rank(h: dict[str, str]) -> tuple:
            ex = h.get("exchange", "").upper().replace(" ", "")
            name = h.get("name", "").lower()
            levered = "leverage" in name or "3x" in name or "2x" in name
            home = 0 if ex in us and "." not in h["symbol"] else 1
            return (levered, home, len(h["symbol"]), h["symbol"])

        out.sort(key=_rank)
        return out

    async def get_employee_counts(
        self,
        symbol: str,
        *,
        limit: int = 16,
        source_context: dict | None = None,
    ) -> list[dict[str, Any]]:
        """SEC-derived employee counts over filing periods."""
        sym = (symbol or "").strip().upper()
        if not sym:
            return []
        data = await self._request(
            endpoint=FMPEndpoint.EMPLOYEE_COUNT,
            path="/stable/historical-employee-count",
            symbol=sym,
            params={"symbol": sym},
            source_context=source_context or {"source": "fmp_employees"},
        )
        rows = data if isinstance(data, list) else []
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "symbol": str(row.get("symbol") or sym),
                    "period": str(row.get("periodOfReport") or ""),
                    "filed": str(row.get("filingDate") or ""),
                    "employees": row.get("employeeCount"),
                    "form": str(row.get("formType") or ""),
                    "source": str(row.get("source") or ""),
                }
            )
        out.sort(key=lambda r: str(r.get("period") or ""), reverse=True)
        return out[: max(1, min(int(limit), 40))]

    async def get_historical_eod(
        self,
        symbol: str,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
        source_context: dict | None = None,
    ) -> list[dict[str, object]]:
        """Daily OHLC for a symbol. Empty list is honest — caller fail-fasts.

        Uses /stable/historical-price-eod/full.
        """
        sym = (symbol or "").strip().upper()
        if not sym:
            raise FMPClientError(
                "symbol is required for historical EOD.\n  Guru: #FMP.00000004.PARSEERR"
            )
        if not to_date:
            to_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if not from_date:
            from_date = (datetime.now(timezone.utc) - timedelta(days=90)).strftime(
                "%Y-%m-%d"
            )
        data = await self._request(
            endpoint=FMPEndpoint.HISTORICAL_EOD,
            path="/stable/historical-price-eod/full",
            symbol=sym,
            params={"symbol": sym, "from": from_date, "to": to_date},
            source_context=source_context,
        )
        rows: list[dict]
        if isinstance(data, list):
            rows = [r for r in data if isinstance(r, dict)]
        elif isinstance(data, dict):
            hist = data.get("historical", data.get("data", []))
            rows = [r for r in hist if isinstance(r, dict)] if isinstance(hist, list) else []
        else:
            rows = []
        bars: list[dict[str, object]] = []
        for r in rows:
            t = r.get("date") or r.get("t")
            if not t:
                continue
            try:
                bars.append(
                    {
                        "t": str(t)[:10],
                        "o": float(r.get("open", r.get("o"))),
                        "h": float(r.get("high", r.get("h"))),
                        "l": float(r.get("low", r.get("l"))),
                        "c": float(r.get("close", r.get("c"))),
                    }
                )
            except (TypeError, ValueError):
                continue
        bars.sort(key=lambda b: str(b["t"]))
        return bars

    async def get_latest_stock_news(self, *, limit: int = 20) -> list[dict]:
        data = await self._request(
            endpoint=FMPEndpoint.STOCK_NEWS,
            path="/stable/news/stock-latest",
            params={"page": "0", "limit": str(limit)},
        )
        return _fmp_rows(data)

    async def get_latest_general_news(self, *, limit: int = 10) -> list[dict]:
        data = await self._request(
            endpoint=FMPEndpoint.GENERAL_NEWS,
            path="/stable/news/general-latest",
            params={"page": "0", "limit": str(limit)},
        )
        return _fmp_rows(data)

    async def get_fmp_articles(self, *, limit: int = 10) -> list[dict]:
        data = await self._request(
            endpoint=FMPEndpoint.FMP_ARTICLES,
            path="/stable/fmp-articles",
            params={"page": "0", "limit": str(limit)},
        )
        return _fmp_rows(data)

    async def get_latest_8k(self, *, days: int = 7, limit: int = 25) -> list[dict]:
        to_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        from_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%d"
        )
        data = await self._request(
            endpoint=FMPEndpoint.EIGHT_K,
            path="/stable/sec-filings-8k",
            params={"from": from_date, "to": to_date, "limit": str(limit)},
        )
        return data if isinstance(data, list) else []

    async def get_latest_insider(self, *, limit: int = 20) -> list[dict]:
        data = await self._request(
            endpoint=FMPEndpoint.INSIDER,
            path="/stable/insider-trading/latest",
            params={"page": "0", "limit": str(limit)},
        )
        return data if isinstance(data, list) else []

    async def get_latest_mergers(self, *, limit: int = 15) -> list[dict]:
        data = await self._request(
            endpoint=FMPEndpoint.MERGERS,
            path="/stable/mergers-acquisitions-latest",
            params={"page": "0", "limit": str(limit)},
        )
        return data if isinstance(data, list) else []

    async def get_latest_congress(self, *, limit: int = 10) -> list[dict]:
        out: list[dict] = []
        for path in ("/stable/senate-latest", "/stable/house-latest"):
            data = await self._request(
                endpoint=FMPEndpoint.CONGRESS,
                path=path,
                params={"page": "0", "limit": str(limit)},
            )
            if isinstance(data, list):
                chamber = "senate" if "senate" in path else "house"
                for row in data:
                    if isinstance(row, dict):
                        rec = dict(row)
                        rec.setdefault("chamber", chamber)
                        out.append(rec)
        return out

    async def get_earnings_calendar(self, *, days: int = 14) -> list[dict]:
        data = await self._request(
            endpoint=FMPEndpoint.EARNINGS_CALENDAR,
            path="/stable/earnings-calendar",
        )
        if not isinstance(data, list):
            return []
        today = datetime.now(timezone.utc).date()
        end = today + timedelta(days=days)
        kept: list[dict] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            raw = str(row.get("date") or "")[:10]
            try:
                day = datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                continue
            if today <= day <= end:
                kept.append(row)
        return kept

    @property
    def rate_limit_status(self) -> dict:
        """Get current rate limit status."""
        return {
            "daily_remaining": self._rate_limiter.daily_remaining,
            "daily_limit": self._rate_limiter.daily_limit,
            "tokens_available": self._rate_limiter.tokens_available,
            "requests_per_minute": self._rate_limiter.requests_per_minute,
        }


# Module-level convenience function
async def get_fmp_client(config: FMPClientConfig | None = None) -> FMPClient:
    """Create and return an FMP client.

    Note: Caller is responsible for closing the client or using as context manager.
    """
    client = FMPClient(config)
    await client.__aenter__()
    return client
