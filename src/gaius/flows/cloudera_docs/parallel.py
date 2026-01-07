"""Parallel PDF Processing with Preemptible GPU Workloads.

Implements multi-GPU parallel docling processing with:
- One worker per available GPU
- Checkpoint/resume for preemption support
- Engine workload integration for priority handling

Architecture:
    ┌─────────────────────────────────────────────────────────────────┐
    │  ParallelDocProcessor (coordinator)                              │
    │  - Manages checkpoint state                                      │
    │  - Handles preemption signals                                    │
    │  - Distributes work to GPU workers                               │
    └─────────────────────────────────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
    ┌─────────┐          ┌─────────┐          ┌─────────┐
    │ Worker0 │          │ Worker1 │          │ Worker2 │
    │ cuda:0  │          │ cuda:1  │          │ cuda:2  │
    └─────────┘          └─────────┘          └─────────┘

Preemption Flow:
    1. High-priority request arrives (/swarm, /thoughts)
    2. Engine signals preemption via workload queue
    3. Workers save current progress to checkpoint
    4. GPUs released for high-priority work
    5. When complete, workers resume from checkpoint
"""

from __future__ import annotations

import json
import logging
import os
import signal
import tempfile
import threading
import time
from concurrent.futures import ProcessPoolExecutor, Future, as_completed
import multiprocessing
from dataclasses import dataclass, field, asdict
from datetime import datetime
from multiprocessing import Manager, Event as MPEvent
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

from .progress import ProgressTracker, get_sync_progress, format_progress_human
from .flow import SyncResult

if TYPE_CHECKING:
    from .sources import ProductSource

logger = logging.getLogger(__name__)


@dataclass
class WorkItem:
    """A single document to process."""
    doc_path: str
    doc_content_hash: str  # For checkpoint validation
    gpu_id: int = -1  # Assigned GPU
    status: str = "pending"  # pending, processing, completed, failed
    error: str | None = None
    output_path: str | None = None


@dataclass
class CheckpointState:
    """Persistent checkpoint for resume after preemption."""
    workload_id: str
    product_name: str
    archive_hash: str
    kb_prefix: str
    version: str
    total_items: int
    completed_items: list[str] = field(default_factory=list)  # doc_paths
    failed_items: list[str] = field(default_factory=list)
    pending_items: list[str] = field(default_factory=list)
    last_checkpoint: str = ""  # ISO timestamp
    preempted: bool = False

    def save(self, checkpoint_path: Path) -> None:
        """Save checkpoint to disk."""
        self.last_checkpoint = datetime.now().isoformat()
        checkpoint_path.write_text(json.dumps(asdict(self), indent=2))
        logger.info(f"Checkpoint saved: {len(self.completed_items)}/{self.total_items} complete")

    @classmethod
    def load(cls, checkpoint_path: Path) -> "CheckpointState | None":
        """Load checkpoint from disk."""
        if not checkpoint_path.exists():
            return None
        try:
            data = json.loads(checkpoint_path.read_text())
            return cls(**data)
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}")
            return None


