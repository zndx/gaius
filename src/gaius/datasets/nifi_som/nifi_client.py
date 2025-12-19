"""NiFi REST API client for canvas manipulation."""

import httpx
from typing import Optional
from .models import Processor, Connection


class NiFiClient:
    """Client for NiFi REST API interactions."""

    def __init__(self, base_url: str = "http://localhost:8450"):
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}/nifi-api"

    async def get_root_process_group_id(self) -> str:
        """Get the root process group ID."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.api_url}/flow/process-groups/root")
            resp.raise_for_status()
            return resp.json()["processGroupFlow"]["id"]

    async def list_process_groups(
        self, parent_id: Optional[str] = None
    ) -> list[dict]:
        """List all process groups under a parent."""
        if parent_id is None:
            parent_id = await self.get_root_process_group_id()

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.api_url}/flow/process-groups/{parent_id}"
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("processGroupFlow", {}).get("flow", {}).get(
                "processGroups", []
            )

    async def get_process_group(self, pg_id: str) -> dict:
        """Get a process group by ID."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.api_url}/process-groups/{pg_id}")
            resp.raise_for_status()
            return resp.json()

    async def get_process_group_flow(self, pg_id: str) -> dict:
        """Get the flow contents of a process group."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.api_url}/flow/process-groups/{pg_id}"
            )
            resp.raise_for_status()
            return resp.json()

    async def create_process_group(
        self,
        parent_id: str,
        name: str,
        position: tuple[float, float] = (100, 100),
        comments: str = "",
    ) -> str:
        """Create a new process group and return its ID."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.api_url}/process-groups/{parent_id}/process-groups",
                json={
                    "revision": {"version": 0},
                    "component": {
                        "name": name,
                        "position": {"x": position[0], "y": position[1]},
                        "comments": comments,
                    },
                },
            )
            resp.raise_for_status()
            return resp.json()["id"]

    async def get_processors(self, pg_id: str) -> list[Processor]:
        """Get all processors in a process group."""
        flow = await self.get_process_group_flow(pg_id)
        processors = flow.get("processGroupFlow", {}).get("flow", {}).get(
            "processors", []
        )

        return [
            Processor(
                id=p["id"],
                name=p["component"]["name"],
                type=p["component"]["type"],
                position=p["position"],
                config=p["component"].get("config", {}),
            )
            for p in processors
        ]

    async def get_connections(self, pg_id: str) -> list[Connection]:
        """Get all connections in a process group."""
        flow = await self.get_process_group_flow(pg_id)
        connections = flow.get("processGroupFlow", {}).get("flow", {}).get(
            "connections", []
        )

        return [
            Connection(
                id=c["id"],
                source_id=c["component"]["source"]["id"],
                destination_id=c["component"]["destination"]["id"],
                source_name=c["component"]["source"].get("name", ""),
                destination_name=c["component"]["destination"].get("name", ""),
                relationships=c["component"].get("selectedRelationships", []),
            )
            for c in connections
        ]

    async def create_processor(
        self,
        pg_id: str,
        name: str,
        processor_type: str = "org.apache.nifi.processors.standard.GenerateFlowFile",
        position: tuple[float, float] = (100, 100),
        bundle: Optional[dict] = None,
    ) -> str:
        """Create a processor and return its ID."""
        if bundle is None:
            bundle = {
                "group": "org.apache.nifi",
                "artifact": "nifi-standard-nar",
                "version": "1.28.1",
            }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.api_url}/process-groups/{pg_id}/processors",
                json={
                    "revision": {"version": 0},
                    "component": {
                        "name": name,
                        "type": processor_type,
                        "bundle": bundle,
                        "position": {"x": position[0], "y": position[1]},
                        "config": {
                            "comments": f"Metaflow step: {name}",
                            "schedulingPeriod": "1 min",
                        },
                    },
                },
            )
            resp.raise_for_status()
            return resp.json()["id"]

    async def create_connection(
        self,
        pg_id: str,
        source_id: str,
        destination_id: str,
        relationships: list[str] = None,
    ) -> str:
        """Create a connection between processors."""
        if relationships is None:
            relationships = ["success"]

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.api_url}/process-groups/{pg_id}/connections",
                json={
                    "revision": {"version": 0},
                    "component": {
                        "source": {
                            "id": source_id,
                            "groupId": pg_id,
                            "type": "PROCESSOR",
                        },
                        "destination": {
                            "id": destination_id,
                            "groupId": pg_id,
                            "type": "PROCESSOR",
                        },
                        "selectedRelationships": relationships,
                    },
                },
            )
            resp.raise_for_status()
            return resp.json()["id"]

    async def sync_flow(
        self, flow_name: str, steps: list[str], parent_id: Optional[str] = None
    ) -> str:
        """Create or update a process group from Metaflow steps.

        Returns the process group ID.
        """
        if parent_id is None:
            parent_id = await self.get_root_process_group_id()

        # Check if process group already exists
        existing_pgs = await self.list_process_groups(parent_id)
        for pg in existing_pgs:
            if pg["component"]["name"] == flow_name:
                return pg["id"]

        # Create new process group
        pg_id = await self.create_process_group(
            parent_id, flow_name, comments=f"Metaflow pipeline: {flow_name}"
        )

        # Create processors for each step
        x_start = 100
        y_pos = 100
        x_spacing = 250
        processor_ids = {}

        for i, step in enumerate(steps):
            x_pos = x_start + i * x_spacing
            proc_id = await self.create_processor(
                pg_id, step, position=(x_pos, y_pos)
            )
            processor_ids[step] = proc_id

        # Create connections between sequential steps
        for i in range(len(steps) - 1):
            await self.create_connection(
                pg_id, processor_ids[steps[i]], processor_ids[steps[i + 1]]
            )

        return pg_id

    def get_canvas_url(self, pg_id: str) -> str:
        """Get the URL for viewing a process group canvas."""
        return f"{self.base_url}/nifi/?processGroupId={pg_id}"
