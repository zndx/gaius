"""Worker pool manager.

Manages a pool of async workers that poll fetch_jobs from PostgreSQL
and dispatch to appropriate fetchers. Raw content is also written to
the Gaius HX data lake (Iceberg tables) for long-term storage.
"""

import asyncio
import logging
import signal
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx

from gaius.workers.base import FetcherRegistry
from gaius.workers.config import WorkerConfig
from gaius.workers.db import Database
from gaius.workers.models import ContentItem as WorkerContentItem, FetchJob, JobStatus

# Import fetchers to register them
from gaius.workers import fetchers  # noqa: F401

logger = logging.getLogger(__name__)

# Thread pool for sync Iceberg operations
_hx_executor: ThreadPoolExecutor | None = None


def _get_hx_executor() -> ThreadPoolExecutor:
    """Get or create the HX thread pool executor."""
    global _hx_executor
    if _hx_executor is None:
        _hx_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hx-writer")
    return _hx_executor


def _convert_to_hx_item(
    item: WorkerContentItem,
    source_type: str,
) -> "HxContentItem":
    """Convert a worker ContentItem to an HX ContentItem for Iceberg storage.

    Args:
        item: Worker ContentItem from fetch result.
        source_type: Source type string (e.g., "arxiv", "rss").

    Returns:
        HX ContentItem for Iceberg storage.
    """
    from gaius.hx.writer import ContentItem as HxContentItem

    return HxContentItem(
        source_id=item.source_id,
        external_id=item.external_id or "",
        title=item.title,
        source_type=source_type,
        url=item.url,
        authors=item.authors if item.authors else None,
        raw_content=item.content,  # Full content goes to Iceberg
        content_type=item.content_type,
        metadata=item.metadata if item.metadata else None,
        published_at=item.published_at,
        fetched_at=item.fetched_at,
    )