def _worker_process_doc(
    doc_path: str,
    doc_bytes: bytes,
    kb_prefix_path: str,
    archive_name: str,  # Name of source archive (e.g., "csa")
    archive_hash: str,
    gpu_id: int,
) -> dict[str, Any]:
    """Worker function to process a single document on specified GPU.

    Runs in a subprocess with CUDA_VISIBLE_DEVICES set.
    Archive paths have format: {product}/{version}/{topic_path}/{file}
    Output preserves this structure under current/cloudera/docs/
    """
    import io
    import os
    import re
    from pathlib import Path
    from datetime import datetime

    # Set GPU visibility BEFORE importing docling
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)

    result = {
        "doc_path": doc_path,
        "success": False,
        "output_path": None,
        "error": None,
        "gpu_id": gpu_id,
    }

    try:
        from docling.document_converter import DocumentConverter
        from docling.datamodel.base_models import InputFormat
        from docling_core.types.io import DocumentStream

        # Determine input format
        if doc_path.endswith(".pdf"):
            input_format = InputFormat.PDF
        elif doc_path.endswith(".html") or doc_path.endswith(".htm"):
            input_format = InputFormat.HTML
        else:
            result["error"] = f"Unsupported format: {doc_path}"
            return result

        # Convert
        converter = DocumentConverter(allowed_formats=[input_format])
        stream = DocumentStream(name=doc_path, stream=io.BytesIO(doc_bytes))
        conv_result = converter.convert(stream)
        markdown = conv_result.document.export_to_markdown()

        if not markdown or len(markdown) < 100:
            result["error"] = "Empty or too short content"
            return result

        # Extract title
        title = ""
        for line in markdown.split("\n"):
            if line.startswith("# "):
                title = line[2:].strip()
                break

        # Parse archive path for product/version
        parts = doc_path.split("/")
        if len(parts) >= 2:
            doc_product = parts[0]
            doc_version = parts[1]
        else:
            doc_product = "unknown"
            doc_version = "unknown"

        # Preserve archive path structure - just strip file extension
        relative_path = re.sub(r"\.(html?|pdf)$", "", doc_path) + ".md"

        kb_path = Path(kb_prefix_path) / relative_path
        kb_path.parent.mkdir(parents=True, exist_ok=True)

        # Escape title for YAML
        safe_title = (title or Path(doc_path).stem).replace('"', '\\"')
        if len(safe_title) > 100:
            safe_title = safe_title[:100] + "..."

        # Add frontmatter - use product/version from archive path
        frontmatter = f"""---
title: "{safe_title}"
source: docs.cloudera.com
product: {doc_product}
version: {doc_version}
archive: {archive_name}
source_path: {doc_path}
synced_at: {datetime.now().isoformat()}
archive_hash: {archive_hash[:16]}
---

"""
        full_content = frontmatter + markdown
        kb_path.write_text(full_content)

        result["success"] = True
        result["output_path"] = str(kb_path)

    except Exception as e:
        result["error"] = str(e)

    return result


