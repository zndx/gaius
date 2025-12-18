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
    database_url: str = "postgres://localhost:5438/zndx_gaius?sslmode=disable"

    # Sync settings
    lineage_sync_interval_hours: int = 6
    operations_sync_interval_hours: int = 1
    topology_sync_daily_hour: int = 3  # 3 AM

    @classmethod
    def from_env(cls) -> "MetaAgentConfig":
        """Load configuration from environment variables."""
        import os

        nifi_url = os.getenv("NIFI_URL", "http://localhost:8450/nifi-api")
        db_url = os.getenv(
            "GAIUS_DATABASE_URL",
            "postgres://localhost:5438/zndx_gaius?sslmode=disable",
        )

        return cls(
            nifi=NiFiConfig(base_url=nifi_url),
            database_url=db_url,
        )
