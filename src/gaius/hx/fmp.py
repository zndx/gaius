"""FMP (Financial Modeling Prep) Exchange Capture.

Captures request-response pairs from FMP API calls to Iceberg storage
for full provenance and potential retraining.

FMP Endpoints Captured:
- /v3/institutional-holder/{symbol} - Who owns a stock
- /v4/institutional-ownership/portfolio-holdings - What an institution owns
- /v4/institutional-ownership/symbol-ownership-percent - Ownership percentage
- /v3/sec_filings/{symbol} - SEC filings (10-K, 10-Q, 8-K)
- /v3/profile/{symbol} - Company profile

CRITICAL: All FMP exchanges MUST be captured for:
1. Audit trail - financial data provenance
2. Replay - rebuild analysis without API costs
3. Training - GLM 4.7 FMP tool use examples
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pyarrow as pa
    from pyiceberg.table import Table

from gaius.hx.exchange import ExchangeCapture, ExchangeWriteResult

logger = logging.getLogger(__name__)


class FMPEndpoint:
    """Known FMP API endpoints for categorization."""

    INSTITUTIONAL_HOLDER = "institutional-holder"
    PORTFOLIO_HOLDINGS = "portfolio-holdings"
    OWNERSHIP_PERCENT = "symbol-ownership-percent"
    SEC_FILINGS = "sec-filings"
    PROFILE = "profile"
    STOCK_NEWS = "stock-news"
    GENERAL_NEWS = "general-news"
    FMP_ARTICLES = "fmp-articles"
    EARNINGS_CALENDAR = "earnings-calendar"
    MERGERS = "mergers-acquisitions"
    INSIDER = "insider-trading"
    CONGRESS = "congress-trading"
    EIGHT_K = "sec-8k"
    HISTORICAL_EOD = "historical-price-eod"
    SEARCH_NAME = "search-name"
    EMPLOYEE_COUNT = "employee-count"
    UNKNOWN = "unknown"

    @classmethod
    def from_url(cls, url: str) -> str:
        """Extract endpoint type from FMP URL."""
        url_lower = url.lower()
        if "institutional-holder" in url_lower:
            return cls.INSTITUTIONAL_HOLDER
        elif "portfolio-holdings" in url_lower:
            return cls.PORTFOLIO_HOLDINGS
        elif "symbol-ownership-percent" in url_lower:
            return cls.OWNERSHIP_PERCENT
        elif "sec-filings-8k" in url_lower or "sec_filings_8k" in url_lower:
            return cls.EIGHT_K
        elif "sec_filings" in url_lower or "sec-filings" in url_lower:
            return cls.SEC_FILINGS
        elif "/profile" in url_lower:
            return cls.PROFILE
        elif "press-release" in url_lower:
            return cls.STOCK_NEWS
        elif "news/stock" in url_lower:
            return cls.STOCK_NEWS
        elif "news/general" in url_lower:
            return cls.GENERAL_NEWS
        elif "fmp-articles" in url_lower:
            return cls.FMP_ARTICLES
        elif "earnings-calendar" in url_lower:
            return cls.EARNINGS_CALENDAR
        elif "merger" in url_lower:
            return cls.MERGERS
        elif "insider" in url_lower:
            return cls.INSIDER
        elif "senate" in url_lower or "house-latest" in url_lower:
            return cls.CONGRESS
        elif "historical-price" in url_lower or "historical-chart" in url_lower:
            return cls.HISTORICAL_EOD
        return cls.UNKNOWN


def _compute_fmp_request_hash(
    endpoint: str, symbol: str | None, params: dict
) -> str:
    """Compute deterministic hash for FMP request deduplication.

    Args:
        endpoint: FMP endpoint type.
        symbol: Stock symbol if applicable.
        params: Request parameters (excluding apikey).

    Returns:
        Hex-encoded SHA-256 hash.
    """
    # Remove apikey from params for hashing
    clean_params = {k: v for k, v in params.items() if k.lower() != "apikey"}
    request_str = json.dumps(
        {"endpoint": endpoint, "symbol": symbol, "params": clean_params},
        sort_keys=True,
        ensure_ascii=True,
    )
    return hashlib.sha256(request_str.encode("utf-8")).hexdigest()


@dataclass
class FMPExchangeRecord:
    """A captured FMP API exchange.

    Attributes:
        endpoint: FMP endpoint type (from FMPEndpoint constants).
        url: Full request URL (with apikey masked).
        symbol: Stock symbol if applicable.
        params: Request parameters.
        response_data: Full JSON response.
        status_code: HTTP status code.
        latency_ms: Request latency in milliseconds.
        source_context: Additional context (profile, domain, etc.).
    """

    endpoint: str
    url: str
    response_data: Any  # JSON-serializable response
    symbol: str | None = None
    params: dict = field(default_factory=dict)
    status_code: int = 200
    latency_ms: int = 0
    source_context: dict = field(default_factory=dict)

    # Auto-generated fields
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    request_hash: str = field(default="")

    def __post_init__(self):
        """Compute request hash if not provided."""
        if not self.request_hash:
            self.request_hash = _compute_fmp_request_hash(
                self.endpoint,
                self.symbol,
                self.params,
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for Iceberg append."""
        # Mask apikey in URL for storage
        masked_url = self.url
        if "apikey=" in masked_url.lower():
            import re
            masked_url = re.sub(r"apikey=[^&]+", "apikey=REDACTED", masked_url, flags=re.IGNORECASE)

        return {
            "id": self.id,
            "provider": "fmp",
            "endpoint": self.endpoint,
            "request_hash": self.request_hash,
            "url": masked_url,
            "symbol": self.symbol or "",
            "params": json.dumps(self.params),
            "response_data": json.dumps(self.response_data),
            "status_code": self.status_code,
            "latency_ms": self.latency_ms,
            "created_at": self.created_at,
            "source_context": json.dumps(self.source_context),
        }


