"""Filesystem to S3 KB sync engine.

Robust one-way sync from local filesystem KB to RustFS/S3 storage.
Features:
- Incremental sync via SHA-256 content hashing
- Postgres-backed state for resume capability
- Post-upload verification
- Exponential backoff retry
- OpenLineage-compatible lineage events
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)

# Lazy imports
_asyncpg = None
_s3_client_cls = None


def _get_asyncpg():
    global _asyncpg
    if _asyncpg is None:
        import asyncpg
        _asyncpg = asyncpg
    return _asyncpg


def _get_s3_client():
    """Get the S3 client class (minio-py, deferred import; speaks to RustFS)."""
    global _s3_client_cls
    if _s3_client_cls is None:
        from minio import Minio
        _s3_client_cls = Minio
    return _s3_client_cls


# ═══════════════════════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class SyncTarget:
    """Configuration for a sync target."""

    id: int
    name: str
    target_type: str  # "rustfs" | "s3"  (rustfs = MinIO-SDK client against Signals RustFS)
    endpoint: str
    bucket: str
    region: str | None
    access_key: str
    secret_key: str
    secure: bool
    prefix: str = ""


@dataclass
class SyncResult:
    """Result of a sync operation."""

    files_scanned: int = 0
    files_uploaded: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    bytes_uploaded: int = 0
    orphans_found: int = 0
    duration_ms: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class FileState:
    """State of a file in the sync manifest."""

    file_path: str
    content_hash: str
    size_bytes: int
    local_mtime: datetime
    remote_etag: str | None = None
    synced_at: datetime | None = None
    sync_status: str = "pending"


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_retries: int = 3
    base_delay_ms: int = 1000
    max_delay_ms: int = 8000
    exponential_base: float = 2.0


# ═══════════════════════════════════════════════════════════════════════════════
# Sync Engine
# ═══════════════════════════════════════════════════════════════════════════════


class SyncEngine:
    """Robust filesystem-to-S3 sync with state tracking.

    Usage:
        target = await get_sync_target("rustfs-local", db_url)
        engine = SyncEngine("build/dev", target, db_url)
        result = await engine.sync(progress_callback=print_progress)
    """

    def __init__(
        self,
        source_root: str,
        target: SyncTarget,
        db_url: str,
        verify_uploads: bool = True,
        batch_size: int = 50,
        retry_config: RetryConfig | None = None,
        allowed_dirs: tuple[str, ...] = ("archive", "current", "scratch"),
    ):
        """Initialize sync engine.

        Args:
            source_root: Filesystem KB root path
            target: Sync target configuration
            db_url: Database URL for state tracking
            verify_uploads: Re-download and verify after upload
            batch_size: Files between checkpoints
            retry_config: Retry behavior for failed uploads
            allowed_dirs: Directories to sync (matches KB structure)
        """
        self.source_root = Path(source_root).resolve()
        self.target = target
        self.db_url = db_url
        self.verify_uploads = verify_uploads
        self.batch_size = batch_size
        self.retry_config = retry_config or RetryConfig()
        self.allowed_dirs = allowed_dirs
        self._client = None
        self._run_id: int | None = None

    async def sync(
        self,
        progress_callback: Callable[[int, int, str, str], None] | None = None,
        resume: bool = False,
        dry_run: bool = False,
    ) -> SyncResult:
        """Execute sync operation.

        Args:
            progress_callback: Called with (current, total, path, action)
            resume: Resume from last checkpoint if interrupted
            dry_run: Compute diff but don't upload

        Returns:
            SyncResult with operation statistics
        """
        start_time = time.time()
        result = SyncResult()

        # Create sync run record
        if not dry_run:
            self._run_id = await self._create_sync_run()

        try:
            # Load resume checkpoint if requested
            resume_from = None
            if resume and not dry_run:
                resume_from = await self._load_checkpoint()
                if resume_from:
                    logger.info(f"Resuming from checkpoint: {resume_from}")

            # Compute diff
            to_upload, to_skip, orphans = await self._compute_diff(resume_from)
            result.files_scanned = len(to_upload) + len(to_skip)
            result.files_skipped = len(to_skip)
            result.orphans_found = len(orphans)

            if dry_run:
                result.files_uploaded = len(to_upload)
                # Estimate bytes
                for path in to_upload:
                    try:
                        result.bytes_uploaded += (self.source_root / path).stat().st_size
                    except Exception:
                        pass
                result.duration_ms = int((time.time() - start_time) * 1000)
                return result

            # Process uploads
            total = len(to_upload)
            for i, path in enumerate(to_upload):
                if progress_callback:
                    progress_callback(i + 1, total, path, "uploading")

                success, size, error = await self._upload_with_retry(path)
                if success:
                    result.files_uploaded += 1
                    result.bytes_uploaded += size
                    if progress_callback:
                        progress_callback(i + 1, total, path, "uploaded")
                else:
                    result.files_failed += 1
                    result.errors.append((path, error or "Unknown error"))
                    if progress_callback:
                        progress_callback(i + 1, total, path, "failed")

                # Checkpoint every batch_size files
                if (i + 1) % self.batch_size == 0:
                    await self._save_checkpoint(path)

            # Report orphans (don't delete)
            if orphans:
                logger.info(f"Found {len(orphans)} orphaned files in remote")
                for orphan in orphans[:10]:
                    logger.debug(f"  Orphan: {orphan}")

            # Complete sync run
            result.duration_ms = int((time.time() - start_time) * 1000)
            await self._complete_sync_run(result, "completed")

            # Record lineage event
            await self._record_lineage_event(result)

            return result

        except Exception as e:
            logger.error(f"Sync failed: {e}")
            if self._run_id:
                await self._complete_sync_run(result, "failed", str(e))
            raise

    async def _compute_diff(
        self,
        resume_from: str | None = None,
    ) -> tuple[list[str], list[str], list[str]]:
        """Compute files to upload, skip, and orphans.

        Returns:
            (to_upload, to_skip, orphans) - sorted path lists
        """
        # Scan local files
        local_files: dict[str, FileState] = {}
        for path, content in self._iter_local_files():
            content_hash = self._compute_hash(content)
            try:
                stat = (self.source_root / path).stat()
                mtime = datetime.fromtimestamp(stat.st_mtime)
            except Exception:
                mtime = datetime.now()

            local_files[path] = FileState(
                file_path=path,
                content_hash=content_hash,
                size_bytes=len(content),
                local_mtime=mtime,
            )

        # Load existing sync state
        existing = await self._load_sync_state()

        to_upload = []
        to_skip = []

        # Compare (sorted for deterministic resume)
        for path in sorted(local_files.keys()):
            # Skip files before resume point
            if resume_from and path <= resume_from:
                to_skip.append(path)
                continue

            local = local_files[path]
            remote = existing.get(path)

            if remote is None:
                # New file
                to_upload.append(path)
            elif remote.content_hash != local.content_hash:
                # Changed file
                to_upload.append(path)
            else:
                # Unchanged
                to_skip.append(path)

        # Find orphans (in remote but not local)
        orphans = [p for p in existing if p not in local_files]

        logger.info(
            f"Diff: {len(to_upload)} to upload, {len(to_skip)} unchanged, "
            f"{len(orphans)} orphans"
        )

        return to_upload, to_skip, sorted(orphans)

    def _iter_local_files(self) -> Iterator[tuple[str, bytes]]:
        """Iterate all files in allowed directories.

        Yields:
            (relative_path, content) tuples
        """
        for dir_name in self.allowed_dirs:
            dir_path = self.source_root / dir_name
            if not dir_path.exists():
                continue

            for file_path in dir_path.rglob("*"):
                if not file_path.is_file():
                    continue

                # Skip cache directories
                if ".cache" in file_path.parts:
                    continue

                rel_path = str(file_path.relative_to(self.source_root))

                try:
                    content = file_path.read_bytes()
                    yield rel_path, content
                except Exception as e:
                    logger.warning(f"Failed to read {rel_path}: {e}")
                    continue

    def _compute_hash(self, content: bytes) -> str:
        """Compute SHA-256 hash for content."""
        return hashlib.sha256(content).hexdigest()

    async def _upload_with_retry(
        self,
        path: str,
    ) -> tuple[bool, int, str | None]:
        """Upload with exponential backoff retry.

        Returns:
            (success, bytes_uploaded, error_message)
        """
        last_error = None

        for attempt in range(self.retry_config.max_retries):
            try:
                size = await self._upload_file(path)
                return True, size, None
            except Exception as e:
                last_error = str(e)
                if attempt < self.retry_config.max_retries - 1:
                    delay = min(
                        self.retry_config.base_delay_ms
                        * (self.retry_config.exponential_base ** attempt),
                        self.retry_config.max_delay_ms,
                    )
                    logger.warning(
                        f"Upload attempt {attempt + 1} failed for {path}, "
                        f"retrying in {delay}ms: {e}"
                    )
                    await asyncio.sleep(delay / 1000)

        logger.error(f"Upload failed after {self.retry_config.max_retries} attempts: {path}")
        await self._update_sync_state(path, "", 0, None, "failed", last_error)
        return False, 0, last_error

    async def _upload_file(self, path: str) -> int:
        """Upload single file with optional verification.

        Returns:
            bytes uploaded
        """
        full_path = self.source_root / path
        content = full_path.read_bytes()
        content_hash = self._compute_hash(content)
        size = len(content)

        # Upload
        client = self._get_client()
        key = f"{self.target.prefix}{path}" if self.target.prefix else path

        result = client.put_object(
            self.target.bucket,
            key,
            io.BytesIO(content),
            length=size,
            content_type=self._guess_content_type(path),
        )

        # Verify if requested
        if self.verify_uploads:
            verified = await self._verify_remote(path, content_hash)
            if not verified:
                raise ValueError(f"Verification failed for {path}")

        # Update sync state
        mtime = datetime.fromtimestamp(full_path.stat().st_mtime)
        await self._update_sync_state(
            path=path,
            content_hash=content_hash,
            size_bytes=size,
            remote_etag=result.etag.strip('"') if result.etag else None,
            sync_status="synced",
            local_mtime=mtime,
        )

        return size

    async def _verify_remote(self, path: str, expected_hash: str) -> bool:
        """Download and verify content matches expected hash."""
        client = self._get_client()
        key = f"{self.target.prefix}{path}" if self.target.prefix else path

        try:
            response = client.get_object(self.target.bucket, key)
            content = response.read()
            response.close()
            response.release_conn()

            actual_hash = self._compute_hash(content)
            return actual_hash == expected_hash
        except Exception as e:
            logger.error(f"Verification failed for {path}: {e}")
            return False

    def _get_client(self):
        """Get or create the S3 client."""
        if self._client is None:
            S3Client = _get_s3_client()
            self._client = S3Client(
                self.target.endpoint,
                access_key=self.target.access_key,
                secret_key=self.target.secret_key,
                secure=self.target.secure,
            )
            # Ensure bucket exists
            if not self._client.bucket_exists(self.target.bucket):
                self._client.make_bucket(self.target.bucket)
        return self._client

    def _guess_content_type(self, path: str) -> str:
        """Guess content type from extension."""
        if path.endswith(".md"):
            return "text/markdown"
        elif path.endswith(".json"):
            return "application/json"
        elif path.endswith(".txt"):
            return "text/plain"
        elif path.endswith(".html"):
            return "text/html"
        return "application/octet-stream"

    # ═══════════════════════════════════════════════════════════════════════════
    # Database Operations
    # ═══════════════════════════════════════════════════════════════════════════

    async def _create_sync_run(self) -> int:
        """Create new sync run record."""
        asyncpg = _get_asyncpg()

        conn = await asyncpg.connect(self.db_url)
        try:
            config_snapshot = json.dumps({
                "verify_uploads": self.verify_uploads,
                "source_root": str(self.source_root),
                "allowed_dirs": list(self.allowed_dirs),
            })
            run_id = await conn.fetchval(
                """
                INSERT INTO kb_sync_runs (target_id, status, config_snapshot)
                VALUES ($1, 'running', $2::jsonb)
                RETURNING id
                """,
                self.target.id,
                config_snapshot,
            )
            return run_id
        finally:
            await conn.close()

    async def _complete_sync_run(
        self,
        result: SyncResult,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Update sync run with completion status."""
        if self._run_id is None:
            return

        asyncpg = _get_asyncpg()

        conn = await asyncpg.connect(self.db_url)
        try:
            await conn.execute(
                """
                UPDATE kb_sync_runs
                SET completed_at = NOW(),
                    status = $2,
                    files_scanned = $3,
                    files_uploaded = $4,
                    files_skipped = $5,
                    files_failed = $6,
                    bytes_uploaded = $7,
                    orphans_found = $8,
                    error_message = $9
                WHERE id = $1
                """,
                self._run_id,
                status,
                result.files_scanned,
                result.files_uploaded,
                result.files_skipped,
                result.files_failed,
                result.bytes_uploaded,
                result.orphans_found,
                error_message,
            )
        finally:
            await conn.close()

    async def _load_sync_state(self) -> dict[str, FileState]:
        """Load existing sync state from database."""
        asyncpg = _get_asyncpg()

        conn = await asyncpg.connect(self.db_url)
        try:
            rows = await conn.fetch(
                """
                SELECT file_path, content_hash, size_bytes, local_mtime,
                       remote_etag, synced_at, sync_status
                FROM kb_sync_state
                WHERE target_id = $1
                """,
                self.target.id,
            )
            return {
                row["file_path"]: FileState(
                    file_path=row["file_path"],
                    content_hash=row["content_hash"],
                    size_bytes=row["size_bytes"],
                    local_mtime=row["local_mtime"],
                    remote_etag=row["remote_etag"],
                    synced_at=row["synced_at"],
                    sync_status=row["sync_status"],
                )
                for row in rows
            }
        finally:
            await conn.close()

    async def _update_sync_state(
        self,
        path: str,
        content_hash: str,
        size_bytes: int,
        remote_etag: str | None,
        sync_status: str,
        error_message: str | None = None,
        local_mtime: datetime | None = None,
    ) -> None:
        """Update or insert sync state for a file."""
        asyncpg = _get_asyncpg()

        if local_mtime is None:
            try:
                local_mtime = datetime.fromtimestamp(
                    (self.source_root / path).stat().st_mtime
                )
            except Exception:
                local_mtime = datetime.now()

        conn = await asyncpg.connect(self.db_url)
        try:
            await conn.execute(
                """
                INSERT INTO kb_sync_state
                    (target_id, file_path, content_hash, size_bytes, local_mtime,
                     remote_etag, synced_at, sync_status, error_message)
                VALUES ($1, $2, $3, $4, $5, $6, NOW(), $7, $8)
                ON CONFLICT (target_id, file_path) DO UPDATE SET
                    content_hash = EXCLUDED.content_hash,
                    size_bytes = EXCLUDED.size_bytes,
                    local_mtime = EXCLUDED.local_mtime,
                    remote_etag = EXCLUDED.remote_etag,
                    synced_at = NOW(),
                    sync_status = EXCLUDED.sync_status,
                    error_message = EXCLUDED.error_message
                """,
                self.target.id,
                path,
                content_hash,
                size_bytes,
                local_mtime,
                remote_etag,
                sync_status,
                error_message,
            )
        finally:
            await conn.close()

    async def _save_checkpoint(self, last_path: str) -> None:
        """Save resume checkpoint."""
        if self._run_id is None:
            return

        asyncpg = _get_asyncpg()

        conn = await asyncpg.connect(self.db_url)
        try:
            await conn.execute(
                "UPDATE kb_sync_runs SET resume_token = $2 WHERE id = $1",
                self._run_id,
                last_path,
            )
        finally:
            await conn.close()

    async def _load_checkpoint(self) -> str | None:
        """Load last checkpoint for resuming."""
        asyncpg = _get_asyncpg()

        conn = await asyncpg.connect(self.db_url)
        try:
            row = await conn.fetchrow(
                """
                SELECT resume_token FROM kb_sync_runs
                WHERE target_id = $1 AND status = 'interrupted'
                ORDER BY started_at DESC LIMIT 1
                """,
                self.target.id,
            )
            return row["resume_token"] if row else None
        finally:
            await conn.close()

    async def _record_lineage_event(self, result: SyncResult) -> None:
        """Record sync in lineage_events table (OpenLineage format)."""
        asyncpg = _get_asyncpg()

        run_id = uuid.uuid4()
        inputs = [{"namespace": "filesystem", "name": str(self.source_root)}]
        outputs = [
            {
                "namespace": self.target.target_type,
                "name": f"{self.target.endpoint}/{self.target.bucket}",
            }
        ]
        facets = {
            "files_uploaded": result.files_uploaded,
            "files_skipped": result.files_skipped,
            "bytes_uploaded": result.bytes_uploaded,
            "orphans_found": result.orphans_found,
            "duration_ms": result.duration_ms,
        }

        conn = await asyncpg.connect(self.db_url)
        try:
            await conn.execute(
                """
                SELECT record_lineage_event(
                    $1::uuid,
                    'gaius.storage',
                    'kb_sync',
                    'COMPLETE',
                    $2::jsonb,
                    $3::jsonb,
                    $4::jsonb
                )
                """,
                run_id,
                json.dumps(inputs),
                json.dumps(outputs),
                json.dumps(facets),
            )
            logger.info(f"Recorded lineage event for sync run {run_id}")
        except Exception as e:
            # Don't fail sync if lineage recording fails
            logger.warning(f"Failed to record lineage event: {e}")
        finally:
            await conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════════════


