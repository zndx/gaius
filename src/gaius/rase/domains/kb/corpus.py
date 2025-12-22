"""Corpus Storage for Ontology Verbalizations.

Stores training corpora to Iceberg (Parquet) for downstream training pipelines.
Uses hx:// URI scheme for consistent addressing.

Storage Layout:
    hx://ontology.corpora - Iceberg table with training examples

Table Schema:
    - corpus_id: Unique corpus identifier
    - domain: Ontology domain (pizza, cloudera, etc.)
    - ontology_path: Source ontology path
    - input: Prompt text (class expression or task description)
    - output: Expected output (verbalization or completion)
    - class_expr: Original OWL class expression
    - created_at: Timestamp
    - content_hash: Hash of input+output for deduplication

Uses the existing HX infrastructure (Iceberg + MinIO) for:
- ACID transactions
- Schema evolution
- Efficient columnar storage (Parquet)
- Query pushdown for training data selection
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


@dataclass
class CorpusExample:
    """A single training example in the corpus."""

    input: str
    output: str
    class_expr: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(
        self,
        corpus_id: str,
        domain: str,
        ontology_path: str,
    ) -> dict[str, Any]:
        """Convert to dictionary for Iceberg append."""
        content = f"{self.input}|{self.output}"
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        return {
            "id": str(uuid.uuid4()),
            "corpus_id": corpus_id,
            "domain": domain,
            "ontology_path": ontology_path,
            "input": self.input,
            "output": self.output,
            "class_expr": self.class_expr,
            "content_hash": content_hash,
            "metadata": json.dumps(self.metadata) if self.metadata else None,
            "created_at": datetime.now(timezone.utc),
        }


@dataclass
class CorpusMetadata:
    """Metadata for a generated corpus."""

    corpus_id: str
    ontology_path: str
    domain: str
    example_count: int
    created_at: datetime
    hx_uri: str
    snapshot_id: int | None = None
    generation_params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_id": self.corpus_id,
            "ontology_path": self.ontology_path,
            "domain": self.domain,
            "example_count": self.example_count,
            "created_at": self.created_at.isoformat(),
            "hx_uri": self.hx_uri,
            "snapshot_id": self.snapshot_id,
            "generation_params": self.generation_params,
        }


@dataclass
class CorpusWriteResult:
    """Result of a corpus write operation."""

    success: bool
    items_written: int
    hx_uri: str | None = None
    manifest_path: str | None = None
    snapshot_id: int | None = None
    corpus_id: str | None = None
    errors: list[str] = field(default_factory=list)


class CorpusStorage:
    """Storage backend for ontology verbalizations using Iceberg.

    Uses Iceberg tables for training data storage, providing:
    - ACID transactions
    - Schema evolution
    - Efficient Parquet storage
    - Time travel for reproducibility
    """

    def __init__(
        self,
        kb_root: str | None = None,
        namespace: str = "ontology",
        table_name: str = "corpora",
        write_manifests: bool = True,
    ):
        """Initialize corpus storage.

        Args:
            kb_root: KB root for manifests. If None, uses GAIUS_KB_ROOT.
            namespace: Iceberg namespace.
            table_name: Table name within namespace.
            write_manifests: Whether to write KB manifest files.
        """
        self._kb_root = kb_root or os.environ.get("GAIUS_KB_ROOT", "build/dev")
        self._namespace = namespace
        self._table_name = table_name
        self._write_manifests = write_manifests
        self._catalog: Catalog | None = None
        self._table: Table | None = None
        self._lock = asyncio.Lock()

    def _get_catalog(self) -> Catalog:
        """Get or create the Iceberg catalog."""
        if self._catalog is None:
            from gaius.hx.catalog import get_catalog
            from gaius.hx.config import get_hx_config

            config = get_hx_config()
            self._catalog = get_catalog(config)
        return self._catalog

    def _get_table(self) -> Table:
        """Get or create the corpora table."""
        if self._table is None:
            self._table = self._ensure_table_exists()
        return self._table

    def _ensure_table_exists(self) -> Table:
        """Ensure the corpora table exists, create if needed."""
        import pyarrow as pa
        from pyiceberg.exceptions import NoSuchTableError

        catalog = self._get_catalog()
        full_name = f"{self._namespace}.{self._table_name}"

        try:
            return catalog.load_table(full_name)
        except NoSuchTableError:
            logger.info(f"Creating corpus table: {full_name}")

            # Create namespace if needed
            try:
                catalog.create_namespace(self._namespace)
            except Exception:
                pass  # Namespace may already exist

            # Define schema
            schema = pa.schema([
                pa.field("id", pa.string(), nullable=False),
                pa.field("corpus_id", pa.string(), nullable=False),
                pa.field("domain", pa.string(), nullable=False),
                pa.field("ontology_path", pa.string(), nullable=False),
                pa.field("input", pa.string(), nullable=False),
                pa.field("output", pa.string(), nullable=False),
                pa.field("class_expr", pa.string(), nullable=True),
                pa.field("content_hash", pa.string(), nullable=False),
                pa.field("metadata", pa.string(), nullable=True),
                pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
            ])

            return catalog.create_table(full_name, schema=schema)

    async def write_corpus(
        self,
        domain: str,
        examples: list[CorpusExample],
        ontology_path: str,
        generation_params: dict[str, Any] | None = None,
    ) -> CorpusWriteResult:
        """Write corpus to Iceberg storage.

        Args:
            domain: Domain name (e.g., 'pizza', 'cloudera')
            examples: List of training examples
            ontology_path: Path to source ontology
            generation_params: Optional generation parameters

        Returns:
            CorpusWriteResult with status and paths
        """
        if not examples:
            return CorpusWriteResult(
                success=False,
                items_written=0,
                errors=["No examples to write"],
            )

        try:
            import pyarrow as pa

            # Generate corpus ID
            corpus_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

            # Convert examples to records
            records = [
                ex.to_dict(corpus_id, domain, ontology_path)
                for ex in examples
            ]

            # Ensure timestamps are timezone-aware
            for record in records:
                if record.get("created_at"):
                    dt = record["created_at"]
                    if dt.tzinfo is None:
                        record["created_at"] = dt.replace(tzinfo=timezone.utc)

            # Convert to PyArrow table
            schema = pa.schema([
                pa.field("id", pa.string(), nullable=False),
                pa.field("corpus_id", pa.string(), nullable=False),
                pa.field("domain", pa.string(), nullable=False),
                pa.field("ontology_path", pa.string(), nullable=False),
                pa.field("input", pa.string(), nullable=False),
                pa.field("output", pa.string(), nullable=False),
                pa.field("class_expr", pa.string(), nullable=True),
                pa.field("content_hash", pa.string(), nullable=False),
                pa.field("metadata", pa.string(), nullable=True),
                pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
            ])
            arrow_table = pa.Table.from_pylist(records, schema=schema)

            # Write to Iceberg (run in thread pool to avoid blocking)
            loop = asyncio.get_event_loop()
            async with self._lock:
                await loop.run_in_executor(
                    None,
                    lambda: self._get_table().append(arrow_table),
                )

            # Get snapshot ID
            snapshot = self._get_table().current_snapshot()
            snapshot_id = snapshot.snapshot_id if snapshot else None

            hx_uri = f"hx://{self._namespace}.{self._table_name}"

            logger.info(
                f"Wrote corpus to Iceberg: {len(examples)} examples "
                f"(corpus_id={corpus_id}, domain={domain}, snapshot={snapshot_id})"
            )

            # Build metadata
            metadata = CorpusMetadata(
                corpus_id=corpus_id,
                ontology_path=ontology_path,
                domain=domain,
                example_count=len(examples),
                created_at=datetime.now(timezone.utc),
                hx_uri=hx_uri,
                snapshot_id=snapshot_id,
                generation_params=generation_params or {},
            )

            # Write KB manifest
            manifest_path = None
            if self._write_manifests:
                manifest_path = self._write_kb_manifest(domain, metadata, examples[:3])

            return CorpusWriteResult(
                success=True,
                items_written=len(examples),
                hx_uri=hx_uri,
                manifest_path=manifest_path,
                snapshot_id=snapshot_id,
                corpus_id=corpus_id,
            )

        except Exception as e:
            error_msg = f"Failed to write corpus: {e}"
            logger.error(error_msg)
            return CorpusWriteResult(
                success=False,
                items_written=0,
                errors=[error_msg],
            )

    def write_corpus_sync(
        self,
        domain: str,
        examples: list[CorpusExample],
        ontology_path: str,
        generation_params: dict[str, Any] | None = None,
    ) -> CorpusWriteResult:
        """Synchronous wrapper for write_corpus.

        For use in constraint evaluation which is synchronous.
        """
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(
            self.write_corpus(domain, examples, ontology_path, generation_params)
        )

    def _write_kb_manifest(
        self,
        domain: str,
        metadata: CorpusMetadata,
        sample_examples: list[CorpusExample],
    ) -> str:
        """Write manifest file to KB for navigation.

        Args:
            domain: Domain name
            metadata: Corpus metadata
            sample_examples: Sample of examples to include

        Returns:
            Path to manifest file (relative to KB root)
        """
        # Build sample examples table
        example_rows = []
        for i, ex in enumerate(sample_examples, 1):
            input_short = ex.input[:50].replace("|", "\\|").replace("\n", " ") + "..."
            output_short = ex.output[:50].replace("|", "\\|").replace("\n", " ") + "..."
            example_rows.append(f"| {i} | {input_short} | {output_short} |")

        examples_table = "\n".join(example_rows) if example_rows else "| - | - | - |"

        content = f"""---
