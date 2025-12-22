"""ClouderaDocsFlow - Sync Cloudera documentation to KB.

Downloads ZIP archives from docs.cloudera.com, extracts HTML pages,
converts to markdown using docling, and saves to KB with full lineage.

Pipeline steps:
1. Check for archive changes (via HTTP HEAD + Last-Modified)
2. Download ZIP archive if changed
3. Extract HTML files from archive
4. Convert HTML to markdown using docling
5. Save to KB with version metadata
6. Update doc_archives table with sync status

Usage:
    # Sync specific product
    uv run gaius-cli --cmd "/docs-sync csa"

    # Sync all products
    uv run gaius-cli --cmd "/docs-sync"

    # Check sync status
    uv run gaius-cli --cmd "/docs-sync status"
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from contextlib import nullcontext
from dataclasses import dataclass, field

import httpx

from .sources import ProductSource, SourceType, get_source, list_sources
from .progress import ProgressTracker

logger = logging.getLogger(__name__)

# Engine gRPC client for GPU orchestration
_engine_client = None


def get_engine_stub():
    """Get engine gRPC stub for workload management.

    Returns the GaiusServiceStub for BeginWorkload/CompleteWorkload calls.
    Uses engine address from environment (GAIUS_ENGINE_HOST:GAIUS_ENGINE_PORT).
    """
    global _engine_client
    if _engine_client is None:
        try:
            import grpc
            from gaius.engine.generated import gaius_service_pb2_grpc

            host = os.environ.get("GAIUS_ENGINE_HOST", "localhost")
            port = os.environ.get("GAIUS_ENGINE_PORT", "50051")
            channel = grpc.insecure_channel(f"{host}:{port}")
            _engine_client = gaius_service_pb2_grpc.GaiusServiceStub(channel)
            logger.info(f"Connected to engine at {host}:{port}")
        except Exception as e:
            logger.warning(f"Could not connect to engine: {e}")
            _engine_client = None
    return _engine_client


class DoclingWorkloadContext:
    """Context manager for GPU workload management during PDF processing.

    Requests GPU resources from the engine before starting docling processing,
    and releases them when done. If engine is unavailable, falls back to
    direct processing (which may fail with OOM if vLLM is using GPUs).

    Usage:
        async with DoclingWorkloadContext(product_name, num_pdfs) as ctx:
            if ctx.success:
                # Process PDFs with docling
                pass
            else:
                # Engine unavailable, try anyway or skip
                pass
    """

    def __init__(self, product_name: str, num_docs: int):
        self.product_name = product_name
        self.num_docs = num_docs
        self.workload_id = f"docs-sync-{product_name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        self.success = False
        self.evicted_endpoints: list[str] = []
        self.restore_plan: list[str] = []

    def __enter__(self):
        stub = get_engine_stub()
        if stub is None:
            logger.warning(
                "Engine not available. PDF processing may fail if GPU memory "
                "is in use by vLLM endpoints."
            )
            return self

        try:
            from gaius.engine.generated import gaius_service_pb2

            # Docling PDF processing needs ~16GB GPU memory
            # Estimate 30s per PDF for duration planning
            estimated_duration = max(60, self.num_docs * 30)

            request = gaius_service_pb2.BeginWorkloadRequest(
                workload_id=self.workload_id,
                workload_type=gaius_service_pb2.WORKLOAD_EMBEDDING,
                required_capabilities=[],  # No specific LLM capability needed
                priority="normal",
                estimated_duration_s=estimated_duration,
                estimated_memory_mb=16000,  # docling needs ~16GB
                preemptible=False,  # Don't preempt mid-sync
            )

            response = stub.BeginWorkload(request)
            if response.success:
                self.success = True
                self.evicted_endpoints = list(response.evicted_endpoints)
                self.restore_plan = list(response.restore_plan)
                logger.info(
                    f"Workload {self.workload_id} started. "
                    f"Evicted: {self.evicted_endpoints}, "
                    f"Restore: {self.restore_plan}"
                )
            else:
                logger.warning(
                    f"Could not allocate GPU resources: {response.error}. "
                    f"Proceeding anyway (may OOM)."
                )
        except Exception as e:
            logger.warning(f"Failed to begin workload: {e}")

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self.success:
            return

        stub = get_engine_stub()
        if stub is None:
            return

        try:
            from gaius.engine.generated import gaius_service_pb2

            request = gaius_service_pb2.CompleteWorkloadRequest(
                workload_id=self.workload_id,
            )
            stub.CompleteWorkload(request)
            logger.info(
                f"Workload {self.workload_id} completed. "
                f"Restoring endpoints: {self.restore_plan}"
            )
        except Exception as e:
            logger.warning(f"Failed to complete workload: {e}")


@dataclass
class SyncResult:
    """Result of a documentation sync operation."""
    product: str
    success: bool
    pages_extracted: int = 0
    pages_skipped: int = 0
    archive_hash: str = ""
    kb_prefix: str = ""
    version: str = ""
    error: str | None = None
    duration_seconds: float = 0.0


@dataclass
class PageResult:
    """Result of extracting a single page."""
    source_path: str
    kb_path: str
    title: str
    markdown_size: int
    success: bool
    error: str | None = None


def compute_content_hash(content: bytes) -> str:
    """Compute SHA-256 hash of content."""
    return hashlib.sha256(content).hexdigest()


def get_archive_last_modified(url: str, timeout: float = 30.0) -> str | None:
    """Get Last-Modified header from archive URL.

    Returns ISO timestamp string or None if not available.
    """
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.head(url, follow_redirects=True)
            if response.status_code == 200:
                last_modified = response.headers.get("Last-Modified")
                if last_modified:
                    # Parse RFC 2822 date
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(last_modified)
                    return dt.isoformat()
    except Exception as e:
        logger.warning(f"Failed to get Last-Modified for {url}: {e}")
    return None


def get_latest_version_from_docs(product: str, timeout: float = 30.0) -> str | None:
    """Get latest version by scraping the docs.cloudera.com /latest/ page.

    Cloudera docs have a breadcrumb with class "bread-version" that shows
    the current version. This avoids needing to download the archive to
    detect version changes.

    Args:
        product: Product name (e.g., "csa", "csa-operator")
        timeout: Request timeout

    Returns:
        Version string (e.g., "1.15.1") or None if not detected
    """
    url = f"https://docs.cloudera.com/{product}/latest/"
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url, follow_redirects=True)
            if response.status_code == 200:
                # Look for <span class="bread-version">X.Y.Z</span>
                match = re.search(
                    r'class="bread-version"[^>]*>([0-9]+\.[0-9]+(?:\.[0-9]+)?)',
                    response.text
                )
                if match:
                    version = match.group(1)
                    logger.info(f"Detected latest {product} version: {version}")
                    return version
    except Exception as e:
        logger.warning(f"Failed to get latest version for {product}: {e}")
    return None


def check_version_changed(source: ProductSource, timeout: float = 30.0) -> tuple[bool, str | None]:
    """Check if a product has a new version available.

    Uses the /latest/ page to detect version changes without downloading.

    Args:
        source: Product source configuration
        timeout: Request timeout

    Returns:
        Tuple of (has_changed, latest_version)
    """
    latest = get_latest_version_from_docs(source.name, timeout)
    if latest is None:
        logger.warning(f"Could not detect latest version for {source.name}")
        return False, None

    if latest != source.version:
        logger.info(
            f"Version change detected for {source.name}: "
            f"{source.version} -> {latest}"
        )
        return True, latest

    logger.info(f"{source.name} is at latest version: {latest}")
    return False, latest


def download_archive(url: str, timeout: float = 600.0) -> bytes:
    """Download ZIP archive from URL.

    Args:
        url: URL to download
        timeout: Request timeout in seconds

    Returns:
        Archive content as bytes
    """
    logger.info(f"Downloading archive from {url}...")

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()

    size_mb = len(response.content) / (1024 * 1024)
    logger.info(f"Downloaded {size_mb:.1f} MB")

    return response.content


def extract_doc_files(
    archive_bytes: bytes,
    product_filter: str | None = None,
) -> dict[str, bytes]:
    """Extract HTML or PDF files from ZIP archive.

    Args:
        archive_bytes: ZIP archive content
        product_filter: If set, only include files whose path starts with this product name.
                        Archive paths typically have format: {product}/{version}/{topic}/{file}
                        e.g., "csa" would match "csa/1.15.1/..." but not "csa-operator/..."

    Returns:
        Dict mapping relative path to file content
    """
    doc_files: dict[str, bytes] = {}

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
        for name in zf.namelist():
            # Filter by product prefix if specified
            if product_filter:
                # Match exact product prefix (csa/ not csa-operator/)
                if not name.startswith(f"{product_filter}/"):
                    continue

            # Process HTML files
            if name.endswith(".html") or name.endswith(".htm"):
                # Skip index/nav files that are mostly navigation
                if any(skip in name.lower() for skip in ["_nav", "_toc", "sidebar"]):
                    continue
                try:
                    doc_files[name] = zf.read(name)
                except Exception as e:
                    logger.warning(f"Failed to read {name}: {e}")
            # Process PDF files
            elif name.endswith(".pdf"):
                try:
                    doc_files[name] = zf.read(name)
                except Exception as e:
                    logger.warning(f"Failed to read {name}: {e}")

    logger.info(f"Extracted {len(doc_files)} document files from archive (filter={product_filter})")
    return doc_files


def convert_doc_to_markdown(
    content: bytes,
    source_path: str,
) -> tuple[str, str]:
    """Convert HTML or PDF content to markdown using docling.

    Args:
        content: Raw document bytes (HTML or PDF)
        source_path: Source file path (for error messages and format detection)

    Returns:
        Tuple of (markdown_content, title)
    """
    from docling.document_converter import DocumentConverter
    from docling.datamodel.base_models import InputFormat
    from docling_core.types.io import DocumentStream

    # Determine input format
    if source_path.endswith(".pdf"):
        input_format = InputFormat.PDF
    elif source_path.endswith(".html") or source_path.endswith(".htm"):
        input_format = InputFormat.HTML
    else:
        raise ValueError(f"Unsupported file format: {source_path}")

    # Create converter
    converter = DocumentConverter(allowed_formats=[input_format])

    # Create document stream from bytes
    stream = DocumentStream(name=source_path, stream=io.BytesIO(content))

    # Convert
    result = converter.convert(stream)
    markdown = result.document.export_to_markdown()

    # Extract title from first heading
    title = ""
    for line in markdown.split("\n"):
        if line.startswith("# "):
            title = line[2:].strip()
            break

    return markdown, title


def sanitize_path(path: str) -> str:
    """Sanitize path for KB storage."""
    # Remove leading slashes and normalize
    path = path.lstrip("/")
    # Replace problematic characters
    path = re.sub(r"[^\w\-_./]", "_", path)
    # Collapse multiple underscores
    path = re.sub(r"_+", "_", path)
    return path


def normalize_archive_path(archive_path: str) -> str:
    """Normalize archive path for KB storage.

    Preserves the archive structure: {product}/{version}/{topic_path}/{file}
    This reflects what Cloudera actually provides and makes provenance clear.

    Examples:
        normalize_archive_path("csa/1.15.1/how-to-flink/cdf-datahub-how-to-flink.pdf")
        -> "csa/1.15.1/how-to-flink/cdf-datahub-how-to-flink"

        normalize_archive_path("csa-operator/1.2/installation/csa-op-install.pdf")
        -> "csa-operator/1.2/installation/csa-op-install"

    Args:
        archive_path: Full path from archive

    Returns:
        Normalized path with extension stripped
    """
    # Remove file extension
    path = re.sub(r"\.(html?|pdf)$", "", archive_path)
    return path


def parse_archive_path(archive_path: str) -> tuple[str, str, str]:
    """Parse archive path into components.

    Archive paths have format: {product}/{version}/{topic_path}/{file}

    Examples:
        parse_archive_path("csa/1.15.1/how-to-flink/cdf-datahub-how-to-flink.pdf")
        -> ("csa", "1.15.1", "how-to-flink/cdf-datahub-how-to-flink.pdf")

    Args:
        archive_path: Full path from archive

    Returns:
        Tuple of (product, version, remainder)
    """
    parts = archive_path.split("/")
    if len(parts) < 3:
        return ("unknown", "unknown", archive_path)

    product = parts[0]
    version = parts[1]
    remainder = "/".join(parts[2:])
    return (product, version, remainder)


def sync_product(
    source: ProductSource,
    kb_root: Path,
    force: bool = False,
) -> SyncResult:
    """Sync a single product's documentation.

    Args:
        source: Product source configuration
        kb_root: KB root directory
        force: Force sync even if archive unchanged

    Returns:
        SyncResult with sync outcome
    """
    start_time = datetime.now()
    result = SyncResult(
        product=source.name,
        success=False,
        kb_prefix=source.kb_prefix,
        version=source.version,
    )

    try:
        if source.source_type != SourceType.ARCHIVE:
            result.error = f"Only ARCHIVE source type supported, got {source.source_type}"
            return result

        if not source.archive_url:
            result.error = "No archive_url configured"
            return result

        # Check for changes via Last-Modified
        last_modified = get_archive_last_modified(source.archive_url)
        logger.info(f"Archive last modified: {last_modified}")

        # Download archive
        archive_bytes = download_archive(source.archive_url)
        result.archive_hash = compute_content_hash(archive_bytes)

        # Extract document files (HTML or PDF)
        # Sync ALL products in the archive - Cloudera archives contain multiple products
        # e.g., CSA archive has: csa/, csa-operator/, cfm/, cdp-private-cloud-*, etc.
        doc_files = extract_doc_files(archive_bytes, product_filter=None)

        # Check for PDF files that need GPU
        has_pdfs = any(p.endswith(".pdf") for p in doc_files)

        # Create KB directory - use common prefix, archive paths provide structure
        # Result: current/cloudera/docs/{product}/{version}/{topic}/{file}.md
        kb_prefix_path = kb_root / "current" / "cloudera" / "docs"
        kb_prefix_path.mkdir(parents=True, exist_ok=True)

        # Convert each document file
        # Use workload context for GPU management if PDFs present
        pages_extracted = 0
        pages_skipped = 0

        if has_pdfs:
            logger.info(
                f"Archive contains {sum(1 for p in doc_files if p.endswith('.pdf'))} PDFs. "
                "Requesting GPU resources via engine..."
            )

        # Initialize progress tracker for real-time visibility
        workload_id = f"docs-sync-{source.name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        progress_tracker = ProgressTracker(
            product=source.name,
            workload_id=workload_id,
            total=len(doc_files),
        )
        progress_tracker.start()

        with DoclingWorkloadContext(source.name, len(doc_files)) if has_pdfs else nullcontext():
            for doc_path, doc_content in doc_files.items():
                try:
                    # Skip excluded patterns
                    if source.should_exclude(doc_path):
                        pages_skipped += 1
                        continue

                    # Convert to markdown
                    markdown, title = convert_doc_to_markdown(doc_content, doc_path)

                    if not markdown or len(markdown) < 100:
                        pages_skipped += 1
                        continue

                    # Generate KB path - preserve archive structure
                    # e.g., csa/1.15.1/how-to-flink/cdf-datahub-how-to-flink.pdf
                    #    -> current/cloudera/docs/csa/1.15.1/how-to-flink/cdf-datahub-how-to-flink.md
                    relative_path = normalize_archive_path(doc_path) + ".md"
                    doc_product, doc_version, _ = parse_archive_path(doc_path)

                    kb_path = kb_prefix_path / relative_path
                    kb_path.parent.mkdir(parents=True, exist_ok=True)

                    # Escape title for YAML (handle quotes and special chars)
                    safe_title = (title or Path(doc_path).stem).replace('"', '\\"')
                    if len(safe_title) > 100:
                        safe_title = safe_title[:100] + "..."

                    # Add frontmatter - use product/version from archive path
                    frontmatter = f"""---
