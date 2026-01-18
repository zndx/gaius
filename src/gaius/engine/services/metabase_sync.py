"""Metabase sync client for MetaAgent service.

Syncs meta.* schema views to Metabase models and dashboards via API.
Uses API key authentication (not session-based) for reliability.

Metabase API Reference:
- POST /api/card - Create model/question (type="model" for models)
- PUT /api/card/:id - Update existing model
- POST /api/dashboard - Create dashboard
- GET /api/database/:id/schema/meta - Get meta schema tables/views
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Result of a sync operation."""

    success: bool
    models_synced: int = 0
    models_failed: int = 0
    dashboards_synced: int = 0
    dashboards_failed: int = 0
    error: str | None = None
    duration_ms: int = 0


@dataclass
class MetabaseModel:
    """Represents a Metabase model (semantic layer)."""

    name: str
    source_table: str
    description: str
    card_id: int | None = None
    display_type: str = "table"


# Models to sync from meta.* schema
DEFAULT_MODELS: list[MetabaseModel] = [
    MetabaseModel(
        name="Budget Status",
        source_table="v_budget_status",
        description="Current pooled budget status for audits and evaluations",
    ),
    MetabaseModel(
        name="Quality Summary",
        source_table="v_quality_summary",
        description="Aggregated quality metrics by source type",
    ),
    MetabaseModel(
        name="Recommendation Funnel",
        source_table="v_recommendation_funnel",
        description="Recommendation status funnel for self-improvement tracking",
    ),
    MetabaseModel(
        name="Recent Audits",
        source_table="v_recent_audits",
        description="Recent MetaAgent audit runs with finding counts",
    ),
    MetabaseModel(
        name="Flow Runs",
        source_table="flow_runs",
        description="Metaflow run history and statistics",
    ),
    MetabaseModel(
        name="Agent Versions",
        source_table="agent_versions",
        description="Agent version history and performance scores",
    ),
    MetabaseModel(
        name="KB Topology",
        source_table="kb_topology",
        description="Knowledge base document topology and clusters",
    ),
]


