"""Worker configuration.

Configuration hierarchy (highest to lowest priority):
1. CLI flags: --pool-size=4 --poll-interval=30
2. Environment: GAIUS_WORKER_POOL_SIZE, GAIUS_WORKER_POLL_INTERVAL, DATABASE_URL
3. Defaults: pool_size=4, poll_interval=30
"""

from dataclasses import dataclass
import os


@dataclass
class WorkerConfig:
    """Configuration for the fetch worker pool."""

    # Database connection
    db_url: str = ""

    # Worker pool settings
    pool_size: int = 4  # Number of concurrent workers
    poll_interval: int = 30  # Seconds between job polling
    job_timeout: int = 300  # Max seconds per job (5 min)
    batch_size: int = 10  # Items to process per batch

    # Retry settings
    max_retries: int = 3
    retry_delay: int = 60  # Seconds between retries

    # HTTP client settings
    http_timeout: float = 30.0  # Request timeout
    user_agent: str = "Gaius-Worker/0.2.0 (https://github.com/zndx/gaius)"

    def __post_init__(self):
        """Resolve database URL from config if not explicitly provided."""
        if not self.db_url:
            from gaius.core.config import get_database_url
            self.db_url = get_database_url()

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        """Load configuration from environment variables."""
        from gaius.core.config import get_database_url

        return cls(
            db_url=get_database_url(),
            pool_size=int(os.getenv("GAIUS_WORKER_POOL_SIZE", "4")),
            poll_interval=int(os.getenv("GAIUS_WORKER_POLL_INTERVAL", "30")),
            job_timeout=int(os.getenv("GAIUS_WORKER_JOB_TIMEOUT", "300")),
            batch_size=int(os.getenv("GAIUS_WORKER_BATCH_SIZE", "10")),
            max_retries=int(os.getenv("GAIUS_WORKER_MAX_RETRIES", "3")),
            retry_delay=int(os.getenv("GAIUS_WORKER_RETRY_DELAY", "60")),
            http_timeout=float(os.getenv("GAIUS_WORKER_HTTP_TIMEOUT", "30")),
            user_agent=os.getenv(
                "GAIUS_WORKER_USER_AGENT",
                "Gaius-Worker/0.2.0 (https://github.com/zndx/gaius)",
            ),
        )

    def with_pool_size(self, pool_size: int) -> "WorkerConfig":
        """Return a new config with the specified pool size."""
        return WorkerConfig(
            db_url=self.db_url,
            pool_size=pool_size,
            poll_interval=self.poll_interval,
            job_timeout=self.job_timeout,
            batch_size=self.batch_size,
            max_retries=self.max_retries,
            retry_delay=self.retry_delay,
            http_timeout=self.http_timeout,
            user_agent=self.user_agent,
        )
