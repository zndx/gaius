"""MetaAgent configuration."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class NiFiConfig:
    """NiFi connection configuration."""

    base_url: str = "http://localhost:8450/nifi-api"
    username: Optional[str] = None
    password: Optional[str] = None
    timeout: float = 30.0
    verify_ssl: bool = False


@dataclass
class MetaAgentConfig:
    """MetaAgent configuration."""

    nifi: NiFiConfig = field(default_factory=NiFiConfig)

    # Database connection for meta schema
    database_url: str = ""

    # Sync settings
    lineage_sync_interval_hours: int = 6
    operations_sync_interval_hours: int = 1
    topology_sync_daily_hour: int = 3  # 3 AM

    def __post_init__(self):
        """Resolve database URL from config if not explicitly provided."""
        if not self.database_url:
            from gaius.core.config import get_database_url
            self.database_url = get_database_url()

    @classmethod
    def from_env(cls) -> "MetaAgentConfig":
        """Load configuration from environment variables."""
        import os

        from gaius.core.config import get_database_url

        nifi_url = os.getenv("NIFI_URL", "http://localhost:8450/nifi-api")
        db_url = get_database_url()

        return cls(
            nifi=NiFiConfig(base_url=nifi_url),
            database_url=db_url,
        )
