#!/usr/bin/env python3
"""Populate AGE lineage graph with Cloudera docs provenance.

This script creates lineage entries for Cloudera documentation that was
synced via the cloudera_docs ETL pipeline. It records:
- Source datasets (docs.cloudera.com archives)
- KB datasets (markdown files in current/cloudera/docs/)
- Transformation relationships (PDF -> Markdown via docling)
"""

import asyncio
import logging
import os
from pathlib import Path
from uuid import uuid4

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Products synced from Cloudera docs
PRODUCTS = [
    "csa",
    "csa-operator",
    "cdp-private-cloud-data-services",
    "cdw-runtime",
    "cloudera-manager",
    "data-catalog",
    "data-engineering",
    "data-warehouse",
    "management-console",
    "replication-manager",
]


async def populate_lineage():
    """Populate the AGE graph with Cloudera docs lineage."""
    from gaius.hx.lineage.emitter import LineageEmitter
    from gaius.hx.lineage.events import Dataset, DatasetFacets, Job, Run, RunEvent, RunState

    emitter = LineageEmitter()
    kb_root = Path(os.environ.get("GAIUS_KB_ROOT", "build/dev"))

    # Create the Job for Cloudera docs sync
    job = Job(
        namespace="cloudera.etl",
        name="cloudera_docs_sync",
    )

    for product in PRODUCTS:
        product_dir = kb_root / "current" / "cloudera" / "docs" / product
        if not product_dir.exists():
            logger.info(f"Skipping {product} - directory not found")
            continue

        # Find all markdown files for this product
        md_files = list(product_dir.rglob("*.md"))
        if not md_files:
            logger.info(f"Skipping {product} - no markdown files")
            continue

        logger.info(f"Processing {product}: {len(md_files)} files")

        # Create a Run for this product
        run = Run(run_id=uuid4())

        # Source dataset (the docs.cloudera.com archive)
        source = Dataset(
            namespace="cloudera.source",
            name=f"docs.cloudera.com/{product}",
            facets=DatasetFacets(
                documentation=f"Cloudera documentation for {product}",
                custom={
                    "_producer": "cloudera_docs_sync",
                    "source_url": f"https://docs.cloudera.com/{product}",
                },
            ),
        )

        # KB dataset (the converted markdown)
        kb_dataset = Dataset(
            namespace="gaius.kb",
            name=f"current/cloudera/docs/{product}",
            facets=DatasetFacets(
                documentation=f"Converted markdown docs for {product}",
                custom={
                    "_producer": "cloudera_docs_sync",
                    "file_count": len(md_files),
                    "files": [str(f.relative_to(kb_root)) for f in md_files[:10]],  # Sample
                },
            ),
        )

        # Emit START event
        start_event = RunEvent.start(
            job=job,
            inputs=[source],
            run=run,
        )
        await emitter.emit(start_event)

        # Emit COMPLETE event with outputs
        complete_event = RunEvent.complete(
            run=run,
            job=job,
            inputs=[source],
            outputs=[kb_dataset],
        )
        event_id = await emitter.emit(complete_event)

        logger.info(f"  Recorded lineage: {source.name} -> {kb_dataset.name} (event_id={event_id})")

    # Close the emitter
    await emitter.close()
    logger.info("Done populating Cloudera docs lineage")


if __name__ == "__main__":
    asyncio.run(populate_lineage())
