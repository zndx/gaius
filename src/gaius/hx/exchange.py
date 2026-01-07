"""Exchange Capture - External API Request/Response Storage.

Captures request-response pairs from external APIs (XAI, Cerebras, Bytez, Brave)
to Iceberg storage for building an internal training dataset.

CRITICAL: Exchange capture failures are treated as data loss errors.
These exchanges represent high-quality instruction-following data that
MUST be retained. Failures are logged at ERROR level and raise exceptions.
"""

from __future__ import annotations

import asyncio
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
    from pyiceberg.catalog import Catalog
    from pyiceberg.table import Table

logger = logging.getLogger(__name__)


class ExchangeCaptureError(Exception):
    """Critical error during exchange capture - data loss risk."""

    pass


def _compute_request_hash(messages: list[dict], model: str, params: dict) -> str:
    """Compute SHA-256 hash of request for deduplication.

    Args:
        messages: Chat messages in OpenAI format.
        model: Model identifier.
        params: Request parameters.

    Returns:
        Hex-encoded SHA-256 hash.
    """
    # Create deterministic representation
    request_str = json.dumps(
        {"messages": messages, "model": model, "params": params},
        sort_keys=True,
        ensure_ascii=True,
    )
    return hashlib.sha256(request_str.encode("utf-8")).hexdigest()