async def get_sync_target(name: str, db_url: str) -> SyncTarget | None:
    """Resolve sync target from database + environment.

    Credentials are resolved from environment variables:
    - GAIUS_SYNC_{NAME}_ACCESS_KEY / GAIUS_SYNC_{NAME}_SECRET_KEY
    - Falls back to GAIUS_KB_ACCESS_KEY / GAIUS_KB_SECRET_KEY
    """
    asyncpg = _get_asyncpg()

    conn = await asyncpg.connect(db_url)
    try:
        row = await conn.fetchrow(
            "SELECT * FROM kb_sync_targets WHERE name = $1 AND is_active = true",
            name,
        )
        if not row:
            return None

        # Resolve credentials from environment
        env_prefix = f"GAIUS_SYNC_{name.upper().replace('-', '_')}_"
        access_key = os.getenv(f"{env_prefix}ACCESS_KEY", "")
        secret_key = os.getenv(f"{env_prefix}SECRET_KEY", "")

        # Fall back to generic KB credentials
        if not access_key:
            access_key = os.getenv("GAIUS_KB_ACCESS_KEY", "rustfsadmin")
        if not secret_key:
            secret_key = os.getenv("GAIUS_KB_SECRET_KEY", "rustfsadmin")

        # Parse config - asyncpg may return str or dict depending on version
        config_raw = row["config"]
        if isinstance(config_raw, str):
            config = json.loads(config_raw) if config_raw else {}
        else:
            config = config_raw or {}

        return SyncTarget(
            id=row["id"],
            name=row["name"],
            target_type=row["target_type"],
            endpoint=row["endpoint"],
            bucket=row["bucket"],
            region=row["region"],
            access_key=access_key,
            secret_key=secret_key,
            secure=config.get("secure", True),
            prefix=config.get("prefix", ""),
        )
    finally:
        await conn.close()


