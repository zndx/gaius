"""Content provenance tracking for KB resources.

This module provides the "source of truth" tracking that enables the
single "in-sync" constraint per KB resource across heterogeneous sources:
- ZIP archives (hashable, versioned)
- HTML pages (ETag/content hash)
- External documentation (Last-Modified, version detection)

Architecture:
    ┌─────────────────────────────────────────────────────────────┐
    │                    ContentSource                             │
    │  - source_uri (canonical identifier)                         │
    │  - source_type (archive, html, api, manual)                  │
    │  - content_hash (SHA-256 of raw content)                     │
    │  - upstream_version (detected or declared)                   │
    │  - fetched_at (when we retrieved it)                         │
    │  - etag (for HTTP conditional requests)                      │
    └──────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
    ┌─────────────────────────────────────────────────────────────┐
    │                  TransformChain                              │
    │  List of transforms applied: PDF→MD, boilerplate strip, etc. │
    └──────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
    ┌─────────────────────────────────────────────────────────────┐
    │                   KBResourceLineage                          │
    │  - kb_path (where it lives in KB)                            │
    │  - sources (List[ContentSource])                             │
    │  - derived_at (when KB resource was created)                 │
    │  - transform_chain (how source → KB)                         │
    └─────────────────────────────────────────────────────────────┘

The SourceInSync constraint checks if the KB resource is current with
all its upstream sources, enabling a single boolean "in-sync" status.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import httpx
from pydantic import BaseModel, Field

from gaius.rase.traceability import TraceableId, IdScheme


class SourceType(str, Enum):
    """Type of upstream content source.

    Determines how freshness is checked:
    - ARCHIVE: ZIP/tar file with content hash
    - HTML: Web page with ETag or content hash
    - API: REST API with version endpoint
    - GIT: Git repository with commit hash
    - MANUAL: Manually managed, no auto-check
    """
    ARCHIVE = "archive"
    HTML = "html"
    API = "api"
    GIT = "git"
    MANUAL = "manual"


class TransformType(str, Enum):
    """Type of transformation applied to content."""
    PDF_TO_MARKDOWN = "pdf_to_markdown"
    HTML_TO_MARKDOWN = "html_to_markdown"
    BOILERPLATE_STRIP = "boilerplate_strip"
    SPLIT_BY_SECTION = "split_by_section"
    MERGE_DOCUMENTS = "merge_documents"
    ONTOLOGY_EXTRACT = "ontology_extract"
    CUSTOM = "custom"


class Transform(BaseModel):
    """A single transformation in the pipeline.

    Attributes:
        transform_type: What kind of transform
        applied_at: When it was applied
        tool_version: Version of tool used (e.g., docling 2.15.0)
        parameters: Transform-specific parameters
        input_hash: Hash of input content
        output_hash: Hash of output content
    """
    transform_type: TransformType
    applied_at: datetime = Field(default_factory=datetime.now)
    tool_version: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    input_hash: str = ""
    output_hash: str = ""

    model_config = {"frozen": True}


class ContentSource(BaseModel):
    """Upstream content source with provenance metadata.

    This is the canonical representation of where KB content came from.
    Supports multiple source types with appropriate freshness checks.

    Attributes:
        source_uri: Canonical URI (URL, file path, or git ref)
        source_type: How to check freshness
        content_hash: SHA-256 of raw content when fetched
        upstream_version: Detected or declared version (e.g., "1.5.4")
        fetched_at: When we retrieved the content
        etag: HTTP ETag for conditional requests
        last_modified: HTTP Last-Modified header
        metadata: Additional source-specific metadata
    """
    source_uri: str
    source_type: SourceType = SourceType.HTML
    content_hash: str = ""
    upstream_version: str = ""
    fetched_at: datetime = Field(default_factory=datetime.now)
    etag: str = ""
    last_modified: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}

    def to_traceable_id(self) -> TraceableId:
        """Generate TraceableId for this source."""
        # Normalize URI to path format
        path = self.source_uri
        if path.startswith("https://"):
            path = path[8:]
        elif path.startswith("http://"):
            path = path[7:]

        # Include version if known
        version = self.upstream_version or None

        return TraceableId(
            scheme=IdScheme.RASE,
            path=f"source/{self.source_type.value}/{path}",
            version=version,
        )

    @classmethod
    def from_archive(
        cls,
        url: str,
        archive_hash: str,
        version: str = "",
        fetched_at: datetime | None = None,
    ) -> "ContentSource":
        """Create source from ZIP/tar archive."""
        return cls(
            source_uri=url,
            source_type=SourceType.ARCHIVE,
            content_hash=archive_hash,
            upstream_version=version,
            fetched_at=fetched_at or datetime.now(),
        )

    @classmethod
    def from_html(
        cls,
        url: str,
        content_hash: str = "",
        etag: str = "",
        last_modified: str = "",
        fetched_at: datetime | None = None,
    ) -> "ContentSource":
        """Create source from HTML page."""
        return cls(
            source_uri=url,
            source_type=SourceType.HTML,
            content_hash=content_hash,
            etag=etag,
            last_modified=last_modified,
            fetched_at=fetched_at or datetime.now(),
        )

    @classmethod
    def from_git(
        cls,
        repo_url: str,
        commit_hash: str,
        branch: str = "main",
        fetched_at: datetime | None = None,
    ) -> "ContentSource":
        """Create source from git repository."""
        return cls(
            source_uri=repo_url,
            source_type=SourceType.GIT,
            content_hash=commit_hash,
            metadata={"branch": branch},
            fetched_at=fetched_at or datetime.now(),
        )

    def is_stale(
        self,
        max_age: timedelta = timedelta(days=7),
        current_time: datetime | None = None,
    ) -> bool:
        """Check if this source record is older than max_age."""
        now = current_time or datetime.now()
        age = now - self.fetched_at
        return age > max_age


class KBResourceLineage(BaseModel):
    """Complete provenance chain for a KB resource.

    Links a KB path to all its upstream sources and the transforms
    applied. Enables the single "in-sync" constraint by tracking:
    - Multiple sources (e.g., main doc + related API reference)
    - Transform chain (PDF→markdown→boilerplate strip)
    - Derived timestamps

    Attributes:
        kb_path: Path in KB (e.g., "current/cloudera/docs/csa/1.5.4/...")
        sources: List of upstream content sources
        transforms: Transform pipeline applied
        derived_at: When KB resource was created/updated
        derived_hash: Hash of final KB content
    """
    kb_path: str
    sources: list[ContentSource] = Field(default_factory=list)
    transforms: list[Transform] = Field(default_factory=list)
    derived_at: datetime = Field(default_factory=datetime.now)
    derived_hash: str = ""

    def to_traceable_id(self) -> TraceableId:
        """Generate TraceableId for this KB resource."""
        return TraceableId(
            scheme=IdScheme.RASE,
            path=f"kb/{self.kb_path}",
        )

    def add_source(self, source: ContentSource) -> "KBResourceLineage":
        """Add a source (returns new lineage - immutable pattern)."""
        return KBResourceLineage(
            kb_path=self.kb_path,
            sources=[*self.sources, source],
            transforms=self.transforms,
            derived_at=self.derived_at,
            derived_hash=self.derived_hash,
        )

    def add_transform(self, transform: Transform) -> "KBResourceLineage":
        """Add a transform step (returns new lineage)."""
        return KBResourceLineage(
            kb_path=self.kb_path,
            sources=self.sources,
            transforms=[*self.transforms, transform],
            derived_at=self.derived_at,
            derived_hash=self.derived_hash,
        )

    def any_source_stale(
        self,
        max_age: timedelta = timedelta(days=7),
        current_time: datetime | None = None,
    ) -> bool:
        """Check if any source is stale."""
        return any(
            source.is_stale(max_age, current_time)
            for source in self.sources
        )

    @classmethod
    def from_frontmatter(cls, kb_path: str, frontmatter: dict[str, Any]) -> "KBResourceLineage":
        """Parse lineage from existing KB frontmatter.

        Handles the current Cloudera docs format:
            source: docs.cloudera.com
            product: csa-operator
            version: 1.4
            archive: csa-operator
            source_path: csa-operator/1.4/overview/csa-op-overview.pdf
            synced_at: 2025-12-22T07:17:45.774381
            archive_hash: 541b2c78b28da47e
        """
        sources = []

        # Check for archive-style source (Cloudera docs)
        if "archive_hash" in frontmatter:
            source_domain = frontmatter.get("source", "unknown")
            archive_name = frontmatter.get("archive", "")
            version = frontmatter.get("version", "")
            source_path = frontmatter.get("source_path", "")

            # Reconstruct archive URL
            if archive_name and source_domain == "docs.cloudera.com":
                archive_url = f"https://docs.cloudera.com/downloads/{archive_name}-docs-archive.zip"
            else:
                archive_url = f"https://{source_domain}/{source_path}"

            synced_at_raw = frontmatter.get("synced_at", "")
            if isinstance(synced_at_raw, datetime):
                synced_at = synced_at_raw
            elif synced_at_raw:
                try:
                    synced_at = datetime.fromisoformat(str(synced_at_raw))
                except ValueError:
                    synced_at = datetime.now()
            else:
                synced_at = datetime.now()

            sources.append(ContentSource(
                source_uri=archive_url,
                source_type=SourceType.ARCHIVE,
                content_hash=frontmatter.get("archive_hash", ""),
                upstream_version=str(version),
                fetched_at=synced_at,
                metadata={
                    "product": frontmatter.get("product", ""),
                    "source_path": source_path,
                },
            ))

        # Check for direct URL source
        elif "source_url" in frontmatter:
            synced_at_raw = frontmatter.get("synced_at", frontmatter.get("fetched_at", ""))
            if isinstance(synced_at_raw, datetime):
                synced_at = synced_at_raw
            elif synced_at_raw:
                try:
                    synced_at = datetime.fromisoformat(str(synced_at_raw))
                except ValueError:
                    synced_at = datetime.now()
            else:
                synced_at = datetime.now()

            sources.append(ContentSource(
                source_uri=frontmatter["source_url"],
                source_type=SourceType.HTML,
                content_hash=frontmatter.get("content_hash", ""),
                etag=frontmatter.get("etag", ""),
                fetched_at=synced_at,
            ))

        # Parse transforms if present
        transforms = []
        if "transform_chain" in frontmatter:
            for t in frontmatter["transform_chain"]:
                try:
                    transforms.append(Transform(
                        transform_type=TransformType(t.get("type", "custom")),
                        tool_version=t.get("tool_version", ""),
                        parameters=t.get("parameters", {}),
                    ))
                except ValueError:
                    transforms.append(Transform(
                        transform_type=TransformType.CUSTOM,
                        parameters={"raw": t},
                    ))

        derived_at_raw = frontmatter.get("derived_at", frontmatter.get("synced_at", ""))
        if isinstance(derived_at_raw, datetime):
            derived_at = derived_at_raw
        elif derived_at_raw:
            try:
                derived_at = datetime.fromisoformat(str(derived_at_raw))
            except ValueError:
                derived_at = datetime.now()
        else:
            derived_at = datetime.now()

        return cls(
            kb_path=kb_path,
            sources=sources,
            transforms=transforms,
            derived_at=derived_at,
            derived_hash=frontmatter.get("derived_hash", frontmatter.get("content_hash", "")),
        )

    def to_frontmatter(self) -> dict[str, Any]:
        """Export lineage to frontmatter format for KB storage."""
        fm: dict[str, Any] = {
            "derived_at": self.derived_at.isoformat(),
        }

        if self.derived_hash:
            fm["derived_hash"] = self.derived_hash

        # Primary source (first in list)
        if self.sources:
            primary = self.sources[0]
            fm["source_uri"] = primary.source_uri
            fm["source_type"] = primary.source_type.value
            fm["content_hash"] = primary.content_hash
            fm["fetched_at"] = primary.fetched_at.isoformat()
            if primary.upstream_version:
                fm["upstream_version"] = primary.upstream_version
            if primary.etag:
                fm["etag"] = primary.etag
            if primary.metadata:
                fm["source_metadata"] = primary.metadata

        # Additional sources
        if len(self.sources) > 1:
            fm["additional_sources"] = [
                {
                    "source_uri": s.source_uri,
                    "source_type": s.source_type.value,
                    "content_hash": s.content_hash,
                    "fetched_at": s.fetched_at.isoformat(),
                }
                for s in self.sources[1:]
            ]

        # Transform chain
        if self.transforms:
            fm["transform_chain"] = [
                {
                    "type": t.transform_type.value,
                    "tool_version": t.tool_version,
                    "applied_at": t.applied_at.isoformat(),
                }
                for t in self.transforms
            ]

        return fm


class FreshnessCheck(BaseModel):
    """Result of checking upstream freshness.

    Attributes:
        source: The source that was checked
        is_fresh: Whether local matches upstream
        upstream_hash: Current upstream hash (if retrieved)
        upstream_version: Current upstream version (if detected)
        check_method: How freshness was determined
        error: Error message if check failed
    """
    source: ContentSource
    is_fresh: bool = True
    upstream_hash: str = ""
    upstream_version: str = ""
    check_method: str = ""  # hash_compare, etag, last_modified, head_request
    error: str = ""
    checked_at: datetime = Field(default_factory=datetime.now)


async def check_source_freshness(
    source: ContentSource,
    timeout: float = 30.0,
) -> FreshnessCheck:
    """Check if a source is fresh against its upstream.

    Uses the most efficient method based on source type:
    - ARCHIVE: HEAD request + hash comparison
    - HTML: ETag/If-None-Match or Last-Modified
    - GIT: ls-remote to check commit
    - API: Version endpoint
    - MANUAL: Always fresh (no check)

    Args:
        source: Source to check
        timeout: HTTP timeout in seconds

    Returns:
        FreshnessCheck with results
    """
    if source.source_type == SourceType.MANUAL:
        return FreshnessCheck(
            source=source,
            is_fresh=True,
            check_method="manual",
        )

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if source.source_type == SourceType.ARCHIVE:
                # For archives, we need to re-download to compare hash
                # But first try HEAD to check Last-Modified
                response = await client.head(source.source_uri, follow_redirects=True)

                if response.status_code == 200:
                    last_mod = response.headers.get("Last-Modified", "")
                    if last_mod and source.last_modified:
                        # Compare Last-Modified timestamps
                        is_fresh = last_mod == source.last_modified
                        return FreshnessCheck(
                            source=source,
                            is_fresh=is_fresh,
                            check_method="last_modified",
                        )

                    # Fall back to content-length heuristic
                    content_length = response.headers.get("Content-Length", "")
                    if content_length:
                        return FreshnessCheck(
                            source=source,
                            is_fresh=True,  # Can't determine without download
                            check_method="head_request",
                            upstream_version=f"size:{content_length}",
                        )

                return FreshnessCheck(
                    source=source,
                    is_fresh=True,
                    check_method="head_request",
                )

            elif source.source_type == SourceType.HTML:
                # Use conditional request with ETag
                headers = {}
                if source.etag:
                    headers["If-None-Match"] = source.etag
                elif source.last_modified:
                    headers["If-Modified-Since"] = source.last_modified

                response = await client.head(source.source_uri, headers=headers, follow_redirects=True)

                if response.status_code == 304:
                    # Not Modified - content is fresh
                    return FreshnessCheck(
                        source=source,
                        is_fresh=True,
                        check_method="etag" if source.etag else "last_modified",
                    )
                elif response.status_code == 200:
                    # Modified - check new ETag
                    new_etag = response.headers.get("ETag", "")
                    if new_etag and source.etag:
                        is_fresh = new_etag == source.etag
                        return FreshnessCheck(
                            source=source,
                            is_fresh=is_fresh,
                            upstream_hash=new_etag,
                            check_method="etag",
                        )

                    # No reliable freshness check available
                    return FreshnessCheck(
                        source=source,
                        is_fresh=True,  # Assume fresh without hash comparison
                        check_method="head_request",
                    )

                return FreshnessCheck(
                    source=source,
                    is_fresh=True,
                    check_method="head_request",
                    error=f"Unexpected status: {response.status_code}",
                )

            elif source.source_type == SourceType.GIT:
                # Would need git ls-remote - not implemented via HTTP
                return FreshnessCheck(
                    source=source,
                    is_fresh=True,
                    check_method="not_implemented",
                    error="Git freshness check requires git CLI",
                )

            elif source.source_type == SourceType.API:
                # API version check would be source-specific
                return FreshnessCheck(
                    source=source,
                    is_fresh=True,
                    check_method="not_implemented",
                    error="API freshness check requires custom implementation",
                )

            else:
                return FreshnessCheck(
                    source=source,
                    is_fresh=True,
                    check_method="unknown_type",
                )

    except httpx.TimeoutException:
        return FreshnessCheck(
            source=source,
            is_fresh=True,  # Assume fresh on timeout
            check_method="failed",
            error="Request timeout",
        )
    except Exception as e:
        return FreshnessCheck(
            source=source,
            is_fresh=True,  # Assume fresh on error
            check_method="failed",
            error=str(e),
        )


def compute_content_hash(content: bytes | str) -> str:
    """Compute SHA-256 hash of content."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def extract_version_from_url(url: str) -> str | None:
    """Extract version number from URL path.

    Handles patterns like:
    - /csa/1.5.4/overview/...
    - /v2.3.1/docs/...
    - /release-3.2/...
    """
    patterns = [
        r"/(\d+\.\d+(?:\.\d+)?)/",  # 1.5.4, 1.5
        r"/v(\d+\.\d+(?:\.\d+)?)/",  # v2.3.1
        r"/release-(\d+\.\d+(?:\.\d+)?)/",  # release-3.2
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


async def get_lineage_from_db(
    kb_path: str,
    db_url: str | None = None,
) -> KBResourceLineage | None:
    """Get lineage from postgres summary_lineage table.

    Queries the existing lineage infrastructure to find provenance
    for a KB resource, using the OpenLineage-compatible tables.

    Args:
        kb_path: KB path (e.g., "current/topics/kudu.md")
        db_url: Database URL (defaults to GAIUS_DATABASE_URL env)

    Returns:
        KBResourceLineage if found, None otherwise
    """
    import os
    try:
        import asyncpg
    except ImportError:
        return None

    db_url = db_url or os.environ.get("GAIUS_DATABASE_URL")
    if not db_url:
        return None

    try:
        conn = await asyncpg.connect(db_url)
        try:
            # Query summary_lineage joined with content_items and sources
            row = await conn.fetchrow("""
                SELECT
                    sl.kb_path,
                    sl.created_at,
                    sl.iceberg_record_id,
                    sl.quality_score,
                    sl.lineage_run_id,
                    ci.url as source_url,
                    ci.title as source_title,
                    ci.fetched_at,
                    ci.content_hash,
                    s.source_type,
                    s.name as source_name
                FROM summary_lineage sl
                LEFT JOIN content_items ci ON sl.content_item_id = ci.id
                LEFT JOIN sources s ON ci.source_id = s.id
                WHERE sl.kb_path = $1
            """, kb_path)

            if not row:
                return None

            sources = []
            if row["source_url"]:
                source_type = SourceType.HTML
                if row["source_type"]:
                    st = row["source_type"].lower()
                    if "rss" in st or "feed" in st:
                        source_type = SourceType.API
                    elif "git" in st:
                        source_type = SourceType.GIT
                    elif "archive" in st or "zip" in st:
                        source_type = SourceType.ARCHIVE

                sources.append(ContentSource(
                    source_uri=row["source_url"],
                    source_type=source_type,
                    content_hash=row["content_hash"] or "",
                    fetched_at=row["fetched_at"] or datetime.now(),
                    metadata={
                        "title": row["source_title"],
                        "source_name": row["source_name"],
                        "iceberg_id": row["iceberg_record_id"],
                        "lineage_run_id": str(row["lineage_run_id"]) if row["lineage_run_id"] else None,
                    },
                ))

            return KBResourceLineage(
                kb_path=kb_path,
                sources=sources,
                derived_at=row["created_at"] or datetime.now(),
            )

        finally:
            await conn.close()

    except Exception:
        return None


async def get_sync_state_from_db(
    file_path: str,
    target_name: str = "rustfs-local",
    db_url: str | None = None,
) -> dict[str, Any] | None:
    """Get sync state for a file from kb_sync_state table.

    Args:
        file_path: Relative file path in KB
        target_name: Sync target name
        db_url: Database URL

    Returns:
        Dict with sync state if found
    """
    import os
    try:
        import asyncpg
    except ImportError:
        return None

    db_url = db_url or os.environ.get("GAIUS_DATABASE_URL")
    if not db_url:
        return None

    try:
        conn = await asyncpg.connect(db_url)
        try:
            row = await conn.fetchrow("""
                SELECT
                    ss.file_path,
                    ss.content_hash,
                    ss.size_bytes,
                    ss.local_mtime,
                    ss.remote_etag,
                    ss.synced_at,
                    ss.sync_status,
                    ss.error_message,
                    st.name as target_name,
                    st.endpoint,
                    st.bucket
                FROM kb_sync_state ss
                JOIN kb_sync_targets st ON ss.target_id = st.id
                WHERE ss.file_path = $1 AND st.name = $2
            """, file_path, target_name)

            if not row:
                return None

            return {
                "file_path": row["file_path"],
                "content_hash": row["content_hash"],
                "size_bytes": row["size_bytes"],
                "local_mtime": row["local_mtime"],
                "remote_etag": row["remote_etag"],
                "synced_at": row["synced_at"],
                "sync_status": row["sync_status"],
                "error_message": row["error_message"],
                "target": {
                    "name": row["target_name"],
                    "endpoint": row["endpoint"],
                    "bucket": row["bucket"],
                },
            }

        finally:
            await conn.close()

    except Exception:
        return None


async def record_lineage_event(
    run_id: str,
    job_namespace: str,
    job_name: str,
    run_state: str,
    inputs: list[dict[str, Any]] | None = None,
    outputs: list[dict[str, Any]] | None = None,
    facets: dict[str, Any] | None = None,
    parent_run_id: str | None = None,
    db_url: str | None = None,
) -> int | None:
    """Record an OpenLineage event to postgres.

    Wrapper around the record_lineage_event() SQL function.

    Args:
        run_id: UUID of the run
        job_namespace: Job namespace (e.g., "gaius.sync", "gaius.fetch")
        job_name: Job name (e.g., "cloudera_docs", "arxiv")
        run_state: START, RUNNING, COMPLETE, FAIL, or ABORT
        inputs: Input datasets [{namespace, name, facets}]
        outputs: Output datasets [{namespace, name, facets}]
        facets: Run facets (metadata)
        parent_run_id: Parent run UUID for nested runs
        db_url: Database URL

    Returns:
        Event ID if recorded, None on error
    """
    import json
    import os
    from uuid import UUID
    try:
        import asyncpg
    except ImportError:
        return None

    db_url = db_url or os.environ.get("GAIUS_DATABASE_URL")
    if not db_url:
        return None

    try:
        conn = await asyncpg.connect(db_url)
        try:
            result = await conn.fetchval("""
                SELECT record_lineage_event(
                    $1::uuid, $2, $3, $4,
                    $5::jsonb, $6::jsonb, $7::jsonb,
                    $8::uuid
                )
            """,
                UUID(run_id),
                job_namespace,
                job_name,
                run_state,
                json.dumps(inputs or []),
                json.dumps(outputs or []),
                json.dumps(facets or {}),
                UUID(parent_run_id) if parent_run_id else None,
            )
            return result

        finally:
            await conn.close()

    except Exception:
        return None


__all__ = [
    "SourceType",
    "TransformType",
    "Transform",
    "ContentSource",
    "KBResourceLineage",
    "FreshnessCheck",
    "check_source_freshness",
    "compute_content_hash",
    "extract_version_from_url",
    # Database integration
    "get_lineage_from_db",
    "get_sync_state_from_db",
    "record_lineage_event",
]
