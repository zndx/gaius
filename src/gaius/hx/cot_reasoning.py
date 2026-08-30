"""HX data product: chain-of-thought reasoning traces — ``hx.cot_reasoning``.

Deep reasoning (optillm ``cot_reflection`` on thinking) is a PRIMARY deliverable of
the content-production flows, not scaffolding: the flow's decision (e.g. which
article to advance) is the crucible in which an accumulating thinking corpus is
refined. Every run's trace is retained here with its flow/step context so the
corpus grows with history.

One physical Iceberg table holds every flow's reasoning; per-task federated
products (e.g. ``gaius.curation.cot_reasoning``, see
``flows/article_curation/publish.py``) slice it by ``flow_name`` / ``step_name`` /
``subject``. The product path ``gaius-content-curation/select_article/hx/cot_reasoning``
decomposes as subject (article slug) / step / table.

Lands in the Signals-owned Polaris REST catalog (``signals`` @ :8181, warehouse
``s3://signals-dataproducts/iceberg``) — the same catalog Signals Impala reads — so
any signals-protocol federated engine can query it, with full Iceberg snapshot
history, the moment it exists. Guru: #HX.00000003.COTWRITE
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyiceberg.catalog import Catalog
    from pyiceberg.table import Table

logger = logging.getLogger(__name__)

NAMESPACE = "hx"
TABLE_NAME = "cot_reasoning"
TABLE_IDENTIFIER = f"{NAMESPACE}.{TABLE_NAME}"
GURU_COTWRITE = "#HX.00000003.COTWRITE"

# Federated product id for the article-curation slice ({peer}.{domain}.{name}).
CURATION_PRODUCT_ID = "gaius.curation.cot_reasoning"


def get_cot_reasoning_schema():
    from pyiceberg.schema import Schema
    from pyiceberg.types import (
        DoubleType,
        LongType,
        NestedField,
        StringType,
        TimestamptzType,
    )

    return Schema(
        # Identity
        NestedField(1, "id", StringType(), required=True, doc="UUID of the reasoning record"),
        NestedField(2, "product_id", StringType(), required=True, doc="Federated product id, e.g. gaius.curation.cot_reasoning"),
        # Flow / step context (the 'with the flow-specific outputs' scoping)
        NestedField(3, "flow_name", StringType(), required=True, doc="Metaflow flow name (partition), e.g. ArticleCurationFlow"),
        NestedField(4, "step_name", StringType(), required=True, doc="Flow step that produced the reasoning, e.g. select_article"),
        NestedField(5, "run_id", StringType(), required=True, doc="Metaflow run id — one immutable version per run"),
        NestedField(6, "pathspec", StringType(), required=False, doc="Metaflow pathspec {flow}/{run_id}/{step}"),
        NestedField(7, "subject", StringType(), required=True, doc="Unit of work reasoned about, e.g. the selected article slug"),
        # The reasoning
        NestedField(8, "technique", StringType(), required=True, doc="optillm technique, e.g. cot_reflection"),
        NestedField(9, "model_name", StringType(), required=True, doc="Model that produced the reasoning"),
        NestedField(10, "prompt", StringType(), required=True, doc="Full prompt (task + candidates) the reasoning answered"),
        NestedField(11, "reasoning_trace", StringType(), required=True, doc="Chain-of-thought / reflection trace — the deliverable"),
        NestedField(12, "raw_response", StringType(), required=False, doc="Untruncated model output (trace + answer)"),
        NestedField(13, "output", StringType(), required=True, doc="Structured decision the flow parsed (JSON)"),
        NestedField(14, "decision", StringType(), required=False, doc="Primary decision value, e.g. selected_slug"),
        NestedField(15, "confidence", DoubleType(), required=False, doc="Model-reported confidence 0.0-1.0"),
        # Cost / timing
        NestedField(16, "input_tokens", LongType(), required=False, doc="Prompt tokens"),
        NestedField(17, "output_tokens", LongType(), required=False, doc="Generated tokens (reasoning + answer)"),
        NestedField(18, "latency_ms", LongType(), required=False, doc="End-to-end latency"),
        NestedField(19, "generated_at", TimestamptzType(), required=True, doc="When the reasoning was produced"),
        # YuniKorn admission provenance
        NestedField(20, "yk_app_id", StringType(), required=False, doc="YuniKorn application id of the admitted flow"),
        NestedField(21, "yk_queue", StringType(), required=False, doc="YuniKorn leaf the flow ran on"),
    )


def get_cot_reasoning_partition_spec():
    """Partitions by: flow_name (identity), generated_at (monthly)."""
    from pyiceberg.partitioning import PartitionField, PartitionSpec
    from pyiceberg.transforms import IdentityTransform, MonthTransform

    return PartitionSpec(
        PartitionField(source_id=3, field_id=1000, transform=IdentityTransform(), name="flow_part"),
        PartitionField(source_id=19, field_id=1001, transform=MonthTransform(), name="generation_month"),
    )


def get_cot_reasoning_sort_order():
    from pyiceberg.table.sorting import SortDirection, SortField, SortOrder

    return SortOrder(SortField(source_id=19, direction=SortDirection.DESC))


def create_cot_reasoning_table(
    catalog: "Catalog",
    namespace: str = NAMESPACE,
    table_name: str = TABLE_NAME,
    if_not_exists: bool = True,
) -> "Table":
    from pyiceberg.exceptions import NoSuchTableError, TableAlreadyExistsError

    table_id = f"{namespace}.{table_name}"
    try:
        if if_not_exists:
            try:
                return catalog.load_table(table_id)
            except NoSuchTableError:
                pass
        logger.info(f"Creating Iceberg table: {table_id}")
        table = catalog.create_table(
            identifier=table_id,
            schema=get_cot_reasoning_schema(),
            partition_spec=get_cot_reasoning_partition_spec(),
            sort_order=get_cot_reasoning_sort_order(),
            properties={
                "write.parquet.compression-codec": "zstd",
                "write.parquet.compression-level": "3",
                "write.metadata.delete-after-commit.enabled": "true",
                "write.metadata.previous-versions-max": "10",
            },
        )
        logger.info(f"Created Iceberg table: {table_id}")
        return table
    except TableAlreadyExistsError:
        if if_not_exists:
            return catalog.load_table(table_id)
        raise


def evolve_cot_reasoning_schema(table: "Table") -> bool:
    """Add any columns the current schema declares that the table lacks."""
    current = {f.name for f in table.schema().fields}
    missing = [f for f in get_cot_reasoning_schema().fields if f.name not in current]
    if not missing:
        return False
    with table.update_schema() as update:
        for field in missing:
            update.add_column(field.name, field.field_type, doc=field.doc)
    logger.info(f"Evolved {TABLE_IDENTIFIER}: added {[f.name for f in missing]}")
    return True


def get_cot_reasoning_table(
    catalog: "Catalog",
    namespace: str = NAMESPACE,
    table_name: str = TABLE_NAME,
) -> "Table":
    """Get the table, creating if necessary; evolves the schema."""
    table = create_cot_reasoning_table(catalog, namespace, table_name, if_not_exists=True)
    evolve_cot_reasoning_schema(table)
    return table


@dataclass(frozen=True)
class CotRecord:
    """What a flow retains after landing one reasoning trace."""

    id: str
    table_identifier: str
    location: str
    snapshot_id: int | None
    generated_at: str


def store_cot_reasoning(
    *,
    flow_name: str,
    step_name: str,
    run_id: str,
    subject: str,
    technique: str,
    model_name: str,
    prompt: str,
    reasoning_trace: str,
    output: str,
    pathspec: str = "",
    raw_response: str = "",
    decision: str = "",
    confidence: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    latency_ms: int | None = None,
    yk_app_id: str = "",
    yk_queue: str = "",
    product_id: str = CURATION_PRODUCT_ID,
) -> CotRecord:
    """Append one reasoning trace to ``hx.cot_reasoning``.

    FAIL-FAST: the trace is the deliverable; a lost trace is a failed run.
    """
    import pyarrow as pa

    from gaius.hx.catalog import get_catalog

    try:
        catalog = get_catalog()
        table = get_cot_reasoning_table(catalog)
        now = datetime.now(timezone.utc)
        record_id = str(uuid.uuid4())
        arrow_schema = pa.schema(
            [
                pa.field("id", pa.string(), nullable=False),
                pa.field("product_id", pa.string(), nullable=False),
                pa.field("flow_name", pa.string(), nullable=False),
                pa.field("step_name", pa.string(), nullable=False),
                pa.field("run_id", pa.string(), nullable=False),
                pa.field("pathspec", pa.string(), nullable=True),
                pa.field("subject", pa.string(), nullable=False),
                pa.field("technique", pa.string(), nullable=False),
                pa.field("model_name", pa.string(), nullable=False),
                pa.field("prompt", pa.string(), nullable=False),
                pa.field("reasoning_trace", pa.string(), nullable=False),
                pa.field("raw_response", pa.string(), nullable=True),
                pa.field("output", pa.string(), nullable=False),
                pa.field("decision", pa.string(), nullable=True),
                pa.field("confidence", pa.float64(), nullable=True),
                pa.field("input_tokens", pa.int64(), nullable=True),
                pa.field("output_tokens", pa.int64(), nullable=True),
                pa.field("latency_ms", pa.int64(), nullable=True),
                pa.field("generated_at", pa.timestamp("us", tz="UTC"), nullable=False),
                pa.field("yk_app_id", pa.string(), nullable=True),
                pa.field("yk_queue", pa.string(), nullable=True),
            ]
        )
        record = pa.table(
            {
                "id": [record_id],
                "product_id": [product_id],
                "flow_name": [flow_name],
                "step_name": [step_name],
                "run_id": [run_id],
                "pathspec": [pathspec or None],
                "subject": [subject],
                "technique": [technique],
                "model_name": [model_name],
                "prompt": [prompt],
                "reasoning_trace": [reasoning_trace or ""],
                "raw_response": [raw_response or None],
                "output": [output],
                "decision": [decision or None],
                "confidence": [confidence],
                "input_tokens": [input_tokens],
                "output_tokens": [output_tokens],
                "latency_ms": [latency_ms],
                "generated_at": [now],
                "yk_app_id": [yk_app_id or None],
                "yk_queue": [yk_queue or None],
            },
            schema=arrow_schema,
        )
        table.append(record)
        table.refresh()
        snap = table.current_snapshot()
        rec = CotRecord(
            id=record_id,
            table_identifier=TABLE_IDENTIFIER,
            location=str(table.location()),
            snapshot_id=int(snap.snapshot_id) if snap is not None else None,
            generated_at=now.isoformat(),
        )
        logger.info(
            f"HX {TABLE_IDENTIFIER}: retained {flow_name}/{step_name} run={run_id} "
            f"subject={subject} id={record_id} snapshot={rec.snapshot_id}"
        )
        return rec
    except Exception as e:  # noqa: BLE001 — re-raise with a guru, never swallow
        raise RuntimeError(
            f"{GURU_COTWRITE} could not retain the reasoning trace in "
            f"{TABLE_IDENTIFIER} ({flow_name}/{step_name} run={run_id}): {e}\n"
            "  The trace is a primary deliverable — this run is not complete without it.\n"
            "  Check: sudo systemctl status signals-polaris.service (Polaris :8181) and "
            "RustFS :9010 credentials (RUSTFS_ACCESS_KEY/RUSTFS_SECRET_KEY)"
        ) from e