async def get_sync_status(target_name: str, db_url: str) -> dict[str, Any]:
    """Get sync status for a target."""
    asyncpg = _get_asyncpg()

    conn = await asyncpg.connect(db_url)
    try:
        # Get target
        target_row = await conn.fetchrow(
            "SELECT id, endpoint, bucket FROM kb_sync_targets WHERE name = $1",
            target_name,
        )
        if not target_row:
            return {"error": f"Unknown target: {target_name}"}

        target_id = target_row["id"]

        # Get state summary
        state = await conn.fetchrow(
            """
            SELECT
                COUNT(*) as total_files,
                COALESCE(SUM(size_bytes), 0) as total_bytes,
                COUNT(*) FILTER (WHERE sync_status = 'synced') as synced,
                COUNT(*) FILTER (WHERE sync_status = 'pending') as pending,
                COUNT(*) FILTER (WHERE sync_status = 'failed') as failed
            FROM kb_sync_state WHERE target_id = $1
            """,
            target_id,
        )

        # Get last run
        last_run = await conn.fetchrow(
            """
            SELECT started_at, completed_at, status, files_uploaded,
                   files_skipped, bytes_uploaded, orphans_found
            FROM kb_sync_runs WHERE target_id = $1
            ORDER BY started_at DESC LIMIT 1
            """,
            target_id,
        )

        return {
            "target": target_name,
            "endpoint": target_row["endpoint"],
            "bucket": target_row["bucket"],
            "state": {
                "total_files": int(state["total_files"]),
                "total_bytes": int(state["total_bytes"]),
                "synced": int(state["synced"]),
                "pending": int(state["pending"]),
                "failed": int(state["failed"]),
            },
            "last_run": {
                "started_at": last_run["started_at"].isoformat()
                if last_run
                else None,
                "completed_at": last_run["completed_at"].isoformat()
                if last_run and last_run["completed_at"]
                else None,
                "status": last_run["status"] if last_run else None,
                "files_uploaded": int(last_run["files_uploaded"]) if last_run else 0,
                "files_skipped": int(last_run["files_skipped"]) if last_run else 0,
                "bytes_uploaded": int(last_run["bytes_uploaded"]) if last_run else 0,
                "orphans_found": int(last_run["orphans_found"]) if last_run else 0,
            }
            if last_run
            else None,
        }
    finally:
        await conn.close()


