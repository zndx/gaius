"""Async HTTP client for NiFi REST API."""

import logging
from typing import Any, Optional

import httpx

from ..config import NiFiConfig
from ..telemetry import trace_nifi_operation
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

    @trace_nifi_operation("get_root_process_group")
    async def get_root_process_group(self) -> dict:
        """Get the root process group."""
        resp = await self._request("GET", "/flow/process-groups/root")
        return resp.json()

    @trace_nifi_operation("create_process_group")
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

    @trace_nifi_operation("get_process_group")
    async def get_process_group(self, group_id: str) -> dict:
        """Get a process group by ID."""
        resp = await self._request("GET", f"/process-groups/{group_id}")
        return resp.json()

    # =========================================================================
    # Processor Operations
    # =========================================================================

    @trace_nifi_operation("create_processor")
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

    @trace_nifi_operation("update_processor")
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

    @trace_nifi_operation("set_processor_state")
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

    @trace_nifi_operation("create_connection")
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
                "source": {
                    "id": source_id,
                    "groupId": process_group_id,
                    "type": "PROCESSOR",
                },
                "destination": {
                    "id": dest_id,
                    "groupId": process_group_id,
                    "type": "PROCESSOR",
                },
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
    # Process Group Contents (for State Management)
    # =========================================================================

    @trace_nifi_operation("get_process_group_contents")
    async def get_process_group_contents(self, group_id: str) -> dict:
        """Get full contents of a process group.

        Returns the processGroupFlow including all processors, connections,
        and child process groups. Used by NiFiStateManager for state capture.
        """
        resp = await self._request("GET", f"/flow/process-groups/{group_id}")
        return resp.json()

    @trace_nifi_operation("list_processors")
    async def list_processors(self, group_id: str) -> list[dict]:
        """List all processors in a process group.

        Returns list of processor entities with their full configuration.
        """
        contents = await self.get_process_group_contents(group_id)
        flow = contents.get("processGroupFlow", {}).get("flow", {})
        return flow.get("processors", [])

    @trace_nifi_operation("list_connections")
    async def list_connections(self, group_id: str) -> list[dict]:
        """List all connections in a process group.

        Returns list of connection entities with source/destination info.
        """
        contents = await self.get_process_group_contents(group_id)
        flow = contents.get("processGroupFlow", {}).get("flow", {})
        return flow.get("connections", [])

    @trace_nifi_operation("list_child_process_groups")
    async def list_child_process_groups(self, group_id: str) -> list[dict]:
        """List all child process groups.

        Returns list of process group entities.
        """
        contents = await self.get_process_group_contents(group_id)
        flow = contents.get("processGroupFlow", {}).get("flow", {})
        return flow.get("processGroups", [])

    @trace_nifi_operation("get_processor")
    async def get_processor(self, processor_id: str) -> dict:
        """Get a processor by ID."""
        resp = await self._request("GET", f"/processors/{processor_id}")
        return resp.json()

    @trace_nifi_operation("get_connection")
    async def get_connection(self, connection_id: str) -> dict:
        """Get a connection by ID."""
        resp = await self._request("GET", f"/connections/{connection_id}")
        return resp.json()

    # =========================================================================
    # Delete Operations (for clear_process_group)
    # =========================================================================

    @trace_nifi_operation("stop_processor")
    async def stop_processor(
        self,
        processor_id: str,
        version: int,
    ) -> dict:
        """Stop a running processor.

        Wrapper around set_processor_state for convenience.
        """
        return await self.set_processor_state(
            processor_id,
            Revision(version=version),
            "STOPPED",
        )

    @trace_nifi_operation("delete_processor")
    async def delete_processor(
        self,
        processor_id: str,
        version: int,
    ) -> None:
        """Delete a processor.

        The processor must be stopped first.
        Raises HTTPStatusError on failure.
        """
        await self._request(
            "DELETE",
            f"/processors/{processor_id}",
            params={"version": version},
        )

    @trace_nifi_operation("drop_connection_queue")
    async def drop_connection_queue(
        self,
        connection_id: str,
    ) -> dict:
        """Drop (empty) the queue for a connection.

        Must be called before deleting a connection with queued FlowFiles.
        Returns the drop request entity.
        """
        resp = await self._request(
            "POST",
            f"/flowfile-queues/{connection_id}/drop-requests",
        )
        return resp.json()

    @trace_nifi_operation("delete_connection")
    async def delete_connection(
        self,
        connection_id: str,
        version: int,
    ) -> None:
        """Delete a connection.

        The connection queue must be empty first (use drop_connection_queue).
        Raises HTTPStatusError on failure.
        """
        await self._request(
            "DELETE",
            f"/connections/{connection_id}",
            params={"version": version},
        )

    @trace_nifi_operation("delete_process_group")
    async def delete_process_group(
        self,
        group_id: str,
        version: int,
    ) -> None:
        """Delete a process group.

        The process group must be empty (no processors, connections, or child groups).
        Use NiFiStateManager.clear_process_group() for recursive deletion.
        Raises HTTPStatusError on failure.
        """
        await self._request(
            "DELETE",
            f"/process-groups/{group_id}",
            params={"version": version},
        )

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