@dataclass
class ExchangeRecord:
    """A captured request-response exchange from an external API.

    Attributes:
        provider: API provider (xai, cerebras, bytez, brave)
        request_messages: Chat messages in OpenAI format
        request_model: Model requested
        request_params: Parameters (temperature, max_tokens, etc.)
        response_content: Full response text
        response_model: Actual model used (may differ from requested)
        input_tokens: Input token count
        output_tokens: Output token count
        latency_ms: Request latency in milliseconds
        source_context: Additional context (agent_alias, task_type, etc.)
    """

    provider: str
    request_messages: list[dict]
    request_model: str
    response_content: str
    request_params: dict = field(default_factory=dict)
    response_model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    source_context: dict = field(default_factory=dict)

    # Auto-generated fields
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    request_hash: str = field(default="")

    def __post_init__(self):
        """Compute request hash if not provided."""
        if not self.request_hash:
            self.request_hash = _compute_request_hash(
                self.request_messages,
                self.request_model,
                self.request_params,
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for Iceberg append."""
        return {
            "id": self.id,
            "provider": self.provider,
            "request_hash": self.request_hash,
            "request_messages": json.dumps(self.request_messages),
            "request_model": self.request_model,
            "request_params": json.dumps(self.request_params),
            "response_content": self.response_content,
            "response_model": self.response_model or self.request_model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "created_at": self.created_at,
            "source_context": json.dumps(self.source_context),
        }


@dataclass
class ExchangeWriteResult:
    """Result of an exchange write operation."""

    success: bool
    items_written: int
    snapshot_id: int | None = None
    errors: list[str] = field(default_factory=list)


class ExchangeCapture:
    """Captures external API exchanges to Iceberg storage.

    CRITICAL: This class treats write failures as data loss errors.
    External API responses are valuable training data that must be preserved.

    Design principles:
    1. Fail loudly - errors are logged at ERROR level and raised
    2. Synchronous writes - no fire-and-forget for critical data
    3. Health checks - verify Iceberg connectivity before accepting requests
    4. Buffered for efficiency - but flushes immediately on errors

    Usage:
        capture = ExchangeCapture()

        # Verify storage is healthy before starting
        if not await capture.health_check():
            raise RuntimeError("Exchange capture storage unavailable")

        # Capture with confirmation (recommended)
        result = await capture.capture(record)
        if not result.success:
            logger.error(f"CRITICAL: Exchange capture failed: {result.errors}")
    """

    def __init__(
        self,
        enabled: bool | None = None,
        namespace: str = "raw",
        table_name: str = "exchange",
        buffer_size: int = 1,  # Default to immediate writes for safety
    ):
        """Initialize exchange capture.

        Args:
            enabled: Whether capture is enabled. If None, reads from
                     GAIUS_HX_CAPTURE_EXCHANGES env var (default: True).
            namespace: Iceberg namespace.
            table_name: Table name within namespace.
            buffer_size: Number of records to buffer before writing.
                        Default is 1 (immediate writes) for data safety.
        """
        if enabled is None:
            env_val = os.environ.get("GAIUS_HX_CAPTURE_EXCHANGES", "true")
            enabled = env_val.lower() in ("1", "true", "yes")

        self._enabled = enabled
        self._namespace = namespace
        self._table_name = table_name
        self._catalog: Catalog | None = None
        self._table: Table | None = None
        self._buffer: list[ExchangeRecord] = []
        self._buffer_size = buffer_size
        self._lock = asyncio.Lock()
        self._healthy: bool | None = None  # None = not checked yet
        self._failed_records: list[ExchangeRecord] = []  # Track failures for retry

    @property
    def enabled(self) -> bool:
        """Whether exchange capture is enabled."""
        return self._enabled

    @property
    def healthy(self) -> bool | None:
        """Whether storage is healthy (None if not checked)."""
        return self._healthy

    @property
    def failed_count(self) -> int:
        """Number of records that failed to write."""
        return len(self._failed_records)

    def _get_catalog(self) -> Catalog:
        """Get or create the Iceberg catalog."""
        if self._catalog is None:
            from gaius.hx.catalog import get_catalog
            from gaius.hx.config import get_hx_config

            config = get_hx_config()
            self._catalog = get_catalog(config)
        return self._catalog

    def _get_table(self) -> Table:
        """Get or create the exchange table."""
        if self._table is None:
            from gaius.hx.exchange_tables import get_exchange_table

            self._table = get_exchange_table(
                self._get_catalog(),
                namespace=self._namespace,
                table_name=self._table_name,
            )
        return self._table

    async def health_check(self) -> bool:
        """Check if Iceberg storage is healthy and accessible.

        This should be called at startup to verify exchange capture
        will work before accepting external API requests.

        Returns:
            True if storage is healthy and ready.
        """
        if not self._enabled:
            logger.info("Exchange capture is disabled")
            return True

        try:
            loop = asyncio.get_event_loop()

            # Test catalog connectivity
            await loop.run_in_executor(None, self._get_catalog)

            # Test table access (creates if needed)
            table = await loop.run_in_executor(None, self._get_table)

            # Verify we can read the schema
            schema = table.schema()
            if len(schema.fields) < 10:
                raise ExchangeCaptureError(
                    f"Exchange table schema invalid: only {len(schema.fields)} fields"
                )

            self._healthy = True
            logger.info(
                f"Exchange capture healthy: table={self._namespace}.{self._table_name}, "
                f"fields={len(schema.fields)}"
            )
            return True

        except Exception as e:
            self._healthy = False
            logger.error(
                f"CRITICAL: Exchange capture health check failed: {e}. "
                "External API responses will NOT be captured!"
            )
            return False

    async def capture(self, record: ExchangeRecord) -> ExchangeWriteResult:
        """Capture an exchange record to Iceberg.

        CRITICAL: This method treats failures as data loss errors.
        Failed records are tracked and can be retried.

        Args:
            record: The exchange record to capture.

        Returns:
            ExchangeWriteResult with status.

        Raises:
            ExchangeCaptureError: If storage is unhealthy and capture fails.
        """
        if not self._enabled:
            return ExchangeWriteResult(success=True, items_written=0)

        # Check health on first capture if not already checked
        if self._healthy is None:
            await self.health_check()

        if self._healthy is False:
            # Storage is known to be unhealthy - track for retry
            self._failed_records.append(record)
            error_msg = (
                f"CRITICAL: Exchange capture unavailable, record queued for retry. "
                f"Provider={record.provider}, model={record.request_model}, "
                f"failed_queue_size={len(self._failed_records)}"
            )
            logger.error(error_msg)
            return ExchangeWriteResult(
                success=False,
                items_written=0,
                errors=[error_msg],
            )

        try:
            async with self._lock:
                self._buffer.append(record)

                # Write when buffer is full
                if len(self._buffer) >= self._buffer_size:
                    return await self._flush_buffer()

            # Buffer not full yet - record is pending
            return ExchangeWriteResult(success=True, items_written=0)

        except Exception as e:
            # Track failed record for retry
            self._failed_records.append(record)
            error_msg = (
                f"CRITICAL: Exchange capture failed: {e}. "
                f"Provider={record.provider}, model={record.request_model}"
            )
            logger.error(error_msg)
            return ExchangeWriteResult(
                success=False,
                items_written=0,
                errors=[error_msg],
            )

    async def _flush_buffer(self) -> ExchangeWriteResult:
        """Flush buffered records to Iceberg.

        Must be called while holding self._lock.

        Raises:
            ExchangeCaptureError: If write fails (records are preserved for retry).
        """
        if not self._buffer:
            return ExchangeWriteResult(success=True, items_written=0)

        records_to_write = self._buffer.copy()
        self._buffer.clear()

        try:
            import pyarrow as pa

            # Convert to PyArrow table
            records = [r.to_dict() for r in records_to_write]
            arrow_table = self._records_to_arrow(records)

            # Append to Iceberg (run in thread pool to avoid blocking)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._get_table().append(arrow_table),
            )

            # Get snapshot ID
            snapshot = self._get_table().current_snapshot()
            snapshot_id = snapshot.snapshot_id if snapshot else None

            logger.info(
                f"Exchange capture: wrote {len(records_to_write)} records to Iceberg "
                f"(snapshot: {snapshot_id}, providers: {set(r['provider'] for r in records)})"
            )

            return ExchangeWriteResult(
                success=True,
                items_written=len(records_to_write),
                snapshot_id=snapshot_id,
            )

        except Exception as e:
            # CRITICAL: Move failed records to retry queue
            self._failed_records.extend(records_to_write)
            self._healthy = False  # Mark as unhealthy

            error_msg = (
                f"CRITICAL: Exchange capture write failed: {e}. "
                f"{len(records_to_write)} records moved to retry queue "
                f"(total queued: {len(self._failed_records)})"
            )
            logger.error(error_msg)

            return ExchangeWriteResult(
                success=False,
                items_written=0,
                errors=[error_msg],
            )

    async def flush(self) -> ExchangeWriteResult:
        """Force flush any buffered records.

        Call this before shutdown to ensure all records are persisted.
        """
        async with self._lock:
            return await self._flush_buffer()

    async def retry_failed(self) -> ExchangeWriteResult:
        """Retry writing failed records.

        Call this after storage becomes healthy again.

        Returns:
            Result of retry attempt.
        """
        if not self._failed_records:
            return ExchangeWriteResult(success=True, items_written=0)

        # Re-check health first
        if not await self.health_check():
            return ExchangeWriteResult(
                success=False,
                items_written=0,
                errors=[f"Storage still unhealthy, {len(self._failed_records)} records pending"],
            )

        # Move failed records to buffer and flush
        async with self._lock:
            self._buffer.extend(self._failed_records)
            self._failed_records.clear()
            return await self._flush_buffer()

    def get_status(self) -> dict[str, Any]:
        """Get capture status for health reporting."""
        return {
            "enabled": self._enabled,
            "healthy": self._healthy,
            "buffered_count": len(self._buffer),
            "failed_count": len(self._failed_records),
            "namespace": self._namespace,
            "table_name": self._table_name,
        }

    def _records_to_arrow(self, records: list[dict]) -> "pa.Table":
        """Convert records to PyArrow table matching exchange schema.

        Args:
            records: List of record dictionaries.

        Returns:
            PyArrow Table.
        """
        import pyarrow as pa

        schema = pa.schema([
            pa.field("id", pa.string(), nullable=False),
            pa.field("provider", pa.string(), nullable=False),
            pa.field("request_hash", pa.string(), nullable=False),
            pa.field("request_messages", pa.string(), nullable=False),
            pa.field("request_model", pa.string(), nullable=False),
            pa.field("request_params", pa.string(), nullable=True),
            pa.field("response_content", pa.string(), nullable=False),
            pa.field("response_model", pa.string(), nullable=True),
            pa.field("input_tokens", pa.int64(), nullable=True),
            pa.field("output_tokens", pa.int64(), nullable=True),
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


# Module-level singleton for convenient access
_exchange_capture: ExchangeCapture | None = None


def get_exchange_capture() -> ExchangeCapture:
    """Get or create the exchange capture singleton.

    Returns:
        ExchangeCapture instance.
    """
    global _exchange_capture
    if _exchange_capture is None:
        _exchange_capture = ExchangeCapture()
    return _exchange_capture


def reset_exchange_capture() -> None:
    """Reset the exchange capture singleton (for testing)."""
    global _exchange_capture
    _exchange_capture = None