async def list_sync_targets(db_url: str) -> list[dict[str, Any]]:
    """List all configured sync targets."""
    asyncpg = _get_asyncpg()

    conn = await asyncpg.connect(db_url)
    try:
        rows = await conn.fetch(
            """
            SELECT name, target_type, endpoint, bucket, region, is_active, created_at
            FROM kb_sync_targets
            ORDER BY name
            """
        )
        return [
            {
                "name": r["name"],
                "type": r["target_type"],
                "endpoint": r["endpoint"],
                "bucket": r["bucket"],
                "region": r["region"],
                "active": r["is_active"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
    finally:
        await conn.close()


async def verify_sync(
    target_name: str,
    source_root: str,
    db_url: str,
    sample_size: int = 20,
) -> dict[str, Any]:
    """Verify a sample of synced files match local content.

    Args:
        target_name: Sync target name
        source_root: Local KB root
        db_url: Database URL
        sample_size: Number of files to verify

    Returns:
        Dict with verified count and any mismatches
    """
    target = await get_sync_target(target_name, db_url)
    if not target:
        return {"error": f"Unknown target: {target_name}"}

    engine = SyncEngine(source_root, target, db_url, verify_uploads=False)
    state = await engine._load_sync_state()

    # Sample synced files
    synced = [s for s in state.values() if s.sync_status == "synced"]
    import random
    sample = random.sample(synced, min(sample_size, len(synced)))

    verified = 0
    mismatches = []

    for file_state in sample:
        ok = await engine._verify_remote(file_state.file_path, file_state.content_hash)
        if ok:
            verified += 1
        else:
            mismatches.append(file_state.file_path)

    return {
        "target": target_name,
        "sample_size": len(sample),
        "verified": verified,
        "mismatches": mismatches,
    }
