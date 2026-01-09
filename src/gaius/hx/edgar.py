"""SEC EDGAR Filing Sync.

Sync-oriented capture of SEC filings to Iceberg storage with:
1. Deduplication by accession_number (SEC's unique filing ID)
2. Content hash verification for integrity
3. Idempotent sync operations
4. Separate extraction phase tracking

Architecture:
- EdgarFilingSync: Check-then-fetch with deduplication
- Metaflow ProspectsFlow: Batch sync + docling extraction
- ProspectsService: Query extracted content for LLM analysis

Sync Semantics:
- Filing exists check: O(1) via accession_number lookup
- Fetch only net-new filings (not in HX)
- Extract only unprocessed filings (no extracted_text)
- Re-running produces no duplicates
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pyarrow as pa
    from pyiceberg.table import Table

from gaius.hx.exchange import ExchangeCapture, ExchangeWriteResult

logger = logging.getLogger(__name__)


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of filing content.

    Used for integrity verification and change detection.

    Args:
        content: Raw HTML content.

    Returns:
        Hex-encoded SHA-256 hash.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _safe_value(val: Any) -> Any:
    """Safely convert pandas NaT/NA values to None for PyArrow.

    Pandas reads NULL timestamps as NaT (Not a Time), which can't be
    directly converted to PyArrow timestamps. This helper converts
    NaT values to None so PyArrow handles them as nulls.

    Args:
        val: Value from pandas DataFrame.

    Returns:
        None if value is NaT/NA, otherwise the original value.
    """
    import pandas as pd

    if pd.isna(val):
        return None
    return val


def normalize_accession_number(accession: str) -> str:
    """Normalize accession number to standard format.

    SEC accession numbers can appear as:
    - 0001104659-26-001107 (with dashes)
    - 0001104659260011079 (without dashes)

    We normalize to the dashed format for consistency.

    Args:
        accession: Raw accession number.

    Returns:
        Normalized accession number with dashes.
    """
    # Remove any existing dashes
    clean = accession.replace("-", "")
    if len(clean) == 18:
        # Format: NNNNNNNNNN-YY-NNNNNN
        return f"{clean[:10]}-{clean[10:12]}-{clean[12:]}"
    return accession  # Return as-is if format unknown


@dataclass
class EdgarFiling:
    """A SEC EDGAR filing record for sync operations.

    The accession_number is the unique identifier - SEC guarantees
    uniqueness across all filings.

    Attributes:
        accession_number: SEC's unique filing identifier (primary key).
        symbol: Stock symbol.
        cik: Central Index Key.
        filing_type: Filing type (10-K, 10-Q, 8-K, etc.).
        filing_date: Date filed with SEC.
        url: Full SEC EDGAR URL.
        raw_html: Full HTML content.
        content_hash: SHA-256 of raw_html for integrity verification.
        title: Filing title extracted from HTML.
        fetched_at: When content was fetched from SEC.
    """

    accession_number: str  # Primary key
    symbol: str
    cik: str
    filing_type: str
    filing_date: str
    url: str

    # Content (populated on fetch)
    raw_html: str = ""
    content_hash: str = ""
    raw_html_length: int = 0
    title: str = ""

    # Fetch metadata
    fetched_at: datetime | None = None
    fetch_latency_ms: int = 0

    # Extraction metadata (populated by Metaflow)
    extracted_text: str | None = None
    extracted_at: datetime | None = None
    extraction_model: str | None = None

    # Analysis metadata (populated by Cerebras GLM 4.7)
    analyzed_at: datetime | None = None
    analysis_model: str | None = None
    analysis_json: str | None = None  # Serialized FilingAnalysis

    # Source tracking
    source_context: dict = field(default_factory=dict)

    def __post_init__(self):
        """Normalize accession number and compute content hash."""
        self.accession_number = normalize_accession_number(self.accession_number)
        if self.raw_html and not self.content_hash:
            self.content_hash = compute_content_hash(self.raw_html)
        if self.raw_html and not self.raw_html_length:
            self.raw_html_length = len(self.raw_html)

    @classmethod
    def from_fmp_filing(cls, fmp_data: dict, symbol: str) -> "EdgarFiling":
        """Create from FMP API response.

        Args:
            fmp_data: Filing dict from FMP API.
            symbol: Stock symbol.

        Returns:
            EdgarFiling with metadata (no content yet).
        """
        return cls(
            accession_number=fmp_data.get("accessionNumber", ""),
            symbol=symbol,
            cik=fmp_data.get("cik", ""),
            filing_type=fmp_data.get("type", fmp_data.get("formType", "")),
            filing_date=fmp_data.get("fillingDate", fmp_data.get("filingDate", "")),
            url=fmp_data.get("finalLink", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for Iceberg storage."""
        return {
            "accession_number": self.accession_number,
            "symbol": self.symbol,
            "cik": self.cik,
            "filing_type": self.filing_type,
            "filing_date": self.filing_date,
            "url": self.url,
            "raw_html": self.raw_html,
            "content_hash": self.content_hash,
            "raw_html_length": self.raw_html_length,
            "title": self.title,
            "fetched_at": self.fetched_at,
            "fetch_latency_ms": self.fetch_latency_ms,
            "extracted_text": self.extracted_text,
            "extracted_at": self.extracted_at,
            "extraction_model": self.extraction_model,
            "source_context": self.source_context,
            "analyzed_at": self.analyzed_at,
            "analysis_model": self.analysis_model,
            "analysis_json": self.analysis_json,
        }