corpus_id: {metadata.corpus_id}
domain: {domain}
ontology: {metadata.ontology_path}
example_count: {metadata.example_count}
created_at: {metadata.created_at.isoformat()}
snapshot_id: {metadata.snapshot_id}
hx_uri: {metadata.hx_uri}
---

# Corpus: {domain}

Generated from ontology verbalization for training.

## Statistics

| Metric | Value |
|--------|-------|
| Examples | {metadata.example_count} |
| Ontology | {metadata.ontology_path} |
| Snapshot | {metadata.snapshot_id} |
| Generated | {metadata.created_at.strftime('%Y-%m-%d %H:%M:%S')} |

## Storage

Corpus stored in Iceberg (Parquet) at:
- **HX URI**: `{metadata.hx_uri}`
- **Corpus ID**: `{metadata.corpus_id}`

### Query

```sql
SELECT * FROM {self._namespace}.{self._table_name}
WHERE corpus_id = '{metadata.corpus_id}'
ORDER BY created_at
```

## Sample Examples

| # | Input | Output |
|---|-------|--------|
{examples_table}

## Usage

```python
from gaius.rase.domains.kb.corpus import CorpusStorage

storage = CorpusStorage()
examples = storage.read_corpus("{domain}")
print(f"Loaded {{len(examples)}} examples")
```
"""

        # Write to KB filesystem
        manifest_dir = Path(self._kb_root) / "current/ontology" / domain
        manifest_dir.mkdir(parents=True, exist_ok=True)

        manifest_path = manifest_dir / "corpus_manifest.md"
        manifest_path.write_text(content)

        rel_path = str(manifest_path.relative_to(self._kb_root))
        logger.debug(f"Wrote KB manifest: {rel_path}")

        return rel_path

    def read_corpus(
        self,
        domain: str | None = None,
        corpus_id: str | None = None,
        limit: int | None = None,
    ) -> list[CorpusExample]:
        """Read corpus from Iceberg storage.

        Args:
            domain: Filter by domain name
            corpus_id: Filter by corpus ID
            limit: Maximum examples to return

        Returns:
            List of CorpusExample objects
        """
        try:
            table = self._get_table()

            # Build filter expression
            filters = []
            if domain:
                filters.append(f"domain = '{domain}'")
            if corpus_id:
                filters.append(f"corpus_id = '{corpus_id}'")

            # Scan table
            scan = table.scan()
            if filters:
                # PyIceberg filter syntax
                from pyiceberg.expressions import EqualTo, And

                filter_expr = None
                if domain:
                    filter_expr = EqualTo("domain", domain)
                if corpus_id:
                    corpus_filter = EqualTo("corpus_id", corpus_id)
                    filter_expr = And(filter_expr, corpus_filter) if filter_expr else corpus_filter

                if filter_expr:
                    scan = table.scan(row_filter=filter_expr)

            # Convert to pandas for easier processing
            df = scan.to_pandas()

            if limit:
                df = df.head(limit)

            examples = []
            for _, row in df.iterrows():
                metadata = {}
                if row.get("metadata"):
                    try:
                        metadata = json.loads(row["metadata"])
                    except Exception:
                        pass

                examples.append(CorpusExample(
                    input=row["input"],
                    output=row["output"],
                    class_expr=row.get("class_expr", ""),
                    metadata=metadata,
                ))

            return examples

        except Exception as e:
            logger.error(f"Failed to read corpus: {e}")
            return []

    def corpus_exists(self, domain: str) -> bool:
        """Check if corpus exists for domain.

        Args:
            domain: Domain name

        Returns:
            True if corpus exists with examples
        """
        try:
            from pyiceberg.expressions import EqualTo

            table = self._get_table()
            scan = table.scan(row_filter=EqualTo("domain", domain))

            # Just check if any rows exist
            df = scan.to_pandas()
            return len(df) > 0

        except Exception:
            return False

    def get_corpus_stats(self, domain: str | None = None) -> dict[str, Any]:
        """Get corpus statistics.

        Args:
            domain: Optional domain filter

        Returns:
            Statistics dictionary
        """
        try:
            table = self._get_table()

            if domain:
                from pyiceberg.expressions import EqualTo
                scan = table.scan(row_filter=EqualTo("domain", domain))
            else:
                scan = table.scan()

            df = scan.to_pandas()

            return {
                "total_examples": len(df),
                "domains": df["domain"].unique().tolist() if len(df) > 0 else [],
                "corpus_ids": df["corpus_id"].unique().tolist() if len(df) > 0 else [],
            }

        except Exception as e:
            logger.error(f"Failed to get corpus stats: {e}")
            return {"error": str(e)}


# Module-level singleton for convenient access
_corpus_storage: CorpusStorage | None = None


def get_corpus_storage(kb_root: str | None = None) -> CorpusStorage:
    """Get or create the corpus storage singleton.

    Args:
        kb_root: Optional KB root override

    Returns:
        CorpusStorage instance
    """
    global _corpus_storage
    if _corpus_storage is None or (kb_root and _corpus_storage._kb_root != kb_root):
        _corpus_storage = CorpusStorage(kb_root=kb_root)
    return _corpus_storage


def load_training_examples(
    domain: str | None = None,
    limit: int | None = None,
    kb_root: str | None = None,
) -> list[dict[str, Any]]:
    """Load training examples for evolution daemon.

    Convenience function for the evolution service to load examples
    from the Iceberg corpus storage.

    Args:
        domain: Filter by domain (e.g., 'pizza', 'gaius')
        limit: Maximum examples to return
        kb_root: KB root path

    Returns:
        List of training examples in evolution format:
        [{"input_prompt": ..., "expected_output": ..., "context": ...}]
    """
    storage = get_corpus_storage(kb_root=kb_root)
    corpus_examples = storage.read_corpus(domain=domain, limit=limit)

    training_examples = []
    for ex in corpus_examples:
        training_examples.append({
            "input_prompt": ex.input,
            "expected_output": ex.output,
            "context": {
                "class_expr": ex.class_expr,
                "domain": domain or "unknown",
                **ex.metadata,
            },
        })

    return training_examples


async def load_training_examples_async(
    domain: str | None = None,
    limit: int | None = None,
    kb_root: str | None = None,
) -> list[dict[str, Any]]:
    """Async version of load_training_examples.

    For use in async contexts like the evolution service.
    """
    import asyncio

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: load_training_examples(domain, limit, kb_root)
    )


__all__ = [
    "CorpusExample",
    "CorpusMetadata",
    "CorpusWriteResult",
    "CorpusStorage",
    "get_corpus_storage",
    "load_training_examples",
    "load_training_examples_async",
]