class ParallelDocProcessor:
    """Coordinates parallel document processing across multiple GPUs.

    Features:
    - Distributes work items across available GPUs
    - Maintains checkpoint for preemption/resume
    - Integrates with engine workload queue
    - Handles graceful shutdown on signals

    Usage:
        processor = ParallelDocProcessor(
            workload_id="docs-sync-csa-20251222",
            product_name="csa",
            num_gpus=6,
        )

        # Process documents
        results = processor.process_documents(
            doc_files={"path/to/doc.pdf": b"..."},
            kb_prefix_path="/path/to/kb",
            source=source_config,
        )

        # Or resume from checkpoint
        processor.resume_from_checkpoint()
    """

    def __init__(
        self,
        workload_id: str,
        product_name: str,
        num_gpus: int = 6,
        checkpoint_dir: Path | None = None,
        preemptible: bool = True,
    ):
        self.workload_id = workload_id
        self.product_name = product_name
        self.num_gpus = num_gpus
        self.preemptible = preemptible

        # Checkpoint management
        if checkpoint_dir is None:
            checkpoint_dir = Path(tempfile.gettempdir()) / "gaius_checkpoints"
        self.checkpoint_dir = checkpoint_dir
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path = self.checkpoint_dir / f"{workload_id}.json"

        # Preemption handling
        self._preempt_event = threading.Event()
        self._shutdown_event = threading.Event()

        # Stats
        self.completed_count = 0
        self.failed_count = 0
        self.start_time: datetime | None = None

        # Progress tracker for real-time visibility
        self._progress_tracker: ProgressTracker | None = None

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful preemption."""
        def handle_preempt(signum, frame):
            logger.info(f"Received signal {signum}, initiating preemption...")
            self._preempt_event.set()

        # SIGUSR1 for preemption (from engine)
        signal.signal(signal.SIGUSR1, handle_preempt)
        # SIGTERM for graceful shutdown
        signal.signal(signal.SIGTERM, handle_preempt)

    def request_gpu_allocation(self) -> tuple[bool, list[int]]:
        """Request GPU allocation from engine.

        Returns:
            Tuple of (success, list of GPU IDs)
        """
        try:
            from .flow import get_engine_stub
            from gaius.engine.generated import gaius_service_pb2

            stub = get_engine_stub()
            if stub is None:
                logger.warning("Engine not available, using all GPUs")
                return True, list(range(self.num_gpus))

            # Request all GPUs for parallel processing
            request = gaius_service_pb2.BeginWorkloadRequest(
                workload_id=self.workload_id,
                workload_type=gaius_service_pb2.WORKLOAD_EMBEDDING,
                required_capabilities=[],
                priority="low",  # Batch job, can be preempted
                estimated_duration_s=3600,  # 1 hour estimate
                estimated_memory_mb=self.num_gpus * 16000,  # 16GB per GPU
                preemptible=self.preemptible,
            )

            response = stub.BeginWorkload(request)
            if response.success:
                logger.info(
                    f"GPU allocation granted. Evicted: {list(response.evicted_endpoints)}"
                )
                # Assume we get all requested GPUs
                return True, list(range(self.num_gpus))
            else:
                logger.warning(f"GPU allocation failed: {response.error}")
                return False, []

        except Exception as e:
            logger.warning(f"Failed to request GPU allocation: {e}")
            return True, list(range(self.num_gpus))  # Fallback to all GPUs

    def release_gpu_allocation(self) -> None:
        """Release GPU allocation back to engine."""
        try:
            from .flow import get_engine_stub
            from gaius.engine.generated import gaius_service_pb2

            stub = get_engine_stub()
            if stub is None:
                return

            request = gaius_service_pb2.CompleteWorkloadRequest(
                workload_id=self.workload_id,
            )
            stub.CompleteWorkload(request)
            logger.info(f"GPU allocation released for {self.workload_id}")

        except Exception as e:
            logger.warning(f"Failed to release GPU allocation: {e}")

    def process_documents(
        self,
        doc_files: dict[str, bytes],
        kb_prefix_path: str,
        archive_name: str,
        archive_hash: str,
        exclude_check: Callable[[str], bool] | None = None,
    ) -> dict[str, Any]:
        """Process documents in parallel across GPUs.

        Args:
            doc_files: Dict mapping doc_path -> content bytes
            kb_prefix_path: KB output directory (current/cloudera/docs/)
            archive_name: Name of source archive (e.g., "csa")
            archive_hash: Archive hash for metadata
            exclude_check: Optional function to check if path should be excluded

        Returns:
            Dict with processing results
        """
        self.start_time = datetime.now()
        self._setup_signal_handlers()

        # Filter excluded files
        if exclude_check:
            doc_files = {p: c for p, c in doc_files.items() if not exclude_check(p)}

        # Filter out files that already exist in KB (incremental sync)
        import re
        from pathlib import Path
        kb_prefix = Path(kb_prefix_path)
        already_exist = []
        for doc_path in list(doc_files.keys()):
            relative_path = re.sub(r"\.(html?|pdf)$", "", doc_path) + ".md"
            kb_path = kb_prefix / relative_path
            if kb_path.exists():
                already_exist.append(doc_path)
                del doc_files[doc_path]

        if already_exist:
            logger.info(f"Skipping {len(already_exist)} files that already exist in KB")

        # Check for existing checkpoint
        checkpoint = CheckpointState.load(self.checkpoint_path)
        if checkpoint and checkpoint.archive_hash == archive_hash:
            logger.info(
                f"Resuming from checkpoint: {len(checkpoint.completed_items)}/{checkpoint.total_items}"
            )
            pending_paths = set(checkpoint.pending_items)
            doc_files = {p: c for p, c in doc_files.items() if p in pending_paths}
        else:
            # New sync
            checkpoint = CheckpointState(
                workload_id=self.workload_id,
                product_name=self.product_name,
                archive_hash=archive_hash,
                kb_prefix=kb_prefix_path,
                version="",  # Not used anymore - version comes from archive path
                total_items=len(doc_files),
                pending_items=list(doc_files.keys()),
            )

        # Request GPU allocation
        success, gpu_ids = self.request_gpu_allocation()
        if not success:
            return {
                "success": False,
                "error": "Failed to allocate GPUs",
                "completed": 0,
                "failed": 0,
            }

        try:
            # Process in parallel
            results = self._process_parallel(
                doc_files=doc_files,
                kb_prefix_path=kb_prefix_path,
                archive_name=archive_name,
                archive_hash=archive_hash,
                gpu_ids=gpu_ids,
                checkpoint=checkpoint,
            )

            return results

        finally:
            # Always release GPUs
            self.release_gpu_allocation()

    def _process_parallel(
        self,
        doc_files: dict[str, bytes],
        kb_prefix_path: str,
        archive_name: str,
        archive_hash: str,
        gpu_ids: list[int],
        checkpoint: CheckpointState,
    ) -> dict[str, Any]:
        """Internal parallel processing with checkpointing."""

        num_workers = len(gpu_ids)
        doc_items = list(doc_files.items())

        logger.info(
            f"Starting parallel processing: {len(doc_items)} docs across {num_workers} GPUs"
        )

        completed = list(checkpoint.completed_items)
        failed = list(checkpoint.failed_items)

        # Initialize progress tracker for real-time visibility
        self._progress_tracker = ProgressTracker(
            product=self.product_name,
            workload_id=self.workload_id,
            total=checkpoint.total_items,
        )
        self._progress_tracker.start()
        # Set initial state if resuming
        if completed or failed:
            self._progress_tracker.update(
                completed=len(completed),
                failed=len(failed),
            )

        # Use ProcessPoolExecutor with 'spawn' context for CUDA compatibility
        # 'fork' (Linux default) can't re-initialize CUDA in child processes
        spawn_ctx = multiprocessing.get_context('spawn')
        with ProcessPoolExecutor(max_workers=num_workers, mp_context=spawn_ctx) as executor:
            # Submit all jobs with round-robin GPU assignment
            futures: dict[Future, str] = {}
            for i, (doc_path, doc_bytes) in enumerate(doc_items):
                gpu_id = gpu_ids[i % num_workers]
                future = executor.submit(
                    _worker_process_doc,
                    doc_path=doc_path,
                    doc_bytes=doc_bytes,
                    kb_prefix_path=kb_prefix_path,
                    archive_name=archive_name,
                    archive_hash=archive_hash,
                    gpu_id=gpu_id,
                )
                futures[future] = doc_path

            # Collect results with checkpoint saves
            checkpoint_interval = 10  # Save every 10 completed
            last_checkpoint = 0

            for future in as_completed(futures):
                if self._preempt_event.is_set():
                    logger.info("Preemption requested, saving checkpoint...")
                    # Cancel pending futures
                    for f in futures:
                        f.cancel()

                    # Save checkpoint with remaining items
                    processed = set(completed) | set(failed)
                    checkpoint.pending_items = [
                        p for p in doc_files.keys() if p not in processed
                    ]
                    checkpoint.completed_items = completed
                    checkpoint.failed_items = failed
                    checkpoint.preempted = True
                    checkpoint.save(self.checkpoint_path)

                    return {
                        "success": False,
                        "preempted": True,
                        "completed": len(completed),
                        "failed": len(failed),
                        "pending": len(checkpoint.pending_items),
                        "checkpoint_path": str(self.checkpoint_path),
                    }

                doc_path = futures[future]
                try:
                    result = future.result()
                    if result["success"]:
                        completed.append(doc_path)
                        self.completed_count += 1
                        # Update progress tracker
                        if self._progress_tracker:
                            self._progress_tracker.update(
                                completed=len(completed),
                                failed=len(failed),
                                recent_file=result.get("output_path", doc_path),
                            )
                    else:
                        failed.append(doc_path)
                        self.failed_count += 1
                        logger.warning(f"Failed {doc_path}: {result['error']}")
                        if self._progress_tracker:
                            self._progress_tracker.update(
                                completed=len(completed),
                                failed=len(failed),
                            )
                except Exception as e:
                    failed.append(doc_path)
                    self.failed_count += 1
                    logger.error(f"Worker error for {doc_path}: {e}")
                    if self._progress_tracker:
                        self._progress_tracker.update(
                            completed=len(completed),
                            failed=len(failed),
                        )

                # Periodic checkpoint
                if len(completed) - last_checkpoint >= checkpoint_interval:
                    checkpoint.completed_items = completed
                    checkpoint.failed_items = failed
                    checkpoint.pending_items = [
                        p for p in doc_files.keys()
                        if p not in set(completed) | set(failed)
                    ]
                    checkpoint.save(self.checkpoint_path)
                    last_checkpoint = len(completed)

                # Progress logging
                total = len(doc_items)
                done = len(completed) + len(failed)
                if done % 20 == 0 or done == total:
                    assert self.start_time is not None  # Set in process()
                    elapsed = (datetime.now() - self.start_time).total_seconds()
                    rate = done / elapsed if elapsed > 0 else 0
                    eta = (total - done) / rate if rate > 0 else 0
                    logger.info(
                        f"Progress: {done}/{total} ({100*done/total:.1f}%) "
                        f"Rate: {rate:.1f}/s, ETA: {eta/60:.1f}min"
                    )

        # Final checkpoint (cleanup)
        if self.checkpoint_path.exists():
            self.checkpoint_path.unlink()

        assert self.start_time is not None  # Set in process()
        duration = (datetime.now() - self.start_time).total_seconds()

        # Mark progress as complete
        if self._progress_tracker:
            self._progress_tracker.complete(success=len(failed) == 0)

        return {
            "success": len(failed) == 0,
            "completed": len(completed),
            "failed": len(failed),
            "duration_seconds": duration,
            "rate_per_second": len(completed) / duration if duration > 0 else 0,
        }

    def resume_from_checkpoint(
        self,
        doc_files: dict[str, bytes],
        kb_prefix_path: str,
        archive_name: str,
        archive_hash: str,
    ) -> dict[str, Any]:
        """Resume processing from a saved checkpoint.

        This is called after a preemption when high-priority work completes.
        """
        checkpoint = CheckpointState.load(self.checkpoint_path)
        if checkpoint is None:
            logger.warning("No checkpoint found to resume from")
            return self.process_documents(
                doc_files=doc_files,
                kb_prefix_path=kb_prefix_path,
                archive_name=archive_name,
                archive_hash=archive_hash,
            )

        if checkpoint.archive_hash != archive_hash:
            logger.warning("Archive changed since checkpoint, starting fresh")
            return self.process_documents(
                doc_files=doc_files,
                kb_prefix_path=kb_prefix_path,
                archive_name=archive_name,
                archive_hash=archive_hash,
            )

        # Filter to only pending items
        pending = set(checkpoint.pending_items)
        filtered_docs = {p: c for p, c in doc_files.items() if p in pending}

        logger.info(
            f"Resuming from checkpoint: {len(checkpoint.completed_items)} done, "
            f"{len(filtered_docs)} remaining"
        )

        # Reset preemption flag
        checkpoint.preempted = False
        self._preempt_event.clear()

        return self.process_documents(
            doc_files=filtered_docs,
            kb_prefix_path=kb_prefix_path,
            archive_name=archive_name,
            archive_hash=archive_hash,
        )


def sync_product_parallel(
    source: "ProductSource",
    kb_root: Path,
    num_gpus: int = 6,
    force: bool = False,
) -> dict[str, Any]:
    """Sync a product using parallel GPU processing.

    Drop-in replacement for sync_product() that uses parallel processing.
    Syncs ALL products in the archive, not just the specified one.

    Args:
        source: Product source configuration (used for archive URL)
        kb_root: KB root directory
        num_gpus: Number of GPUs to use
        force: Force sync even if unchanged

    Returns:
        Sync result dict
    """
    from .flow import (
        download_archive,
        extract_doc_files,
        compute_content_hash,
    )
    from .sources import SourceType

    if source.source_type != SourceType.ARCHIVE or not source.archive_url:
        return {
            "success": False,
            "error": "Only ARCHIVE sources supported",
        }

    # Download and extract - sync ALL products in archive
    logger.info(f"Downloading archive for {source.name}...")
    archive_bytes = download_archive(source.archive_url)
    archive_hash = compute_content_hash(archive_bytes)

    # Extract ALL documents (no product filter)
    doc_files = extract_doc_files(archive_bytes, product_filter=None)
    pdf_count = sum(1 for p in doc_files if p.endswith(".pdf"))

    if pdf_count == 0:
        logger.info("No PDFs found, using sequential processing")
        from .flow import sync_product
        result = sync_product(source, kb_root, force)
        # Convert SyncResult to dict for consistent return type
        return {
            "product": result.product,
            "success": result.success,
            "pages_extracted": result.pages_extracted,
            "pages_skipped": result.pages_skipped,
            "archive_hash": result.archive_hash,
            "kb_prefix": result.kb_prefix,
            "version": result.version,
            "duration_seconds": result.duration_seconds,
            "error": result.error,
        }

    logger.info(f"Found {pdf_count} PDFs, using parallel processing on {num_gpus} GPUs")

    # Setup parallel processor
    workload_id = f"docs-sync-{source.name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    processor = ParallelDocProcessor(
        workload_id=workload_id,
        product_name=source.name,
        num_gpus=num_gpus,
        preemptible=True,
    )

    # Use common KB prefix: current/cloudera/docs/
    kb_prefix_path = kb_root / "current" / "cloudera" / "docs"
    kb_prefix_path.mkdir(parents=True, exist_ok=True)

    # Process - archive paths provide the structure
    result = processor.process_documents(
        doc_files=doc_files,
        kb_prefix_path=str(kb_prefix_path),
        archive_name=source.name,
        archive_hash=archive_hash,
        exclude_check=source.should_exclude,
    )

    # Convert to SyncResult format
    return {
        "product": source.name,
        "success": result.get("success", False),
        "pages_extracted": result.get("completed", 0),
        "pages_skipped": result.get("failed", 0),
        "archive_hash": archive_hash,
        "kb_prefix": "current/cloudera/docs",
        "version": "multi",  # Multiple products/versions
        "duration_seconds": result.get("duration_seconds", 0),
        "parallel": True,
        "num_gpus": num_gpus,
        "preempted": result.get("preempted", False),
    }
