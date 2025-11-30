"""Worker pool manager.

Manages a pool of async workers that poll fetch_jobs from PostgreSQL
and dispatch to appropriate fetchers.
"""

import asyncio
import logging
import signal
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx

from gaius.workers.base import FetcherRegistry
from gaius.workers.config import WorkerConfig
from gaius.workers.db import Database
from gaius.workers.models import FetchJob, JobStatus

# Import fetchers to register them
from gaius.workers import fetchers  # noqa: F401

logger = logging.getLogger(__name__)


class WorkerPool:
    """Manages a pool of fetch workers."""

    def __init__(self, config: WorkerConfig):
        self.config = config
        self.db: Database | None = None
        self.http: httpx.AsyncClient | None = None
        self._shutdown = asyncio.Event()
        self._workers: list[asyncio.Task] = []

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

            # Insert content items
            total, new_count = await self.db.insert_content_items(result.items)

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