title: "{safe_title}"
source: docs.cloudera.com
product: {doc_product}
version: {doc_version}
archive: {source.name}
source_path: {doc_path}
synced_at: {datetime.now().isoformat()}
archive_hash: {result.archive_hash[:16]}
---

"""
                    full_content = frontmatter + markdown

                    # Write to KB
                    kb_path.write_text(full_content)
                    pages_extracted += 1

                    # Update progress tracker
                    progress_tracker.update(
                        completed=pages_extracted,
                        failed=pages_skipped,
                        recent_file=str(kb_path),
                    )

                    if pages_extracted % 50 == 0:
                        logger.info(f"Extracted {pages_extracted} pages...")

                except Exception as e:
                    logger.warning(f"Failed to process {doc_path}: {e}")
                    pages_skipped += 1
                    progress_tracker.update(
                        completed=pages_extracted,
                        failed=pages_skipped,
                    )

        result.pages_extracted = pages_extracted
        result.pages_skipped = pages_skipped
        result.success = True

        duration = (datetime.now() - start_time).total_seconds()
        result.duration_seconds = duration

        # Mark progress as complete
        progress_tracker.complete(success=True)

        logger.info(
            f"Sync complete: {pages_extracted} pages extracted, "
            f"{pages_skipped} skipped in {duration:.1f}s"
        )

    except Exception as e:
        logger.error(f"Sync failed for {source.name}: {e}")
        result.error = str(e)
        result.duration_seconds = (datetime.now() - start_time).total_seconds()

    return result


def sync_all_products(
    kb_root: Path | None = None,
    products: list[str] | None = None,
    force: bool = False,
    num_gpus: int = 4,
) -> list[SyncResult]:
    """Sync documentation for all configured products.

    Uses smart routing: parallel processing for large PDF archives,
    sequential for smaller or HTML-only content.

    Args:
        kb_root: KB root directory (default: from environment)
        products: List of product names to sync (default: all)
        force: Force sync even if archives unchanged
        num_gpus: Number of GPUs for parallel processing (default: 4)

    Returns:
        List of SyncResults
    """
    if kb_root is None:
        kb_root = Path(os.environ.get("GAIUS_KB_ROOT", "build/dev"))

    sources = list_sources()
    if products:
        sources = [s for s in sources if s.name in products]

    results = []
    for source in sources:
        if source.source_type == SourceType.ARCHIVE and source.archive_url:
            logger.info(f"Syncing {source.display_name} ({source.version})...")
            # Use smart routing - auto-selects parallel for large PDF archives
            result = sync_product_smart(source, kb_root, force=force, num_gpus=num_gpus)
            results.append(result)
        else:
            logger.info(f"Skipping {source.name} (no archive URL)")

    return results


# =============================================================================
# CLI HELPERS
# =============================================================================

def get_sync_status() -> dict[str, Any]:
    """Get current sync status from database.

    Returns dict with status for each configured product.
    """
    # TODO: Query doc_archives table
    sources = list_sources()
    return {
        "products": [
            {
                "name": s.name,
                "display_name": s.display_name,
                "version": s.version,
                "archive_url": s.archive_url,
                "kb_prefix": s.kb_prefix,
            }
            for s in sources
            if s.source_type == SourceType.ARCHIVE
        ],
    }


def sync_product_smart(
    source: ProductSource,
    kb_root: Path,
    force: bool = False,
    num_gpus: int = 6,
    parallel_threshold: int = 10,
) -> SyncResult:
    """Smart sync that auto-selects sequential or parallel mode.

    Uses parallel processing for archives with many PDFs (>= parallel_threshold),
    sequential processing for smaller archives or HTML-only content.

    Args:
        source: Product source configuration
        kb_root: KB root directory
        force: Force sync even if unchanged
        num_gpus: Number of GPUs for parallel processing (default: 6)
        parallel_threshold: Min PDFs to trigger parallel mode (default: 10)

    Returns:
        SyncResult with sync outcome
    """
    if source.source_type != SourceType.ARCHIVE or not source.archive_url:
        return sync_product(source, kb_root, force)

    # Check archive contents
    try:
        archive_bytes = download_archive(source.archive_url)
        doc_files = extract_doc_files(archive_bytes)
        pdf_count = sum(1 for p in doc_files if p.endswith(".pdf"))

        logger.info(f"Archive contains {pdf_count} PDFs, {len(doc_files)} total files")

        if pdf_count >= parallel_threshold:
            logger.info(
                f"Using parallel processing ({pdf_count} PDFs >= {parallel_threshold} threshold)"
            )
            from .parallel import sync_product_parallel

            result_dict = sync_product_parallel(
                source=source,
                kb_root=kb_root,
                num_gpus=num_gpus,
                force=force,
            )

            # Convert dict to SyncResult
            return SyncResult(
                product=result_dict.get("product", source.name),
                success=result_dict.get("success", False),
                pages_extracted=result_dict.get("pages_extracted", 0),
                pages_skipped=result_dict.get("pages_skipped", 0),
                archive_hash=result_dict.get("archive_hash"),
                kb_prefix=result_dict.get("kb_prefix", source.kb_prefix),
                version=result_dict.get("version", source.version),
                duration_seconds=result_dict.get("duration_seconds", 0),
                error=result_dict.get("error"),
            )
        else:
            logger.info(
                f"Using sequential processing ({pdf_count} PDFs < {parallel_threshold} threshold)"
            )
            return sync_product(source, kb_root, force)

    except Exception as e:
        logger.warning(f"Smart routing failed, falling back to sequential: {e}")
        return sync_product(source, kb_root, force)


# For Metaflow integration (future)
# @register_flow("cloudera_docs")
class ClouderaDocsFlow:
    """Metaflow-compatible sync flow (placeholder).

    Full Metaflow implementation to be added when needed.
    Current implementation uses direct sync via sync_product().
    """
    pass