class WorkerPool:
    """Manages a pool of fetch workers.

    Writes fetched content to both PostgreSQL (for quick access) and
    Iceberg (for long-term storage and analytics via gaius.hx).
    """

    def __init__(self, config: WorkerConfig, enable_hx: bool = True):
        self.config = config
        self.enable_hx = enable_hx
        self.db: Database | None = None
        self.http: httpx.AsyncClient | None = None
        self._shutdown = asyncio.Event()
        self._workers: list[asyncio.Task] = []
        self._hx_store = None  # Lazy-loaded IcebergContentStore

    def _get_hx_store(self):
        """Get or create the HX content store (lazy initialization).

        Returns:
            IcebergContentStore instance or None if HX is disabled/unavailable.
        """
        if not self.enable_hx:
            return None

        if self._hx_store is None:
            try:
                from gaius.hx import IcebergContentStore, get_hx_config

                config = get_hx_config()
                if not config.enabled:
                    logger.info("HX data lake is disabled in config")
                    self.enable_hx = False
                    return None

                self._hx_store = IcebergContentStore(config)
                logger.info("Initialized HX content store for Iceberg writes")
            except ImportError as e:
                logger.warning(f"HX module not available: {e}")
                self.enable_hx = False
                return None
            except Exception as e:
                logger.warning(f"Failed to initialize HX store: {e}")
                self.enable_hx = False
                return None

        return self._hx_store

    async def _write_to_hx(
        self,
        items: list[WorkerContentItem],
        source_type: str,
    ) -> int:
        """Write content items to HX Iceberg storage asynchronously.

        Runs the sync Iceberg write in a thread pool to avoid blocking.

        Args:
            items: Worker ContentItem objects to store.
            source_type: Source type string for the items.

        Returns:
            Number of items written to Iceberg.
        """
        store = self._get_hx_store()
        if store is None:
            return 0

        # Convert worker items to HX items
        hx_items = [_convert_to_hx_item(item, source_type) for item in items]

        # Run sync Iceberg write in thread pool
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                _get_hx_executor(),
                store.store_content,
                hx_items,
            )
            if result.success:
                logger.debug(
                    f"Wrote {result.items_written} items to HX Iceberg "
                    f"(snapshot: {result.snapshot_id})"
                )
                return result.items_written
            else:
                logger.warning(f"HX write failed: {result.errors}")
                return 0
        except Exception as e:
            logger.warning(f"HX write error: {e}")
            return 0

    @asynccontextmanager
    async def _resources(self) -> AsyncIterator[None]:
        """Context manager for shared resources."""
        self.db = await Database.connect(
            self.config.db_url,
            min_size=2,
            max_size=self.config.pool_size + 2,
        )
        self.http = httpx.AsyncClient(
            timeout=self.config.http_timeout,
            headers={"User-Agent": self.config.user_agent},
            follow_redirects=True,
        )
        try:
            yield
        finally:
            await self.http.aclose()
            await self.db.close()

    async def run(self) -> None:
        """Run the worker pool until shutdown."""
        async with self._resources():
            logger.info(
                f"Starting worker pool with {self.config.pool_size} workers"
            )

            # Start workers
            async with asyncio.TaskGroup() as tg:
                for i in range(self.config.pool_size):
                    task = tg.create_task(
                        self._worker_loop(worker_id=i),
                        name=f"worker-{i}",
                    )
                    self._workers.append(task)

                # Wait for shutdown signal
                await self._shutdown.wait()

                # Cancel all workers
                for task in self._workers:
                    task.cancel()

            logger.info("Worker pool shut down")

    async def run_once(self) -> int:
        """Run a single pass of job processing.

        Returns the number of jobs processed.
        """
        async with self._resources():
            processed = 0
            while True:
                job = await self.db.claim_next_job(self.config.job_timeout)
                if job is None:
                    break
                await self._process_job(job)
                processed += 1
            return processed

    async def shutdown(self) -> None:
        """Signal the pool to shut down."""
        logger.info("Shutdown requested")
        self._shutdown.set()

    async def _worker_loop(self, worker_id: int) -> None:
        """Main loop for a single worker."""
        logger.debug(f"Worker {worker_id} started")

        while not self._shutdown.is_set():
            try:
                # Try to claim a job
                job = await self.db.claim_next_job(self.config.job_timeout)

                if job is None:
                    # No jobs available, wait before polling again
                    try:
                        await asyncio.wait_for(
                            self._shutdown.wait(),
                            timeout=self.config.poll_interval,
                        )
                    except asyncio.TimeoutError:
                        pass
                    continue

                # Process the job
                logger.info(
                    f"Worker {worker_id} processing job {job.id} "
                    f"(source: {job.source.name if job.source else job.source_id})"
                )
                await self._process_job(job)

            except asyncio.CancelledError:
                logger.debug(f"Worker {worker_id} cancelled")
                raise
            except Exception as e:
                logger.exception(f"Worker {worker_id} error: {e}")
                # Continue after error
                await asyncio.sleep(1)

        logger.debug(f"Worker {worker_id} stopped")

    async def _process_job(self, job: FetchJob) -> None:
        """Process a single fetch job."""
        if job.source is None:
            await self.db.fail_job(job.id, "Source not found")
            return

        source = job.source

        # Get the appropriate fetcher
        fetcher = FetcherRegistry.create(
            source.source_type,
            self.config,
            self.http,
        )

        if fetcher is None:
            await self.db.fail_job(
                job.id,
                f"No fetcher for source type: {source.source_type.value}",
            )
            return

        try:
            # Execute the fetch
            result = await fetcher.fetch(source)

            if result.error:
                await self.db.fail_job(
                    job.id,
                    result.error,
                    metadata=result.metadata,
                )
                return

            # Insert content items to PostgreSQL (quick access)
            total, new_count = await self.db.insert_content_items(result.items)

            # Write to HX Iceberg data lake (long-term storage)
            # Only write new items to avoid duplicates in Iceberg
            if new_count > 0 and self.enable_hx:
                hx_written = await self._write_to_hx(
                    result.items,
                    source.source_type.value,
                )
                if hx_written > 0:
                    logger.debug(f"Job {job.id}: wrote {hx_written} items to HX")

            # Update source last_fetch_at
            await self.db.update_source_last_fetch(source.id)

            # Complete the job
            await self.db.complete_job(
                job.id,
                items_fetched=total,
                items_new=new_count,
                metadata=result.metadata,
            )

            logger.info(
                f"Job {job.id} completed: {total} items fetched, {new_count} new"
            )

        except Exception as e:
            logger.exception(f"Job {job.id} failed: {e}")
            await self.db.fail_job(job.id, str(e))


def setup_signal_handlers(pool: WorkerPool) -> None:
    """Set up signal handlers for graceful shutdown."""
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda: asyncio.create_task(pool.shutdown()),
        )


async def run_worker_pool(config: WorkerConfig) -> None:
    """Run the worker pool with signal handling."""
    pool = WorkerPool(config)
    setup_signal_handlers(pool)
    await pool.run()


async def run_once(config: WorkerConfig) -> int:
    """Run a single pass of job processing."""
    pool = WorkerPool(config)
    return await pool.run_once()
