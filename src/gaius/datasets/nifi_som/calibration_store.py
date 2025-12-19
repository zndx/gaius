"""Iceberg-based Calibration Storage for XAI Calibration History.

Persists calibration samples to Iceberg tables in S3/MinIO following
the hx.writer pattern. Stores both local and XAI scores for analysis
and calibration factor training.

Storage path: s3://zndx-gaius/datasets/{dataset_id}/hx/calibration/

Schema includes:
- Example identification
- Local 4-dimension scores (input)
- XAI 6-dimension scores (labels)
- Evidence and error types
- Metadata (model, tokens, timestamp)

Usage:
    from gaius.datasets.nifi_som.calibration_store import (
        CalibrationStore,
        CalibrationItem,
    )

    store = CalibrationStore(dataset_id="nifi-som-v1")
    result = store.store_samples(items)
    print(f"Stored {result.items_written} samples")
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .rubric import RubricScore, RubricDimension

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class CalibrationItem:
    """A calibration sample for Iceberg storage.

    Contains both local model scores (input) and XAI scores (labels)
    for training local verifiers and calibration factor computation.
    """

    # Identity
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    example_id: str = ""
    dataset_id: str = ""

    # Example content
    instruction: str = ""
    target_name: str = ""
    target_type: str = ""
    action_type: str = ""

    # Local 4-dimension scores (input to calibration)
    local_clarity: float = 0.0
    local_naturalness: float = 0.0
    local_specificity: float = 0.0
    local_conciseness: float = 0.0
    local_overall: float = 0.0

    # XAI 6-dimension scores (0-4 ordinal)
    xai_intent: int = 0
    xai_som_grounding: int = 0
    xai_action_semantics: int = 0
    xai_tom_trace: int = 0
    xai_constraints: int = 0
    xai_outcome: int = 0
    xai_overall: float = 0.0  # Weighted reward

    # Evidence (JSON-encoded per dimension)
    evidence_json: str = "{}"

    # Error types (JSON-encoded, only for scores <= 2)
    errors_json: str = "{}"

    # Calibration delta (XAI overall - local overall mapped)
    calibration_delta: float = 0.0

    # Metadata
    xai_model: str = ""
    tokens_used: int = 0
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Convert to dictionary for Iceberg/PyArrow."""
        return {
            "id": self.id,
            "example_id": self.example_id,
            "dataset_id": self.dataset_id,
            "instruction": self.instruction,
            "target_name": self.target_name,
            "target_type": self.target_type,
            "action_type": self.action_type,
            "local_clarity": self.local_clarity,
            "local_naturalness": self.local_naturalness,
            "local_specificity": self.local_specificity,
            "local_conciseness": self.local_conciseness,
            "local_overall": self.local_overall,
            "xai_intent": self.xai_intent,
            "xai_som_grounding": self.xai_som_grounding,
            "xai_action_semantics": self.xai_action_semantics,
            "xai_tom_trace": self.xai_tom_trace,
            "xai_constraints": self.xai_constraints,
            "xai_outcome": self.xai_outcome,
            "xai_overall": self.xai_overall,
            "evidence_json": self.evidence_json,
            "errors_json": self.errors_json,
            "calibration_delta": self.calibration_delta,
            "xai_model": self.xai_model,
            "tokens_used": self.tokens_used,
            "evaluated_at": self.evaluated_at,
        }

    @classmethod
    def from_rubric_score(
        cls,
        rubric_score: RubricScore,
        dataset_id: str,
        instruction: str,
        target_name: str,
        target_type: str,
        action_type: str,
        local_clarity: float,
        local_naturalness: float,
        local_specificity: float,
        local_conciseness: float,
        local_overall: float,
    ) -> "CalibrationItem":
        """Create CalibrationItem from RubricScore and local scores.

        Args:
            rubric_score: XAI evaluation result
            dataset_id: Dataset identifier
            instruction: The instruction text
            target_name: Target element name
            target_type: Target element type
            action_type: Action type (click, type, etc.)
            local_*: Local model scores

        Returns:
            CalibrationItem ready for storage
        """
        # Extract XAI scores
        xai_scores = {
            "intent": rubric_score.dimension_scores.get(
                RubricDimension.INTENT
            ),
            "som_grounding": rubric_score.dimension_scores.get(
                RubricDimension.SOM_GROUNDING
            ),
            "action_semantics": rubric_score.dimension_scores.get(
                RubricDimension.ACTION_SEMANTICS
            ),
            "tom_trace": rubric_score.dimension_scores.get(
                RubricDimension.TOM_TRACE
            ),
            "constraints": rubric_score.dimension_scores.get(
                RubricDimension.CONSTRAINTS
            ),
            "outcome": rubric_score.dimension_scores.get(
                RubricDimension.OUTCOME
            ),
        }

        # Build evidence dict
        evidence = {}
        errors = {}
        for dim_name, dim_score in xai_scores.items():
            if dim_score:
                evidence[dim_name] = dim_score.evidence
                if dim_score.error_type:
                    errors[dim_name] = dim_score.error_type

        # Compute calibration delta
        # Map local overall to 0-1 (assume it's already 0-1)
        xai_overall = rubric_score.weighted_reward
        calibration_delta = xai_overall - local_overall

        return cls(
            example_id=rubric_score.example_id,
            dataset_id=dataset_id,
            instruction=instruction,
            target_name=target_name,
            target_type=target_type,
            action_type=action_type,
            local_clarity=local_clarity,
            local_naturalness=local_naturalness,
            local_specificity=local_specificity,
            local_conciseness=local_conciseness,
            local_overall=local_overall,
            xai_intent=xai_scores["intent"].score if xai_scores["intent"] else 0,
            xai_som_grounding=xai_scores["som_grounding"].score if xai_scores["som_grounding"] else 0,
            xai_action_semantics=xai_scores["action_semantics"].score if xai_scores["action_semantics"] else 0,
            xai_tom_trace=xai_scores["tom_trace"].score if xai_scores["tom_trace"] else 0,
            xai_constraints=xai_scores["constraints"].score if xai_scores["constraints"] else 0,
            xai_outcome=xai_scores["outcome"].score if xai_scores["outcome"] else 0,
            xai_overall=xai_overall,
            evidence_json=json.dumps(evidence),
            errors_json=json.dumps(errors),
            calibration_delta=calibration_delta,
            xai_model=rubric_score.evaluator_model,
            tokens_used=rubric_score.tokens_used,
            evaluated_at=rubric_score.evaluated_at,
        )