class MetabaseSyncClient:
    """Client for syncing meta.* views to Metabase models.

    Features:
    - API key authentication (X-API-Key header)
    - Creates/updates Metabase models from PostgreSQL views
    - Tracks sync history in meta.metabase_sync_runs
    - Registers models in meta.metabase_models

    Configuration (via config):
    - metabase.url: Metabase instance URL
    - metabase.api_key: API key for authentication
    - metabase.database_id: Database ID in Metabase for meta schema

    Guru Meditation Codes:
    - #MA.00000010.MBNOCONFIG - Metabase not configured
    - #MA.00000011.MBCONNFAIL - Metabase connection failed
    - #MA.00000012.MBSYNCFAIL - Sync operation failed
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        database_id: int | None = None,
    ):
        """Initialize Metabase client.

        Args:
            base_url: Metabase instance URL (e.g., http://localhost:3000)
            api_key: Metabase API key
            database_id: Database ID in Metabase
        """
        self.base_url = base_url or os.environ.get("METABASE_URL")
        self.api_key = api_key or os.environ.get("METABASE_API_KEY")
        db_id_str = os.environ.get("METABASE_DATABASE_ID")
        self.database_id = database_id or (int(db_id_str) if db_id_str else None)

        self._client: httpx.AsyncClient | None = None
        self._connected = False

    @property
    def is_configured(self) -> bool:
        """Check if Metabase is configured."""
        return bool(self.base_url and self.api_key and self.database_id)

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "X-API-Key": self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def test_connection(self) -> bool:
        """Test connection to Metabase.

        Returns:
            True if connection successful, False otherwise
        """
        if not self.is_configured:
            logger.warning("[#MA.00000010.MBNOCONFIG] Metabase not configured")
            return False

        try:
            client = await self._get_client()
            response = await client.get("/api/session/properties")

            if response.status_code == 200:
                self._connected = True
                logger.info("Metabase connection successful")
                return True

            logger.warning(
                f"[#MA.00000011.MBCONNFAIL] Metabase connection failed: {response.status_code}"
            )
            return False

        except Exception as e:
            logger.error(f"[#MA.00000011.MBCONNFAIL] Metabase connection error: {e}")
            return False

    async def get_schema_tables(self) -> list[dict[str, Any]]:
        """Get tables/views from meta schema.

        Returns:
            List of table metadata from Metabase
        """
        if not self._connected:
            await self.test_connection()

        client = await self._get_client()
        response = await client.get(f"/api/database/{self.database_id}/schema/meta")

        if response.status_code != 200:
            logger.error(f"Failed to get schema: {response.status_code}")
            return []

        return response.json()

    async def create_or_update_model(self, model: MetabaseModel) -> dict[str, Any] | None:
        """Create or update a Metabase model.

        Args:
            model: Model definition to sync

        Returns:
            Created/updated card data or None on failure
        """
        if not self._connected:
            await self.test_connection()

        client = await self._get_client()

        # First, try to find existing model by name
        existing_card_id = await self._find_model_by_name(model.name)

        card_data = {
            "name": model.name,
            "description": model.description,
            "type": "model",
            "dataset_query": {
                "type": "query",
                "database": self.database_id,
                "query": {
                    "source-table": f"meta.{model.source_table}",
                },
            },
            "display": model.display_type,
            "visualization_settings": {},
        }

        try:
            if existing_card_id:
                # Update existing model
                response = await client.put(f"/api/card/{existing_card_id}", json=card_data)
                if response.status_code == 200:
                    logger.info(f"Updated model: {model.name}")
                    return response.json()
            else:
                # Create new model
                response = await client.post("/api/card", json=card_data)
                if response.status_code == 200:
                    logger.info(f"Created model: {model.name}")
                    return response.json()

            logger.error(f"Failed to sync model {model.name}: {response.status_code}")
            return None

        except Exception as e:
            logger.error(f"Error syncing model {model.name}: {e}")
            return None

    async def _find_model_by_name(self, name: str) -> int | None:
        """Find existing model by name.

        Args:
            name: Model name to search for

        Returns:
            Card ID if found, None otherwise
        """
        client = await self._get_client()

        try:
            # Search for cards with matching name
            response = await client.get(
                "/api/card",
                params={"f": "all", "model_id": True},
            )

            if response.status_code != 200:
                return None

            cards = response.json()
            for card in cards:
                if card.get("name") == name and card.get("type") == "model":
                    return card.get("id")

            return None

        except Exception:
            return None

    async def sync_all_models(
        self,
        models: list[MetabaseModel] | None = None,
        full_refresh: bool = False,
    ) -> SyncResult:
        """Sync all models to Metabase.

        Args:
            models: Models to sync (default: DEFAULT_MODELS)
            full_refresh: If True, recreate all models

        Returns:
            SyncResult with statistics
        """
        start_time = datetime.now()
        models = models or DEFAULT_MODELS

        if not self.is_configured:
            return SyncResult(
                success=False,
                error="Metabase not configured. Set metabase_url, metabase_api_key, metabase_database_id",
            )

        if not await self.test_connection():
            return SyncResult(
                success=False,
                error="Failed to connect to Metabase",
            )

        synced = 0
        failed = 0

        for model in models:
            try:
                result = await self.create_or_update_model(model)
                if result:
                    synced += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"Error syncing {model.name}: {e}")
                failed += 1

        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        return SyncResult(
            success=failed == 0,
            models_synced=synced,
            models_failed=failed,
            duration_ms=duration_ms,
        )

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
            self._connected = False


# Module-level singleton
_metabase_client: MetabaseSyncClient | None = None


def get_metabase_client() -> MetabaseSyncClient:
    """Get or create Metabase client singleton."""
    global _metabase_client
    if _metabase_client is None:
        _metabase_client = MetabaseSyncClient()
    return _metabase_client


async def reset_metabase_client() -> None:
    """Reset Metabase client singleton (for testing)."""
    global _metabase_client
    if _metabase_client:
        await _metabase_client.close()
    _metabase_client = None