class FMPExchangeCapture(ExchangeCapture):
    """Specialized capture for FMP API exchanges.

    Extends ExchangeCapture with FMP-specific:
    - Request deduplication (same endpoint+symbol+params)
    - Endpoint categorization
    - Cost tracking
    - Symbol-based partitioning

    Usage:
        capture = FMPExchangeCapture()

        # Before making FMP API call
        record = FMPExchangeRecord(
            endpoint=FMPEndpoint.SEC_FILINGS,
            url=url,
            symbol="CHTR",
            response_data=response.json(),
            latency_ms=150,
        )
        await capture.capture_fmp(record)
    """

    def __init__(
        self,
        enabled: bool | None = None,
        namespace: str = "raw",
        table_name: str = "fmp_exchange",
        buffer_size: int = 1,
    ):
        """Initialize FMP exchange capture.

        Args:
            enabled: Whether capture is enabled. If None, reads from
                     GAIUS_HX_CAPTURE_FMP env var (default: True).
            namespace: Iceberg namespace.
            table_name: Table name within namespace.
            buffer_size: Number of records to buffer before writing.
        """
        if enabled is None:
            env_val = os.environ.get("GAIUS_HX_CAPTURE_FMP", "true")
            enabled = env_val.lower() in ("1", "true", "yes")

        # Call parent with FMP-specific settings
        super().__init__(
            enabled=enabled,
            namespace=namespace,
            table_name=table_name,
            buffer_size=buffer_size,
        )
        self._fmp_buffer: list[FMPExchangeRecord] = []

    def _get_table(self) -> "Table":
        """Get or create the FMP exchange table."""
        if self._table is None:
            from gaius.hx.fmp_tables import get_fmp_exchange_table

            self._table = get_fmp_exchange_table(
                self._get_catalog(),
                namespace=self._namespace,
                table_name=self._table_name,
            )
        return self._table

    async def capture_fmp(self, record: FMPExchangeRecord) -> ExchangeWriteResult:
        """Capture an FMP exchange record.

        Args:
            record: The FMP exchange record to capture.

        Returns:
            ExchangeWriteResult with status.
        """
        if not self._enabled:
            return ExchangeWriteResult(success=True, items_written=0)

        # Check health on first capture
        if self._healthy is None:
            await self.health_check()

        if self._healthy is False:
            error_msg = (
                f"CRITICAL: FMP exchange capture unavailable. "
                f"Endpoint={record.endpoint}, symbol={record.symbol}"
            )
            logger.error(error_msg)
            return ExchangeWriteResult(
                success=False,
                items_written=0,
                errors=[error_msg],
            )

        try:
            async with self._lock:
                self._fmp_buffer.append(record)

                if len(self._fmp_buffer) >= self._buffer_size:
                    return await self._flush_fmp_buffer()

            return ExchangeWriteResult(success=True, items_written=0)

        except Exception as e:
            error_msg = f"CRITICAL: FMP exchange capture failed: {e}"
            logger.error(error_msg)
            return ExchangeWriteResult(
                success=False,
                items_written=0,
                errors=[error_msg],
            )

    async def _flush_fmp_buffer(self) -> ExchangeWriteResult:
        """Flush buffered FMP records to Iceberg."""
        if not self._fmp_buffer:
            return ExchangeWriteResult(success=True, items_written=0)

        records_to_write = self._fmp_buffer.copy()
        self._fmp_buffer.clear()

        try:
            import asyncio
            import pyarrow as pa

            records = [r.to_dict() for r in records_to_write]
            arrow_table = self._fmp_records_to_arrow(records)

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._get_table().append(arrow_table),
            )

            snapshot = self._get_table().current_snapshot()
            snapshot_id = snapshot.snapshot_id if snapshot else None

            symbols = set(r["symbol"] for r in records if r["symbol"])
            logger.info(
                f"FMP exchange capture: wrote {len(records_to_write)} records "
                f"(snapshot: {snapshot_id}, symbols: {symbols})"
            )

            return ExchangeWriteResult(
                success=True,
                items_written=len(records_to_write),
                snapshot_id=snapshot_id,
            )

        except Exception as e:
            self._healthy = False
            error_msg = f"CRITICAL: FMP exchange write failed: {e}"
            logger.error(error_msg)
            return ExchangeWriteResult(
                success=False,
                items_written=0,
                errors=[error_msg],
            )

    async def flush(self) -> ExchangeWriteResult:
        """Force flush any buffered FMP records."""
        async with self._lock:
            return await self._flush_fmp_buffer()

    def _fmp_records_to_arrow(self, records: list[dict]) -> "pa.Table":
        """Convert FMP records to PyArrow table."""
        import pyarrow as pa

        schema = pa.schema([
            pa.field("id", pa.string(), nullable=False),
            pa.field("provider", pa.string(), nullable=False),
            pa.field("endpoint", pa.string(), nullable=False),
            pa.field("request_hash", pa.string(), nullable=False),
            pa.field("url", pa.string(), nullable=False),
            pa.field("symbol", pa.string(), nullable=True),
            pa.field("params", pa.string(), nullable=True),
            pa.field("response_data", pa.string(), nullable=False),
            pa.field("status_code", pa.int32(), nullable=False),
            pa.field("latency_ms", pa.int64(), nullable=True),
            pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("source_context", pa.string(), nullable=True),
        ])

        # Ensure timestamps are timezone-aware
        for record in records:
            if record.get("created_at"):
                dt = record["created_at"]
                if dt.tzinfo is None:
                    record["created_at"] = dt.replace(tzinfo=timezone.utc)

        return pa.Table.from_pylist(records, schema=schema)


# Module-level singleton
_fmp_capture: FMPExchangeCapture | None = None


def get_fmp_capture() -> FMPExchangeCapture:
    """Get or create the FMP exchange capture singleton."""
    global _fmp_capture
    if _fmp_capture is None:
        _fmp_capture = FMPExchangeCapture()
    return _fmp_capture


def reset_fmp_capture() -> None:
    """Reset the FMP capture singleton (for testing)."""
    global _fmp_capture
    _fmp_capture = None
