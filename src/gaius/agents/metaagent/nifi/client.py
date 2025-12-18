"""Async HTTP client for NiFi REST API."""

import logging
from typing import Any, Optional

import httpx

from ..config import NiFiConfig
from .models import (
    ConnectionComponent,
    Position,
    ProcessGroupComponent,
    ProcessorComponent,
    ProcessorConfig,
    Revision,
)

logger = logging.getLogger(__name__)


class NiFiClient:
    """Async HTTP client for NiFi REST API.

    Provides methods for creating and managing NiFi flow elements:
    - Process groups (containers for flows)
    - Processors (flow elements)
    - Connections (relationships between processors)
    """

    def __init__(self, config: NiFiConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None
        self._token: Optional[str] = None

    async def connect(self) -> bool:
        """Initialize connection and authenticate if needed."""
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            verify=self.config.verify_ssl,
        )

        # Authenticate if credentials provided
        if self.config.username and self.config.password:
            try:
                resp = await self._client.post(
                    "/access/token",
                    data={
                        "username": self.config.username,
                        "password": self.config.password,
                    },
                )
                if resp.status_code == 201:
                    self._token = resp.text
                    logger.info("NiFi authentication successful")
                else:
                    logger.warning(f"NiFi auth failed: {resp.status_code}")
            except Exception as e:
                logger.warning(f"NiFi auth error: {e}")

        return True

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "NiFiClient":
        await self.connect()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    async def _request(
        self, method: str, path: str, **kwargs
    ) -> httpx.Response:
        """Make authenticated request."""
        if not self._client:
            raise RuntimeError("Client not connected. Call connect() first.")

        headers = kwargs.pop("headers", {})
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        resp = await self._client.request(method, path, headers=headers, **kwargs)
        resp.raise_for_status()
        return resp

    # =========================================================================
    # Process Group Operations
    # =========================================================================

    async def get_root_process_group(self) -> dict:
        """Get the root process group."""
        resp = await self._request("GET", "/flow/process-groups/root")
        return resp.json()

    async def create_process_group(
        self,
        parent_id: str,
        name: str,
        position: Position,
        comments: str = "",
    ) -> dict:
        """Create a process group."""
        payload = {
            "revision": {"version": 0},
            "component": {
                "name": name,
                "position": {"x": position.x, "y": position.y},
                "comments": comments,
            },
        }

        resp = await self._request(
            "POST",
            f"/process-groups/{parent_id}/process-groups",
            json=payload,
        )
        return resp.json()

    async def get_process_group(self, group_id: str) -> dict:
        """Get a process group by ID."""
        resp = await self._request("GET", f"/process-groups/{group_id}")
        return resp.json()

    # =========================================================================
    # Processor Operations
    # =========================================================================

    async def create_processor(
        self,
        process_group_id: str,
        processor_type: str,
        name: str,
        position: Position,
        config: Optional[ProcessorConfig] = None,
    ) -> dict:
        """Create a processor in a process group."""
        config = config or ProcessorConfig()

        payload = {
            "revision": {"version": 0},
            "component": {
                "type": processor_type,
                "name": name,
                "position": {"x": position.x, "y": position.y},
                "config": {
                    "properties": config.properties,
                    "schedulingStrategy": config.scheduling_strategy,
                    "schedulingPeriod": config.scheduling_period,
                    "penaltyDuration": config.penalty_duration,
                    "yieldDuration": config.yield_duration,
                    "runDurationMillis": config.run_duration_nanos // 1_000_000,
                    "bulletinLevel": config.bulletin_level,
                },
            },
        }

        resp = await self._request(
            "POST",
            f"/process-groups/{process_group_id}/processors",
            json=payload,
        )
        return resp.json()

    async def update_processor(
        self,
        processor_id: str,
        revision: Revision,
        updates: dict,
    ) -> dict:
        """Update a processor."""
        payload = {
            "revision": {"version": revision.version},
            "component": {"id": processor_id, **updates},
        }

        resp = await self._request(
            "PUT",
            f"/processors/{processor_id}",
            json=payload,
        )
        return resp.json()

    async def set_processor_state(
        self,
        processor_id: str,
        revision: Revision,
        state: str,  # STOPPED, RUNNING, DISABLED
    ) -> dict:
        """Set processor run state."""
        payload = {
            "revision": {"version": revision.version},
            "state": state,
        }

        resp = await self._request(
            "PUT",
            f"/processors/{processor_id}/run-status",
            json=payload,
        )
        return resp.json()

    # =========================================================================
    # Connection Operations
    # =========================================================================

    async def create_connection(
        self,
        process_group_id: str,
        source_id: str,
        dest_id: str,
        relationships: list[str],
        name: str = "",
    ) -> dict:
        """Create a connection between processors."""
        payload = {
            "revision": {"version": 0},
            "component": {
                "source": {"id": source_id, "type": "PROCESSOR"},
                "destination": {"id": dest_id, "type": "PROCESSOR"},
                "selectedRelationships": relationships,
                "name": name,
            },
        }

        resp = await self._request(
            "POST",
            f"/process-groups/{process_group_id}/connections",
            json=payload,
        )
        return resp.json()

    # =========================================================================
    # Flow Status Operations
    # =========================================================================

    async def get_flow_status(self, process_group_id: str) -> dict:
        """Get flow status for a process group."""
        resp = await self._request(
            "GET", f"/flow/process-groups/{process_group_id}/status"
        )
        return resp.json()

    async def get_system_diagnostics(self) -> dict:
        """Get NiFi system diagnostics."""
        resp = await self._request("GET", "/system-diagnostics")
        return resp.json()

    # =========================================================================
    # Health Check
    # =========================================================================

    async def health_check(self) -> bool:
        """Check if NiFi is healthy and responding."""
        try:
            resp = await self._request("GET", "/flow/status")
            return resp.status_code == 200
        except Exception as e:
            logger.warning(f"NiFi health check failed: {e}")
            return False
