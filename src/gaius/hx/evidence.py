"""Evidence Capture - RASE Verification Result Storage.

Captures verification results from the RASE objective verification pipeline
to Iceberg storage for training and audit purposes.

Evidence is stored at hx://rase.evidence partitioned by:
- domain (kb, nifi, etc.)
- month (for time-based queries)

Each record contains:
- Objective metadata
- Verification result (verdict, accuracy, reward)
- Constraint results for debugging
- Digital thread for training lineage

CRITICAL: Evidence capture failures are treated as data loss errors.
Verification evidence is essential for training signal and must be retained.
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
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pyiceberg.catalog import Catalog
    from pyiceberg.table import Table

logger = logging.getLogger(__name__)


class EvidenceCaptureError(Exception):
    """Critical error during evidence capture - data loss risk."""

    pass


@dataclass
class EvidenceRecord:
    """A captured verification result from RASE.

    Attributes:
        objective_name: Name of the verified objective
        domain: Verification domain (kb, nifi, etc.)
        verdict: Verification verdict (pass, fail, inconclusive, error)
        accuracy: Accuracy score 0.0-1.0
        reward: Computed reward for training
        gates_total: Total number of gates evaluated
        gates_passed: Number of gates that passed
        constraint_results: List of constraint result dicts
        document_path: Path to verified document (if applicable)
        thread_id: TraceableId of digital thread
        thread_data: Full digital thread data (optional)
        objective_type: Type of objective (rase-objective, etc.)
        document_hash: SHA-256 of document content
        duration_ms: Verification duration in milliseconds
        is_training_eligible: Whether eligible for training
        calibration_source: External calibration source (cerebras, xai)
        calibration_score: External calibration score
    """

    objective_name: str
    domain: str
    verdict: str
    accuracy: float
    reward: float
    gates_total: int
    gates_passed: int
    constraint_results: list[dict]
    thread_id: str

    # Optional fields
    document_path: str | None = None
    thread_data: dict | None = None
    objective_type: str = "rase-objective"
    document_hash: str | None = None
    duration_ms: int | None = None
    is_training_eligible: bool = True
    calibration_source: str | None = None
    calibration_score: float | None = None

    # Auto-generated fields
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str = field(default="")
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        """Generate run_id if not provided."""
        if not self.run_id:
            timestamp = self.created_at.strftime("%Y%m%d_%H%M%S")
            short_id = self.id[:8]
            self.run_id = f"{timestamp}_{short_id}"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for Iceberg append."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "objective_name": self.objective_name,
            "objective_type": self.objective_type,
            "domain": self.domain,
            "verdict": self.verdict,
            "accuracy": self.accuracy,
            "reward": self.reward,
            "gates_total": self.gates_total,
            "gates_passed": self.gates_passed,
            "constraint_results": json.dumps(self.constraint_results),
            "document_path": self.document_path,
            "document_hash": self.document_hash,
            "thread_id": self.thread_id,
            "thread_data": json.dumps(self.thread_data) if self.thread_data else None,
            "created_at": self.created_at,
            "duration_ms": self.duration_ms,
            "is_training_eligible": self.is_training_eligible,
            "calibration_source": self.calibration_source,
            "calibration_score": self.calibration_score,
        }


@dataclass
class EvidenceWriteResult:
    """Result of an evidence write operation."""

    success: bool
    items_written: int
    snapshot_id: int | None = None
    run_id: str | None = None
    errors: list[str] = field(default_factory=list)


class EvidenceCapture:
    """Captures RASE verification evidence to Iceberg storage.

    CRITICAL: This class treats write failures as data loss errors.
    Verification evidence is essential for training and must be preserved.

    Design principles:
    1. Fail loudly - errors are logged at ERROR level
    2. Synchronous writes - no fire-and-forget for critical data
    3. Health checks - verify Iceberg connectivity before accepting results
    4. KB manifests - write thin manifests to KB for navigation

    Usage:
        capture = EvidenceCapture()

        # Verify storage is healthy before starting
        if not await capture.health_check():
            raise RuntimeError("Evidence capture storage unavailable")

        # Capture with confirmation
        result = await capture.capture(record)
        if not result.success:
            logger.error(f"CRITICAL: Evidence capture failed: {result.errors}")
    """

    def __init__(
        self,
        enabled: bool | None = None,
        namespace: str = "rase",
        table_name: str = "evidence",
        kb_root: str | None = None,
        write_kb_manifests: bool = True,
    ):
        """Initialize evidence capture.

        Args:
            enabled: Whether capture is enabled. If None, reads from
                     GAIUS_HX_CAPTURE_EVIDENCE env var (default: True).
            namespace: Iceberg namespace.
            table_name: Table name within namespace.
            kb_root: KB root for thin manifests. If None, uses GAIUS_KB_ROOT.
            write_kb_manifests: Whether to write thin manifests to KB.
        """
        if enabled is None:
            env_val = os.environ.get("GAIUS_HX_CAPTURE_EVIDENCE", "true")
            enabled = env_val.lower() in ("1", "true", "yes")

        self._enabled = enabled
        self._namespace = namespace
        self._table_name = table_name
        self._kb_root = kb_root or os.environ.get("GAIUS_KB_ROOT", "build/dev")
        self._write_kb_manifests = write_kb_manifests
        self._catalog: Catalog | None = None
        self._table: Table | None = None
        self._healthy: bool | None = None
        self._failed_records: list[EvidenceRecord] = []
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        """Whether evidence capture is enabled."""
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
        """Get or create the evidence table."""
        if self._table is None:
            from gaius.hx.evidence_tables import get_evidence_table

            self._table = get_evidence_table(
                self._get_catalog(),
                namespace=self._namespace,
                table_name=self._table_name,
            )
        return self._table

    async def health_check(self) -> bool:
        """Check if Iceberg storage is healthy and accessible.

        This should be called at startup to verify evidence capture
        will work before accepting verification results.

        Returns:
            True if storage is healthy and ready.
        """
        if not self._enabled:
            logger.info("Evidence capture is disabled")
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
                raise EvidenceCaptureError(
                    f"Evidence table schema invalid: only {len(schema.fields)} fields"
                )

            self._healthy = True
            logger.info(
                f"Evidence capture healthy: table={self._namespace}.{self._table_name}, "
                f"fields={len(schema.fields)}"
            )
            return True

        except Exception as e:
            self._healthy = False
            logger.error(
                f"CRITICAL: Evidence capture health check failed: {e}. "
                "Verification results will NOT be captured!"
            )
            return False

    async def capture(self, record: EvidenceRecord) -> EvidenceWriteResult:
        """Capture a verification evidence record to Iceberg.

        CRITICAL: This method treats failures as data loss errors.
        Failed records are tracked and can be retried.

        Args:
            record: The evidence record to capture.

        Returns:
            EvidenceWriteResult with status.
        """
        if not self._enabled:
            return EvidenceWriteResult(
                success=True,
                items_written=0,
                run_id=record.run_id,
            )

        # Check health on first capture if not already checked
        if self._healthy is None:
            await self.health_check()

        if self._healthy is False:
            # Storage is known to be unhealthy - track for retry
            self._failed_records.append(record)
            error_msg = (
                f"CRITICAL: Evidence capture unavailable, record queued for retry. "
                f"Objective={record.objective_name}, verdict={record.verdict}, "
                f"failed_queue_size={len(self._failed_records)}"
            )
            logger.error(error_msg)
            return EvidenceWriteResult(
                success=False,
                items_written=0,
                run_id=record.run_id,
                errors=[error_msg],
            )

        try:
            async with self._lock:
                return await self._write_record(record)

        except Exception as e:
            # Track failed record for retry
            self._failed_records.append(record)
            error_msg = (
                f"CRITICAL: Evidence capture failed: {e}. "
                f"Objective={record.objective_name}, verdict={record.verdict}"
            )
            logger.error(error_msg)
            return EvidenceWriteResult(
                success=False,
                items_written=0,
                run_id=record.run_id,
                errors=[error_msg],
            )

    async def _write_record(self, record: EvidenceRecord) -> EvidenceWriteResult:
        """Write a single record to Iceberg.

        Must be called while holding self._lock.
        """
        import pyarrow as pa

        # Convert to PyArrow table
        records = [record.to_dict()]
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
            f"Evidence capture: wrote 1 record to Iceberg "
            f"(run_id={record.run_id}, objective={record.objective_name}, "
            f"verdict={record.verdict}, snapshot={snapshot_id})"
        )

        # Write KB manifest if enabled
        if self._write_kb_manifests:
            await self._write_kb_manifest(record)

        return EvidenceWriteResult(
            success=True,
            items_written=1,
            snapshot_id=snapshot_id,
            run_id=record.run_id,
        )

    async def _write_kb_manifest(self, record: EvidenceRecord) -> str:
        """Write thin manifest to KB for navigation.

        Args:
            record: The evidence record.

        Returns:
            Path to KB manifest.
        """
        # Build constraint summary table
        constraint_rows = []
        for c in record.constraint_results:
            status = "[OK]" if c.get("satisfied", False) else "[FAIL]"
            name = c.get("name", "unknown")
            message = c.get("message", "")[:60]
            constraint_rows.append(f"| {name} | {status} | {message} |")

        constraint_table = "\n".join(constraint_rows) if constraint_rows else "| - | - | - |"

        # Build hx:// path
        hx_path = f"hx://{self._namespace}.{self._table_name}"

        content = f"""---