@dataclass
class SyncResult:
    """Result of a sync operation."""

    success: bool
    filings_checked: int = 0
    filings_new: int = 0
    filings_skipped: int = 0  # Already in HX
    filings_fetched: int = 0
    filings_extracted: int = 0
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        status = "OK" if self.success else "FAILED"
        return (
            f"SyncResult({status}): "
            f"checked={self.filings_checked}, new={self.filings_new}, "
            f"skipped={self.filings_skipped}, fetched={self.filings_fetched}, "
            f"extracted={self.filings_extracted}"
        )


class EdgarFilingSync(ExchangeCapture):
    """Sync-oriented SEC EDGAR filing storage.

    Provides idempotent sync operations:
    - exists(accession_number) - check if filing already stored
    - get_unextracted() - filings needing docling extraction
    - sync_filing(filing) - store if not exists
    - update_extraction(accession, text, model) - update extraction fields

    Usage:
        sync = EdgarFilingSync()

        # Check before fetching
        if not await sync.exists("0001104659-26-001107"):
            # Fetch from SEC and store
            filing = await fetch_from_sec(...)
            await sync.sync_filing(filing)

        # Get filings needing extraction
        unextracted = await sync.get_unextracted(limit=100)
        for filing in unextracted:
            text = await run_docling(filing.raw_html)
            await sync.update_extraction(filing.accession_number, text, "docling-v2")
    """

    def __init__(
        self,
        enabled: bool | None = None,
        namespace: str = "raw",
        table_name: str = "edgar_filings",
    ):
        """Initialize EDGAR filing sync.

        Args:
            enabled: Whether sync is enabled.
            namespace: Iceberg namespace.
            table_name: Table name within namespace.
        """
        if enabled is None:
            env_val = os.environ.get("GAIUS_HX_EDGAR_SYNC", "true")
            enabled = env_val.lower() in ("1", "true", "yes")

        super().__init__(
            enabled=enabled,
            namespace=namespace,
            table_name=table_name,
            buffer_size=1,  # Immediate writes for sync semantics
        )
        self._accession_cache: set[str] | None = None
        self._cache_loaded_at: datetime | None = None
        self._cache_ttl_seconds = 300  # 5 minute cache

    def _get_table(self) -> "Table":
        """Get or create the EDGAR filings table."""
        if self._table is None:
            from gaius.hx.edgar_tables import get_edgar_filings_table

            self._table = get_edgar_filings_table(
                self._get_catalog(),
                namespace=self._namespace,
                table_name=self._table_name,
            )
        else:
            # Refresh to ensure we have latest schema after any evolution
            self._table.refresh()
        return self._table

    async def _load_accession_cache(self, force: bool = False) -> None:
        """Load set of existing accession numbers for fast lookup.

        Args:
            force: Force reload even if cache is fresh.
        """
        now = datetime.now(timezone.utc)

        # Check if cache is still valid
        if not force and self._accession_cache is not None and self._cache_loaded_at:
            age = (now - self._cache_loaded_at).total_seconds()
            if age < self._cache_ttl_seconds:
                return

        try:
            loop = asyncio.get_event_loop()

            def load_accessions():
                table = self._get_table()
                # Only scan accession_number column for efficiency
                scan = table.scan(selected_fields=("accession_number",))
                df = scan.to_pandas()
                return set(df["accession_number"].tolist())

            self._accession_cache = await loop.run_in_executor(None, load_accessions)
            self._cache_loaded_at = now
            logger.debug(f"Loaded {len(self._accession_cache)} accession numbers to cache")

        except Exception as e:
            logger.warning(f"Failed to load accession cache: {e}")
            self._accession_cache = set()
            self._cache_loaded_at = now

    async def exists(self, accession_number: str) -> bool:
        """Check if a filing exists in HX by accession number.

        Args:
            accession_number: SEC accession number.

        Returns:
            True if filing already stored.
        """
        if not self._enabled:
            return False

        accession = normalize_accession_number(accession_number)
        await self._load_accession_cache()
        return accession in (self._accession_cache or set())

    async def get_existing_accessions(self, accessions: list[str]) -> set[str]:
        """Check which accession numbers already exist.

        Args:
            accessions: List of accession numbers to check.

        Returns:
            Set of accession numbers that exist in HX.
        """
        if not self._enabled:
            return set()

        await self._load_accession_cache()
        normalized = {normalize_accession_number(a) for a in accessions}
        return normalized & (self._accession_cache or set())

    async def get_unextracted(self, limit: int = 100) -> list[EdgarFiling]:
        """Get filings that need extraction (have raw_html but no extracted_text).

        Args:
            limit: Maximum filings to return.

        Returns:
            List of EdgarFiling objects needing extraction.
        """
        if not self._enabled:
            return []

        try:
            loop = asyncio.get_event_loop()

            def query_unextracted():
                from pyiceberg.expressions import And, IsNull, NotEqualTo

                table = self._get_table()
                # Filter for filings with content but no extraction
                # Also exclude filings with empty accession_number (bad data)
                scan = table.scan(
                    row_filter=And(
                        IsNull("extracted_text"),
                        NotEqualTo("accession_number", ""),
                    ),
                    selected_fields=(
                        "accession_number", "symbol", "cik", "filing_type",
                        "filing_date", "url", "raw_html", "content_hash",
                        "raw_html_length", "title", "fetched_at",
                    ),
                    limit=limit,
                )
                df = scan.to_pandas()
                return df.to_dict("records")

            records = await loop.run_in_executor(None, query_unextracted)

            # Double-check accession_number is valid (belt and suspenders)
            return [
                EdgarFiling(
                    accession_number=r["accession_number"],
                    symbol=r["symbol"],
                    cik=r["cik"],
                    filing_type=r["filing_type"],
                    filing_date=r["filing_date"],
                    url=r["url"],
                    raw_html=r["raw_html"],
                    content_hash=r["content_hash"],
                    raw_html_length=r["raw_html_length"],
                    title=r.get("title", ""),
                    fetched_at=r.get("fetched_at"),
                )
                for r in records
                if r["accession_number"] and r["accession_number"].strip()
            ]

        except Exception as e:
            logger.error(f"Failed to query unextracted filings: {e}")
            return []

    async def get_filings_by_symbol(
        self,
        symbol: str,
        limit: int = 20,
    ) -> list[EdgarFiling]:
        """Get filings for a specific symbol.

        Used to retrieve extracted filings for analysis.

        Args:
            symbol: Stock symbol.
            limit: Maximum filings to return.

        Returns:
            List of EdgarFiling objects.
        """
        if not self._enabled:
            return []

        try:
            loop = asyncio.get_event_loop()

            def query_filings():
                from pyiceberg.expressions import EqualTo

                table = self._get_table()
                scan = table.scan(
                    row_filter=EqualTo("symbol", symbol.upper()),
                    limit=limit,
                )
                df = scan.to_pandas()
                return df.to_dict("records")

            records = await loop.run_in_executor(None, query_filings)

            return [
                EdgarFiling(
                    accession_number=r["accession_number"],
                    symbol=r["symbol"],
                    cik=r["cik"],
                    filing_type=r["filing_type"],
                    filing_date=r["filing_date"],
                    url=r["url"],
                    raw_html=r.get("raw_html", ""),
                    content_hash=r.get("content_hash", ""),
                    raw_html_length=r.get("raw_html_length", 0),
                    title=r.get("title", ""),
                    fetched_at=r.get("fetched_at"),
                    extracted_text=r.get("extracted_text"),
                    extracted_at=r.get("extracted_at"),
                    extraction_model=r.get("extraction_model"),
                    analyzed_at=r.get("analyzed_at"),
                    analysis_model=r.get("analysis_model"),
                    analysis_json=r.get("analysis_json"),
                )
                for r in records
                if r["accession_number"]
            ]

        except Exception as e:
            logger.error(f"Failed to query filings for {symbol}: {e}")
            return []

    async def get_unanalyzed(
        self,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[EdgarFiling]:
        """Get filings that have extracted text but no analysis.

        Used to find filings ready for Cerebras analysis (have text, not analyzed).

        Args:
            symbol: Optional symbol filter.
            limit: Maximum filings to return.

        Returns:
            List of EdgarFiling objects needing analysis.
        """
        if not self._enabled:
            return []

        try:
            loop = asyncio.get_event_loop()

            def query_unanalyzed():
                from pyiceberg.expressions import And, EqualTo, IsNull, Not, NotEqualTo

                table = self._get_table()

                # Build filter: has extracted_text, no analyzed_at
                # Note: PyIceberg doesn't have IsNotNull, use Not(IsNull(...))
                conditions = [
                    Not(IsNull("extracted_text")),
                    NotEqualTo("extracted_text", ""),
                    IsNull("analyzed_at"),
                    NotEqualTo("accession_number", ""),
                ]

                if symbol:
                    conditions.append(EqualTo("symbol", symbol.upper()))

                # Combine conditions
                if len(conditions) == 1:
                    row_filter = conditions[0]
                else:
                    row_filter = And(*conditions)

                scan = table.scan(
                    row_filter=row_filter,
                    selected_fields=(
                        "accession_number", "symbol", "cik", "filing_type",
                        "filing_date", "url", "extracted_text", "title",
                    ),
                    limit=limit,
                )
                df = scan.to_pandas()
                return df.to_dict("records")

            records = await loop.run_in_executor(None, query_unanalyzed)

            return [
                EdgarFiling(
                    accession_number=r["accession_number"],
                    symbol=r["symbol"],
                    cik=r["cik"],
                    filing_type=r["filing_type"],
                    filing_date=r["filing_date"],
                    url=r["url"],
                    extracted_text=r.get("extracted_text"),
                    title=r.get("title", ""),
                )
                for r in records
                if r["accession_number"]
            ]

        except Exception as e:
            logger.error(f"Failed to query unanalyzed filings: {e}")
            return []

    async def update_analysis(
        self,
        accession_number: str,
        analysis_json: str,
        analysis_model: str,
        analysis_reasoning: str = "",
    ) -> bool:
        """Update analysis fields for a filing using Iceberg upsert.

        Marks the filing as analyzed to prevent reprocessing.

        Args:
            accession_number: Filing to update.
            analysis_json: Serialized FilingAnalysis JSON.
            analysis_model: Model used (e.g., zai-glm-4.7).
            analysis_reasoning: GLM chain-of-thought reasoning for distillation.

        Returns:
            True if update succeeded.
        """
        if not self._enabled:
            return False

        accession = normalize_accession_number(accession_number)

        try:
            loop = asyncio.get_event_loop()

            def do_upsert():
                import pyarrow as pa
                from pyiceberg.expressions import EqualTo

                table = self._get_table()

                # Read existing row
                scan = table.scan(
                    row_filter=EqualTo("accession_number", accession),
                )
                df = scan.to_pandas()

                if df.empty:
                    logger.warning(f"Filing {accession} not found for analysis update")
                    return False

                row = df.iloc[0].to_dict()

                # Build updated row with analysis fields
                # Use _safe_value to convert pandas NaT to None for PyArrow
                # Order must match Iceberg table schema (source_context before analysis fields)
                now = datetime.now(timezone.utc)
                updated_data = {
                    "accession_number": [row["accession_number"]],
                    "symbol": [row["symbol"]],
                    "cik": [row["cik"]],
                    "filing_type": [row["filing_type"]],
                    "filing_date": [row["filing_date"]],
                    "url": [row["url"]],
                    "raw_html": [row["raw_html"]],
                    "content_hash": [row["content_hash"]],
                    "raw_html_length": [row["raw_html_length"]],
                    "title": [row.get("title", "") or ""],
                    "fetched_at": [_safe_value(row.get("fetched_at"))],
                    "fetch_latency_ms": [_safe_value(row.get("fetch_latency_ms"))],
                    "extracted_text": [row.get("extracted_text")],
                    "extracted_at": [_safe_value(row.get("extracted_at"))],
                    "extraction_model": [row.get("extraction_model")],
                    "source_context": [row.get("source_context", "{}")],
                    # Analysis fields (must be last per Iceberg schema)
                    "analyzed_at": [now],
                    "analysis_model": [analysis_model],
                    "analysis_json": [analysis_json],
                    # Chain-of-thought for distillation
                    "analysis_reasoning": [analysis_reasoning or None],
                }

                # Create PyArrow table with proper schema (order matches Iceberg table)
                schema = pa.schema([
                    pa.field("accession_number", pa.string(), nullable=False),
                    pa.field("symbol", pa.string(), nullable=False),
                    pa.field("cik", pa.string(), nullable=False),
                    pa.field("filing_type", pa.string(), nullable=False),
                    pa.field("filing_date", pa.string(), nullable=False),
                    pa.field("url", pa.string(), nullable=False),
                    pa.field("raw_html", pa.string(), nullable=False),
                    pa.field("content_hash", pa.string(), nullable=False),
                    pa.field("raw_html_length", pa.int64(), nullable=False),
                    pa.field("title", pa.string(), nullable=True),
                    pa.field("fetched_at", pa.timestamp("us", tz="UTC"), nullable=True),
                    pa.field("fetch_latency_ms", pa.int64(), nullable=True),
                    pa.field("extracted_text", pa.string(), nullable=True),
                    pa.field("extracted_at", pa.timestamp("us", tz="UTC"), nullable=True),
                    pa.field("extraction_model", pa.string(), nullable=True),
                    pa.field("source_context", pa.string(), nullable=True),
                    pa.field("analyzed_at", pa.timestamp("us", tz="UTC"), nullable=True),
                    pa.field("analysis_model", pa.string(), nullable=True),
                    pa.field("analysis_json", pa.string(), nullable=True),
                    pa.field("analysis_reasoning", pa.string(), nullable=True),
                ])

                arrow_table = pa.table(updated_data).cast(schema)

                # Upsert with accession_number as join key
                table.upsert(
                    arrow_table,
                    join_cols=["accession_number"],
                    when_matched_update_all=True,
                    when_not_matched_insert_all=False,
                )

                logger.info(
                    f"Updated analysis for {accession}: model={analysis_model}"
                )
                return True

            success = await loop.run_in_executor(None, do_upsert)
            return success

        except Exception as e:
            logger.error(f"Failed to update analysis for {accession}: {e}")
            return False

    async def delete_invalid_filings(self) -> int:
        """Delete filings with empty accession numbers (data quality cleanup).

        Returns:
            Number of filings deleted.
        """
        if not self._enabled:
            return 0

        try:
            loop = asyncio.get_event_loop()

            def do_delete():
                from pyiceberg.expressions import EqualTo

                table = self._get_table()
                # Delete rows with empty accession_number
                table.delete(delete_filter=EqualTo("accession_number", ""))
                return 1  # Iceberg delete doesn't return count easily

            await loop.run_in_executor(None, do_delete)
            logger.info("Deleted filings with empty accession_number")

            # Invalidate cache
            self._accession_cache = None
            self._cache_loaded_at = None

            return 1

        except Exception as e:
            logger.error(f"Failed to delete invalid filings: {e}")
            return 0

    def _emit_quality_rejection_event(
        self,
        reason: str,
        filing_symbol: str,
        filing_url: str,
        guru_code: str,
    ) -> None:
        """Emit OpenTelemetry event for data quality rejection.

        Args:
            reason: Human-readable rejection reason.
            filing_symbol: Stock symbol.
            filing_url: Filing URL.
            guru_code: Guru Meditation code.
        """
        try:
            from opentelemetry import trace

            span = trace.get_current_span()
            if span.is_recording():
                span.add_event(
                    "edgar.filing.quality_rejected",
                    {
                        "reason": reason,
                        "symbol": filing_symbol,
                        "url": filing_url,
                        "guru_code": guru_code,
                    },
                )
        except ImportError:
            pass  # OTel not available
        except Exception as e:
            logger.debug(f"Failed to emit OTel event: {e}")

    async def sync_filing(self, filing: EdgarFiling) -> ExchangeWriteResult:
        """Sync a filing to HX (idempotent - skips if exists).

        Args:
            filing: The filing to sync.

        Returns:
            ExchangeWriteResult with sync status.
        """
        if not self._enabled:
            return ExchangeWriteResult(success=True, items_written=0)

        # Validate accession number (required for deduplication)
        if not filing.accession_number or not filing.accession_number.strip():
            guru_code = "#EDGAR.00000006.NO_ACCESSION"
            error_msg = (
                f"Cannot sync filing without accession_number. "
                f"Symbol={filing.symbol}, URL={filing.url}\n"
                f"  Guru Meditation: {guru_code}\n"
                "  Ensure FMP response includes accession or extract from URL."
            )
            logger.error(error_msg)

            # Emit OTel event for quality rejection
            self._emit_quality_rejection_event(
                reason="missing_accession_number",
                filing_symbol=filing.symbol,
                filing_url=filing.url,
                guru_code=guru_code,
            )

            return ExchangeWriteResult(
                success=False,
                items_written=0,
                errors=[error_msg],
            )

        # Check if already exists
        if await self.exists(filing.accession_number):
            logger.debug(f"Filing {filing.accession_number} already exists, skipping")
            return ExchangeWriteResult(success=True, items_written=0)

        # Check health on first write
        if self._healthy is None:
            await self.health_check()

        if self._healthy is False:
            error_msg = (
                f"CRITICAL: EDGAR filing sync unavailable. "
                f"Accession={filing.accession_number}"
            )
            logger.error(error_msg)
            return ExchangeWriteResult(
                success=False,
                items_written=0,
                errors=[error_msg],
            )

        try:
            import pyarrow as pa

            arrow_table = self._filing_to_arrow(filing)

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._get_table().append(arrow_table),
            )

            # Update cache
            if self._accession_cache is not None:
                self._accession_cache.add(filing.accession_number)

            logger.info(f"Synced filing {filing.accession_number} ({filing.symbol} {filing.filing_type})")
            return ExchangeWriteResult(success=True, items_written=1)

        except Exception as e:
            error_msg = f"CRITICAL: Filing sync failed for {filing.accession_number}: {e}"
            logger.error(error_msg)
            return ExchangeWriteResult(
                success=False,
                items_written=0,
                errors=[error_msg],
            )

    async def sync_filings(self, filings: list[EdgarFiling]) -> SyncResult:
        """Sync multiple filings (batch operation).

        Args:
            filings: List of filings to sync.

        Returns:
            SyncResult with counts.
        """
        result = SyncResult(success=True, filings_checked=len(filings))

        if not self._enabled or not filings:
            return result

        # Check which already exist
        accessions = [f.accession_number for f in filings]
        existing = await self.get_existing_accessions(accessions)
        result.filings_skipped = len(existing)

        # Filter to net-new filings
        new_filings = [f for f in filings if f.accession_number not in existing]
        result.filings_new = len(new_filings)

        if not new_filings:
            logger.info(f"All {len(filings)} filings already exist, nothing to sync")
            return result

        # Sync new filings
        for filing in new_filings:
            write_result = await self.sync_filing(filing)
            if write_result.success and write_result.items_written > 0:
                result.filings_fetched += 1
            elif not write_result.success:
                result.errors.extend(write_result.errors)

        result.success = len(result.errors) == 0
        logger.info(str(result))
        return result

    async def update_extraction(
        self,
        accession_number: str,
        extracted_text: str,
        extraction_model: str,
    ) -> bool:
        """Update extraction fields for a filing using Iceberg upsert.

        Uses PyIceberg's upsert with accession_number as the join key.
        Only updates extraction fields, preserving all other data.

        Args:
            accession_number: Filing to update.
            extracted_text: Extracted text content.
            extraction_model: Model/version used for extraction.

        Returns:
            True if update succeeded.
        """
        if not self._enabled:
            return False

        accession = normalize_accession_number(accession_number)

        try:
            loop = asyncio.get_event_loop()

            def do_upsert():
                import pyarrow as pa
                from pyiceberg.expressions import EqualTo

                table = self._get_table()

                # First, read the existing row to get all fields
                # Include analysis fields so we can preserve them during upsert
                scan = table.scan(
                    row_filter=EqualTo("accession_number", accession),
                    selected_fields=(
                        "accession_number", "symbol", "cik", "filing_type",
                        "filing_date", "url", "raw_html", "content_hash",
                        "raw_html_length", "title", "fetched_at", "fetch_latency_ms",
                        "source_context", "analyzed_at", "analysis_model", "analysis_json",
                        "analysis_reasoning",
                    ),
                )
                df = scan.to_pandas()

                if df.empty:
                    logger.warning(f"Filing {accession} not found for extraction update")
                    return False

                row = df.iloc[0].to_dict()

                # Build updated row with extraction fields
                # Use _safe_value to convert pandas NaT to None for PyArrow
                now = datetime.now(timezone.utc)
                updated_data = {
                    "accession_number": [row["accession_number"]],
                    "symbol": [row["symbol"]],
                    "cik": [row["cik"]],
                    "filing_type": [row["filing_type"]],
                    "filing_date": [row["filing_date"]],
                    "url": [row["url"]],
                    "raw_html": [row["raw_html"]],
                    "content_hash": [row["content_hash"]],
                    "raw_html_length": [row["raw_html_length"]],
                    "title": [row.get("title", "") or ""],
                    "fetched_at": [_safe_value(row.get("fetched_at"))],
                    "fetch_latency_ms": [_safe_value(row.get("fetch_latency_ms"))],
                    # Updated extraction fields
                    "extracted_text": [extracted_text],
                    "extracted_at": [now],
                    "extraction_model": [extraction_model],
                    "source_context": [row.get("source_context", "{}")],
                    # Preserve existing analysis fields (must match full table schema)
                    "analyzed_at": [_safe_value(row.get("analyzed_at"))],
                    "analysis_model": [row.get("analysis_model")],
                    "analysis_json": [row.get("analysis_json")],
                    "analysis_reasoning": [row.get("analysis_reasoning")],
                }

                # Create PyArrow table with full schema (must match Iceberg table)
                schema = pa.schema([
                    pa.field("accession_number", pa.string(), nullable=False),
                    pa.field("symbol", pa.string(), nullable=False),
                    pa.field("cik", pa.string(), nullable=False),
                    pa.field("filing_type", pa.string(), nullable=False),
                    pa.field("filing_date", pa.string(), nullable=False),
                    pa.field("url", pa.string(), nullable=False),
                    pa.field("raw_html", pa.string(), nullable=False),
                    pa.field("content_hash", pa.string(), nullable=False),
                    pa.field("raw_html_length", pa.int64(), nullable=False),
                    pa.field("title", pa.string(), nullable=True),
                    pa.field("fetched_at", pa.timestamp("us", tz="UTC"), nullable=True),
                    pa.field("fetch_latency_ms", pa.int64(), nullable=True),
                    pa.field("extracted_text", pa.string(), nullable=True),
                    pa.field("extracted_at", pa.timestamp("us", tz="UTC"), nullable=True),
                    pa.field("extraction_model", pa.string(), nullable=True),
                    pa.field("source_context", pa.string(), nullable=True),
                    pa.field("analyzed_at", pa.timestamp("us", tz="UTC"), nullable=True),
                    pa.field("analysis_model", pa.string(), nullable=True),
                    pa.field("analysis_json", pa.string(), nullable=True),
                    pa.field("analysis_reasoning", pa.string(), nullable=True),
                ])

                arrow_table = pa.table(updated_data).cast(schema)

                # Upsert with accession_number as join key
                table.upsert(
                    arrow_table,
                    join_cols=["accession_number"],
                    when_matched_update_all=True,
                    when_not_matched_insert_all=False,  # Don't insert new rows
                )

                logger.info(
                    f"Updated extraction for {accession}: "
                    f"{len(extracted_text):,} chars, model={extraction_model}"
                )
                return True

            success = await loop.run_in_executor(None, do_upsert)
            return success

        except Exception as e:
            logger.error(f"Failed to update extraction for {accession}: {e}")
            return False

    async def update_extractions_batch(
        self,
        updates: list[tuple[str, str, str]],
    ) -> int:
        """Batch update extraction fields for multiple filings.

        More efficient than individual updates for bulk extraction jobs.

        Args:
            updates: List of (accession_number, extracted_text, extraction_model) tuples.

        Returns:
            Number of successful updates.
        """
        if not self._enabled or not updates:
            return 0

        try:
            loop = asyncio.get_event_loop()

            def do_batch_upsert():
                import pyarrow as pa
                from pyiceberg.expressions import In

                table = self._get_table()

                # Get all accession numbers to update
                accessions = [normalize_accession_number(u[0]) for u in updates]
                extraction_map = {
                    normalize_accession_number(u[0]): (u[1], u[2])
                    for u in updates
                }

                # Read existing rows (all fields including analysis for preservation)
                scan = table.scan(
                    row_filter=In("accession_number", accessions),
                )
                df = scan.to_pandas()

                if df.empty:
                    logger.warning("No filings found for batch extraction update")
                    return 0

                # Update extraction fields
                now = datetime.now(timezone.utc)
                rows_updated = 0

                updated_rows = []
                for _, row in df.iterrows():
                    accession = row["accession_number"]
                    if accession in extraction_map:
                        extracted_text, extraction_model = extraction_map[accession]
                        updated_row = row.to_dict()
                        updated_row["extracted_text"] = extracted_text
                        updated_row["extracted_at"] = now
                        updated_row["extraction_model"] = extraction_model
                        updated_rows.append(updated_row)
                        rows_updated += 1

                if not updated_rows:
                    return 0

                # Build PyArrow table with full schema (must match Iceberg table)
                schema = pa.schema([
                    pa.field("accession_number", pa.string(), nullable=False),
                    pa.field("symbol", pa.string(), nullable=False),
                    pa.field("cik", pa.string(), nullable=False),
                    pa.field("filing_type", pa.string(), nullable=False),
                    pa.field("filing_date", pa.string(), nullable=False),
                    pa.field("url", pa.string(), nullable=False),
                    pa.field("raw_html", pa.string(), nullable=False),
                    pa.field("content_hash", pa.string(), nullable=False),
                    pa.field("raw_html_length", pa.int64(), nullable=False),
                    pa.field("title", pa.string(), nullable=True),
                    pa.field("fetched_at", pa.timestamp("us", tz="UTC"), nullable=True),
                    pa.field("fetch_latency_ms", pa.int64(), nullable=True),
                    pa.field("extracted_text", pa.string(), nullable=True),
                    pa.field("extracted_at", pa.timestamp("us", tz="UTC"), nullable=True),
                    pa.field("extraction_model", pa.string(), nullable=True),
                    pa.field("source_context", pa.string(), nullable=True),
                    pa.field("analyzed_at", pa.timestamp("us", tz="UTC"), nullable=True),
                    pa.field("analysis_model", pa.string(), nullable=True),
                    pa.field("analysis_json", pa.string(), nullable=True),
                ])

                # Convert to columnar format, handling NaT values
                columns = {col: [_safe_value(r[col]) for r in updated_rows] for col in schema.names}
                arrow_table = pa.table(columns).cast(schema)

                # Upsert batch
                table.upsert(
                    arrow_table,
                    join_cols=["accession_number"],
                    when_matched_update_all=True,
                    when_not_matched_insert_all=False,
                )

                logger.info(f"Batch updated extraction for {rows_updated} filings")
                return rows_updated

            count = await loop.run_in_executor(None, do_batch_upsert)
            return count

        except Exception as e:
            logger.error(f"Failed to batch update extractions: {e}")
            return 0

    def _filing_to_arrow(self, filing: EdgarFiling) -> "pa.Table":
        """Convert a single filing to PyArrow table."""
        import pyarrow as pa

        # Full schema must match Iceberg table schema
        schema = pa.schema([
            pa.field("accession_number", pa.string(), nullable=False),
            pa.field("symbol", pa.string(), nullable=False),
            pa.field("cik", pa.string(), nullable=False),
            pa.field("filing_type", pa.string(), nullable=False),
            pa.field("filing_date", pa.string(), nullable=False),
            pa.field("url", pa.string(), nullable=False),
            pa.field("raw_html", pa.string(), nullable=False),
            pa.field("content_hash", pa.string(), nullable=False),
            pa.field("raw_html_length", pa.int64(), nullable=False),
            pa.field("title", pa.string(), nullable=True),
            pa.field("fetched_at", pa.timestamp("us", tz="UTC"), nullable=True),
            pa.field("fetch_latency_ms", pa.int64(), nullable=True),
            pa.field("extracted_text", pa.string(), nullable=True),
            pa.field("extracted_at", pa.timestamp("us", tz="UTC"), nullable=True),
            pa.field("extraction_model", pa.string(), nullable=True),
            pa.field("source_context", pa.string(), nullable=True),
            pa.field("analyzed_at", pa.timestamp("us", tz="UTC"), nullable=True),
            pa.field("analysis_model", pa.string(), nullable=True),
            pa.field("analysis_json", pa.string(), nullable=True),
        ])

        data = {
            "accession_number": [filing.accession_number],
            "symbol": [filing.symbol],
            "cik": [filing.cik],
            "filing_type": [filing.filing_type],
            "filing_date": [filing.filing_date],
            "url": [filing.url],
            "raw_html": [filing.raw_html],
            "content_hash": [filing.content_hash],
            "raw_html_length": [filing.raw_html_length],
            "title": [filing.title or ""],
            "fetched_at": [filing.fetched_at],
            "fetch_latency_ms": [filing.fetch_latency_ms],
            "extracted_text": [filing.extracted_text],
            "extracted_at": [filing.extracted_at],
            "extraction_model": [filing.extraction_model],
            "source_context": [json.dumps(filing.source_context)],
            "analyzed_at": [filing.analyzed_at],
            "analysis_model": [filing.analysis_model],
            "analysis_json": [filing.analysis_json],
        }

        return pa.table(data).cast(schema)


# Legacy alias for backward compatibility
EdgarExchangeRecord = EdgarFiling
EdgarExchangeCapture = EdgarFilingSync


# Singleton instance
_edgar_sync: EdgarFilingSync | None = None


def get_edgar_sync() -> EdgarFilingSync:
    """Get the singleton EDGAR filing sync instance."""
    global _edgar_sync
    if _edgar_sync is None:
        _edgar_sync = EdgarFilingSync()
    return _edgar_sync


# Legacy alias
def get_edgar_capture() -> EdgarFilingSync:
    """Legacy alias for get_edgar_sync()."""
    return get_edgar_sync()