@dataclass
class WriteResult:
    """Result of a write operation."""

    success: bool
    items_written: int
    snapshot_id: Optional[int] = None
    errors: list[str] = field(default_factory=list)
    table_path: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Iceberg Store
# ─────────────────────────────────────────────────────────────────────────────


class CalibrationStore:
    """Write calibration samples to Iceberg in S3.

    Follows the hx.writer.IcebergContentStore pattern for consistency
    with the broader Gaius data lake architecture.

    Storage location:
        s3://zndx-gaius/datasets/{dataset_id}/hx/calibration/

    Table name:
        gaius_calibration.calibration_{dataset_id}
    """

    def __init__(
        self,
        dataset_id: str,
        namespace: str = "gaius_calibration",
    ):
        """Initialize calibration store.

        Args:
            dataset_id: Dataset identifier (e.g., "nifi-som-v1")
            namespace: Iceberg namespace
        """
        self.dataset_id = dataset_id
        self.namespace = namespace
        self.table_name = f"calibration_{dataset_id.replace('-', '_')}"
        self.s3_prefix = f"datasets/{dataset_id}/hx/calibration"

        self._catalog = None
        self._table = None

    @property
    def catalog(self):
        """Get the Iceberg catalog."""
        if self._catalog is None:
            try:
                from gaius.hx.catalog import get_catalog
                from gaius.hx.config import get_hx_config
                config = get_hx_config()
                self._catalog = get_catalog(config)
            except ImportError:
                logger.warning("hx module not available, using local fallback")
                self._catalog = None
        return self._catalog

    @property
    def table(self):
        """Get or create the calibration table."""
        if self._table is None and self.catalog is not None:
            self._table = self._ensure_table()
        return self._table

    def _ensure_table(self):
        """Ensure calibration table exists with correct schema."""
        try:
            # Try to load existing table
            table_id = f"{self.namespace}.{self.table_name}"
            return self.catalog.load_table(table_id)
        except Exception:
            # Create table with schema
            return self._create_table()

    def _create_table(self):
        """Create the calibration table."""
        import pyarrow as pa
        from pyiceberg.schema import Schema
        from pyiceberg.types import (
            StringType,
            LongType,
            DoubleType,
            TimestamptzType,
            NestedField,
        )

        # Define Iceberg schema
        schema = Schema(
            NestedField(1, "id", StringType(), required=True),
            NestedField(2, "example_id", StringType(), required=True),
            NestedField(3, "dataset_id", StringType(), required=True),
            NestedField(4, "instruction", StringType(), required=True),
            NestedField(5, "target_name", StringType(), required=True),
            NestedField(6, "target_type", StringType(), required=True),
            NestedField(7, "action_type", StringType(), required=True),
            # Local scores
            NestedField(8, "local_clarity", DoubleType(), required=True),
            NestedField(9, "local_naturalness", DoubleType(), required=True),
            NestedField(10, "local_specificity", DoubleType(), required=True),
            NestedField(11, "local_conciseness", DoubleType(), required=True),
            NestedField(12, "local_overall", DoubleType(), required=True),
            # XAI scores
            NestedField(13, "xai_intent", LongType(), required=True),
            NestedField(14, "xai_som_grounding", LongType(), required=True),
            NestedField(15, "xai_action_semantics", LongType(), required=True),
            NestedField(16, "xai_tom_trace", LongType(), required=True),
            NestedField(17, "xai_constraints", LongType(), required=True),
            NestedField(18, "xai_outcome", LongType(), required=True),
            NestedField(19, "xai_overall", DoubleType(), required=True),
            # Evidence and errors
            NestedField(20, "evidence_json", StringType(), required=True),
            NestedField(21, "errors_json", StringType(), required=True),
            NestedField(22, "calibration_delta", DoubleType(), required=True),
            # Metadata
            NestedField(23, "xai_model", StringType(), required=True),
            NestedField(24, "tokens_used", LongType(), required=True),
            NestedField(25, "evaluated_at", TimestamptzType(), required=True),
        )

        # Create namespace if needed
        try:
            self.catalog.create_namespace(self.namespace)
        except Exception:
            pass  # Namespace exists

        # Create table
        table_id = f"{self.namespace}.{self.table_name}"
        return self.catalog.create_table(
            table_id,
            schema=schema,
            location=f"s3://zndx-gaius/{self.s3_prefix}",
        )

    def store_samples(self, items: list[CalibrationItem]) -> WriteResult:
        """Store calibration samples to Iceberg.

        Args:
            items: List of CalibrationItem objects

        Returns:
            WriteResult with status and snapshot info
        """
        if not items:
            return WriteResult(success=True, items_written=0)

        # If Iceberg not available, fall back to local JSON
        if self.table is None:
            return self._store_local_fallback(items)

        try:
            import pyarrow as pa

            # Convert to PyArrow table
            records = [item.to_dict() for item in items]
            arrow_table = self._records_to_arrow(records)

            # Append to Iceberg
            self.table.append(arrow_table)

            # Get snapshot ID
            snapshot = self.table.current_snapshot()
            snapshot_id = snapshot.snapshot_id if snapshot else None

            logger.info(
                f"Stored {len(items)} calibration samples to Iceberg "
                f"(snapshot: {snapshot_id})"
            )

            return WriteResult(
                success=True,
                items_written=len(items),
                snapshot_id=snapshot_id,
                table_path=f"{self.namespace}.{self.table_name}",
            )

        except Exception as e:
            logger.error(f"Failed to store to Iceberg: {e}")
            # Fall back to local
            return self._store_local_fallback(items)

    def _records_to_arrow(self, records: list[dict]):
        """Convert records to PyArrow table."""
        import pyarrow as pa

        # Ensure timestamps are timezone-aware
        for record in records:
            if record.get("evaluated_at"):
                dt = record["evaluated_at"]
                if dt.tzinfo is None:
                    record["evaluated_at"] = dt.replace(tzinfo=timezone.utc)

        schema = pa.schema([
            pa.field("id", pa.string(), nullable=False),
            pa.field("example_id", pa.string(), nullable=False),
            pa.field("dataset_id", pa.string(), nullable=False),
            pa.field("instruction", pa.string(), nullable=False),
            pa.field("target_name", pa.string(), nullable=False),
            pa.field("target_type", pa.string(), nullable=False),
            pa.field("action_type", pa.string(), nullable=False),
            pa.field("local_clarity", pa.float64(), nullable=False),
            pa.field("local_naturalness", pa.float64(), nullable=False),
            pa.field("local_specificity", pa.float64(), nullable=False),
            pa.field("local_conciseness", pa.float64(), nullable=False),
            pa.field("local_overall", pa.float64(), nullable=False),
            pa.field("xai_intent", pa.int64(), nullable=False),
            pa.field("xai_som_grounding", pa.int64(), nullable=False),
            pa.field("xai_action_semantics", pa.int64(), nullable=False),
            pa.field("xai_tom_trace", pa.int64(), nullable=False),
            pa.field("xai_constraints", pa.int64(), nullable=False),
            pa.field("xai_outcome", pa.int64(), nullable=False),
            pa.field("xai_overall", pa.float64(), nullable=False),
            pa.field("evidence_json", pa.string(), nullable=False),
            pa.field("errors_json", pa.string(), nullable=False),
            pa.field("calibration_delta", pa.float64(), nullable=False),
            pa.field("xai_model", pa.string(), nullable=False),
            pa.field("tokens_used", pa.int64(), nullable=False),
            pa.field("evaluated_at", pa.timestamp("us", tz="UTC"), nullable=False),
        ])

        return pa.Table.from_pylist(records, schema=schema)

    def _store_local_fallback(self, items: list[CalibrationItem]) -> WriteResult:
        """Fall back to local JSON storage when Iceberg unavailable."""
        import os
        from pathlib import Path

        # Store in build/dev/datasets/{dataset_id}/hx/calibration/
        base_path = Path("build/dev/datasets") / self.dataset_id / "hx" / "calibration"
        base_path.mkdir(parents=True, exist_ok=True)

        # Write JSON file
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"calibration_{timestamp}.json"
        filepath = base_path / filename

        records = []
        for item in items:
            record = item.to_dict()
            # Convert datetime for JSON
            record["evaluated_at"] = record["evaluated_at"].isoformat()
            records.append(record)

        with open(filepath, "w") as f:
            json.dump(records, f, indent=2)

        logger.info(f"Stored {len(items)} calibration samples to {filepath}")

        return WriteResult(
            success=True,
            items_written=len(items),
            table_path=str(filepath),
        )

    def query_samples(
        self,
        target_type: Optional[str] = None,
        min_delta: Optional[float] = None,
        max_delta: Optional[float] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query calibration samples for analysis.

        Args:
            target_type: Filter by target type
            min_delta: Minimum calibration delta
            max_delta: Maximum calibration delta
            limit: Maximum results

        Returns:
            List of sample dictionaries
        """
        if self.table is None:
            return self._query_local_fallback(target_type, min_delta, max_delta, limit)

        try:
            # Build filter expression
            filters = []
            if target_type:
                filters.append(f"target_type = '{target_type}'")
            if min_delta is not None:
                filters.append(f"calibration_delta >= {min_delta}")
            if max_delta is not None:
                filters.append(f"calibration_delta <= {max_delta}")

            # Scan table
            scan = self.table.scan()
            if filters:
                scan = scan.filter(" AND ".join(filters))

            # Convert to records
            arrow_table = scan.to_arrow()
            records = arrow_table.to_pylist()[:limit]

            return records

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []

    def _query_local_fallback(
        self,
        target_type: Optional[str],
        min_delta: Optional[float],
        max_delta: Optional[float],
        limit: int,
    ) -> list[dict]:
        """Query local JSON fallback storage."""
        from pathlib import Path

        base_path = Path("build/dev/datasets") / self.dataset_id / "hx" / "calibration"
        if not base_path.exists():
            return []

        all_records = []
        for filepath in base_path.glob("calibration_*.json"):
            with open(filepath) as f:
                records = json.load(f)
                all_records.extend(records)

        # Apply filters
        filtered = []
        for record in all_records:
            if target_type and record.get("target_type") != target_type:
                continue
            if min_delta is not None and record.get("calibration_delta", 0) < min_delta:
                continue
            if max_delta is not None and record.get("calibration_delta", 0) > max_delta:
                continue
            filtered.append(record)

        return filtered[:limit]

    def get_calibration_stats(self) -> dict:
        """Get statistics about calibration samples.

        Returns:
            Dict with counts, deltas, and distribution info
        """
        samples = self.query_samples(limit=10000)

        if not samples:
            return {
                "total_samples": 0,
                "by_type": {},
                "avg_delta": 0.0,
            }

        # Count by type
        by_type = {}
        for sample in samples:
            t = sample.get("target_type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1

        # Compute delta statistics
        deltas = [s.get("calibration_delta", 0) for s in samples]
        avg_delta = sum(deltas) / len(deltas) if deltas else 0
        min_delta = min(deltas) if deltas else 0
        max_delta = max(deltas) if deltas else 0

        # XAI score distributions
        xai_scores = {
            "intent": [s.get("xai_intent", 0) for s in samples],
            "som_grounding": [s.get("xai_som_grounding", 0) for s in samples],
            "action_semantics": [s.get("xai_action_semantics", 0) for s in samples],
            "tom_trace": [s.get("xai_tom_trace", 0) for s in samples],
            "constraints": [s.get("xai_constraints", 0) for s in samples],
            "outcome": [s.get("xai_outcome", 0) for s in samples],
        }

        xai_avgs = {
            dim: sum(scores) / len(scores) if scores else 0
            for dim, scores in xai_scores.items()
        }

        return {
            "total_samples": len(samples),
            "by_type": by_type,
            "delta_stats": {
                "avg": avg_delta,
                "min": min_delta,
                "max": max_delta,
            },
            "xai_score_avgs": xai_avgs,
        }