run_id: {record.run_id}
objective: {record.objective_name}
domain: {record.domain}
timestamp: {record.created_at.isoformat()}
verdict: {record.verdict}
accuracy: {record.accuracy}
reward: {record.reward}
evidence_table: {hx_path}
---

# Verification Evidence: {record.objective_name}

**Run ID**: `{record.run_id}`
**Domain**: {record.domain}
**Verdict**: {record.verdict}
**Accuracy**: {record.accuracy:.2%}
**Reward**: {record.reward:.2f}

## Gates

| Gate | Status | Message |
|------|--------|---------|
{constraint_table}

## Evidence Storage

Evidence stored in Iceberg at:
- Table: `{hx_path}`
- Query: `SELECT * FROM {self._namespace}.{self._table_name} WHERE run_id = '{record.run_id}'`

## Training Eligibility

- **Eligible**: {"Yes" if record.is_training_eligible else "No"}
- **Calibration**: {record.calibration_source or "None"}
- **Calibration Score**: {record.calibration_score if record.calibration_score else "N/A"}
"""

        # Write to KB filesystem
        evidence_dir = Path(self._kb_root) / "current/objectives/evidence" / record.objective_name
        evidence_dir.mkdir(parents=True, exist_ok=True)

        manifest_path = evidence_dir / f"{record.run_id}.md"
        manifest_path.write_text(content)

        rel_path = str(manifest_path.relative_to(self._kb_root))
        logger.debug(f"Wrote KB manifest: {rel_path}")

        return rel_path

    async def retry_failed(self) -> EvidenceWriteResult:
        """Retry writing failed records.

        Call this after storage becomes healthy again.

        Returns:
            Result of retry attempt.
        """
        if not self._failed_records:
            return EvidenceWriteResult(success=True, items_written=0)

        # Re-check health first
        if not await self.health_check():
            return EvidenceWriteResult(
                success=False,
                items_written=0,
                errors=[f"Storage still unhealthy, {len(self._failed_records)} records pending"],
            )

        # Retry each record
        failed = []
        written = 0

        for record in self._failed_records:
            try:
                async with self._lock:
                    result = await self._write_record(record)
                    if result.success:
                        written += 1
                    else:
                        failed.append(record)
            except Exception as e:
                logger.error(f"Retry failed for {record.run_id}: {e}")
                failed.append(record)

        self._failed_records = failed

        if failed:
            return EvidenceWriteResult(
                success=False,
                items_written=written,
                errors=[f"{len(failed)} records still pending"],
            )

        return EvidenceWriteResult(success=True, items_written=written)

    def get_status(self) -> dict[str, Any]:
        """Get capture status for health reporting."""
        return {
            "enabled": self._enabled,
            "healthy": self._healthy,
            "failed_count": len(self._failed_records),
            "namespace": self._namespace,
            "table_name": self._table_name,
            "kb_root": self._kb_root,
            "write_kb_manifests": self._write_kb_manifests,
        }

    def _records_to_arrow(self, records: list[dict]) -> "pa.Table":
        """Convert records to PyArrow table matching evidence schema.

        Args:
            records: List of record dictionaries.

        Returns:
            PyArrow Table.
        """
        import pyarrow as pa

        schema = pa.schema([
            pa.field("id", pa.string(), nullable=False),
            pa.field("run_id", pa.string(), nullable=False),
            pa.field("objective_name", pa.string(), nullable=False),
            pa.field("objective_type", pa.string(), nullable=True),
            pa.field("domain", pa.string(), nullable=False),
            pa.field("verdict", pa.string(), nullable=False),
            pa.field("accuracy", pa.float64(), nullable=False),
            pa.field("reward", pa.float64(), nullable=False),
            pa.field("gates_total", pa.int64(), nullable=False),
            pa.field("gates_passed", pa.int64(), nullable=False),
            pa.field("constraint_results", pa.string(), nullable=False),
            pa.field("document_path", pa.string(), nullable=True),
            pa.field("document_hash", pa.string(), nullable=True),
            pa.field("thread_id", pa.string(), nullable=False),
            pa.field("thread_data", pa.string(), nullable=True),
            pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("duration_ms", pa.int64(), nullable=True),
            pa.field("is_training_eligible", pa.bool_(), nullable=True),
            pa.field("calibration_source", pa.string(), nullable=True),
            pa.field("calibration_score", pa.float64(), nullable=True),
        ])

        # Ensure timestamps are timezone-aware
        for record in records:
            if record.get("created_at"):
                dt = record["created_at"]
                if dt.tzinfo is None:
                    record["created_at"] = dt.replace(tzinfo=timezone.utc)

        return pa.Table.from_pylist(records, schema=schema)


# Module-level singleton for convenient access
_evidence_capture: EvidenceCapture | None = None


def get_evidence_capture() -> EvidenceCapture:
    """Get or create the evidence capture singleton.

    Returns:
        EvidenceCapture instance.
    """
    global _evidence_capture
    if _evidence_capture is None:
        _evidence_capture = EvidenceCapture()
    return _evidence_capture


def reset_evidence_capture() -> None:
    """Reset the evidence capture singleton (for testing)."""
    global _evidence_capture
    _evidence_capture = None


__all__ = [
    "EvidenceCaptureError",
    "EvidenceRecord",
    "EvidenceWriteResult",
    "EvidenceCapture",
    "get_evidence_capture",
    "reset_evidence_capture",
]
