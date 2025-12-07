"""Apache AGE Graph Query Helpers.

Provides high-level functions for querying the lineage graph.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class LineageNode:
    """A node in the lineage graph."""

    node_type: str  # Dataset, Job, Run
    id: str
    properties: dict = field(default_factory=dict)


@dataclass
class LineageEdge:
    """An edge in the lineage graph."""

    edge_type: str  # INPUT_TO, OUTPUTS, EXECUTES, PARENT
    from_id: str
    to_id: str
    properties: dict = field(default_factory=dict)


@dataclass
class LineagePath:
    """A path through the lineage graph."""

    nodes: list[LineageNode]
    edges: list[LineageEdge]


class LineageGraphQuery:
    """Query helper for the lineage graph.

    Provides convenient methods for common lineage queries:
    - Get upstream sources for a dataset
    - Get downstream outputs from a dataset
    - Get the lineage chain for a KB file
    - Find all runs that processed a dataset
    """

    def __init__(
        self,
        database_url: str | None = None,
        graph_name: str = "gaius_hx",
    ):
        """Initialize the query helper.

        Args:
            database_url: PostgreSQL connection URL.
            graph_name: Name of the AGE graph.
        """
        self._database_url = database_url
        self._graph_name = graph_name
        self._pool: asyncpg.Pool | None = None

    async def _get_pool(self) -> asyncpg.Pool:
        """Get or create the connection pool."""
        if self._pool is None:
            import asyncpg

            if self._database_url is None:
                from gaius.core.config import get_config
                self._database_url = get_config().database.url

            self._pool = await asyncpg.create_pool(
                self._database_url,
                min_size=1,
                max_size=5,
            )
        return self._pool

    async def get_upstream(
        self,
        dataset_namespace: str,
        dataset_name: str,
        max_depth: int = 10,
    ) -> list[LineageNode]:
        """Get upstream sources for a dataset.

        Traverses INPUT_TO and OUTPUTS edges backwards to find
        all datasets that contributed to this one.

        Args:
            dataset_namespace: Dataset namespace (e.g., "gaius.kb").
            dataset_name: Dataset name (e.g., "current/topics/foo.md").
            max_depth: Maximum traversal depth.

        Returns:
            List of upstream Dataset nodes.
        """
        pool = await self._get_pool()
        dataset_id = f"{dataset_namespace}:{dataset_name}"

        async with pool.acquire() as conn:
            await conn.execute("LOAD 'age'")
            await conn.execute("SET search_path = ag_catalog, \"$user\", public")

            # Find upstream datasets through runs
            cypher = f"""
                SELECT * FROM cypher('{self._graph_name}', $$
                    MATCH (target:Dataset {{dataset_id: '{dataset_id}'}})
                    MATCH path = (source:Dataset)-[:INPUT_TO*1..{max_depth}]->(:Run)-[:OUTPUTS*1..{max_depth}]->(target)
                    RETURN DISTINCT source
                $$) AS (source agtype);
            """

            try:
                rows = await conn.fetch(cypher)
                return [self._parse_node(row["source"]) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get upstream lineage: {e}")
                return []

    async def get_downstream(
        self,
        dataset_namespace: str,
        dataset_name: str,
        max_depth: int = 10,
    ) -> list[LineageNode]:
        """Get downstream outputs from a dataset.

        Traverses INPUT_TO and OUTPUTS edges forwards to find
        all datasets derived from this one.

        Args:
            dataset_namespace: Dataset namespace.
            dataset_name: Dataset name.
            max_depth: Maximum traversal depth.

        Returns:
            List of downstream Dataset nodes.
        """
        pool = await self._get_pool()
        dataset_id = f"{dataset_namespace}:{dataset_name}"

        async with pool.acquire() as conn:
            await conn.execute("LOAD 'age'")
            await conn.execute("SET search_path = ag_catalog, \"$user\", public")

            cypher = f"""
                SELECT * FROM cypher('{self._graph_name}', $$
                    MATCH (source:Dataset {{dataset_id: '{dataset_id}'}})
                    MATCH path = (source)-[:INPUT_TO*1..{max_depth}]->(:Run)-[:OUTPUTS*1..{max_depth}]->(target:Dataset)
                    RETURN DISTINCT target
                $$) AS (target agtype);
            """

            try:
                rows = await conn.fetch(cypher)
                return [self._parse_node(row["target"]) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get downstream lineage: {e}")
                return []

    async def get_kb_lineage(self, kb_path: str) -> LineagePath:
        """Get the complete lineage chain for a KB file.

        Args:
            kb_path: Path to the KB file.

        Returns:
            LineagePath with all nodes and edges in the chain.
        """
        pool = await self._get_pool()
        dataset_id = f"gaius.kb:{kb_path}"

        async with pool.acquire() as conn:
            await conn.execute("LOAD 'age'")
            await conn.execute("SET search_path = ag_catalog, \"$user\", public")

            # Get the full path from source to KB
            cypher = f"""
                SELECT * FROM cypher('{self._graph_name}', $$
                    MATCH path = (source:Dataset)-[:INPUT_TO*]->(:Run)-[:OUTPUTS*]->(target:Dataset {{dataset_id: '{dataset_id}'}})
                    RETURN path
                    LIMIT 1
                $$) AS (path agtype);
            """

            try:
                rows = await conn.fetch(cypher)
                if rows:
                    return self._parse_path(rows[0]["path"])
                return LineagePath(nodes=[], edges=[])
            except Exception as e:
                logger.error(f"Failed to get KB lineage: {e}")
                return LineagePath(nodes=[], edges=[])

    async def get_runs_for_dataset(
        self,
        dataset_namespace: str,
        dataset_name: str,
    ) -> list[LineageNode]:
        """Get all runs that used or produced a dataset.

        Args:
            dataset_namespace: Dataset namespace.
            dataset_name: Dataset name.

        Returns:
            List of Run nodes.
        """
        pool = await self._get_pool()
        dataset_id = f"{dataset_namespace}:{dataset_name}"

        async with pool.acquire() as conn:
            await conn.execute("LOAD 'age'")
            await conn.execute("SET search_path = ag_catalog, \"$user\", public")

            cypher = f"""
                SELECT * FROM cypher('{self._graph_name}', $$
                    MATCH (d:Dataset {{dataset_id: '{dataset_id}'}})
                    MATCH (d)-[:INPUT_TO|OUTPUTS]-(r:Run)
                    RETURN DISTINCT r
                $$) AS (r agtype);
            """

            try:
                rows = await conn.fetch(cypher)
                return [self._parse_node(row["r"]) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get runs for dataset: {e}")
                return []

    def _parse_node(self, agtype: Any) -> LineageNode:
        """Parse an AGE node result."""
        import json

        # AGE returns nodes as JSON-like strings
        if isinstance(agtype, str):
            data = json.loads(agtype)
        else:
            data = agtype

        # Extract node type from label
        node_type = "Unknown"
        if "label" in data:
            node_type = data["label"]
        elif "Dataset" in str(data):
            node_type = "Dataset"
        elif "Run" in str(data):
            node_type = "Run"
        elif "Job" in str(data):
            node_type = "Job"

        # Get ID
        node_id = data.get("properties", {}).get("dataset_id") or \
                  data.get("properties", {}).get("run_id") or \
                  data.get("properties", {}).get("job_id") or \
                  str(data.get("id", ""))

        return LineageNode(
            node_type=node_type,
            id=node_id,
            properties=data.get("properties", {}),
        )

    def _parse_path(self, agtype: Any) -> LineagePath:
        """Parse an AGE path result."""
        import json

        if isinstance(agtype, str):
            data = json.loads(agtype)
        else:
            data = agtype

        nodes = []
        edges = []

        # AGE paths alternate between nodes and edges
        for i, element in enumerate(data.get("path", [])):
            if i % 2 == 0:
                nodes.append(self._parse_node(element))
            else:
                edges.append(self._parse_edge(element))

        return LineagePath(nodes=nodes, edges=edges)

    def _parse_edge(self, agtype: Any) -> LineageEdge:
        """Parse an AGE edge result."""
        import json

        if isinstance(agtype, str):
            data = json.loads(agtype)
        else:
            data = agtype

        return LineageEdge(
            edge_type=data.get("label", "Unknown"),
            from_id=str(data.get("start_id", "")),
            to_id=str(data.get("end_id", "")),
            properties=data.get("properties", {}),
        )

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
