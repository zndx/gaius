"""Lineage Emitter - Store events and update AGE graph.

Handles:
1. Storing OpenLineage events in PostgreSQL lineage_events table
2. Optionally materializing events to Apache AGE graph
3. Context manager for tracking job runs
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator
from uuid import UUID

if TYPE_CHECKING:
    import asyncpg

from gaius.hx.lineage.events import (
    Dataset,
    Job,
    Run,
    RunEvent,
    RunState,
)

logger = logging.getLogger(__name__)


# Module-level singleton
_emitter: LineageEmitter | None = None


class LineageEmitter:
    """Emit OpenLineage events to storage and graph.

    Thread-safe emitter that stores events in PostgreSQL
    and optionally materializes to Apache AGE graph.
    """

    def __init__(
        self,
        database_url: str | None = None,
        graph_name: str = "gaius_hx",
        materialize_graph: bool = True,
    ):
        """Initialize the emitter.

        Args:
            database_url: PostgreSQL connection URL. If None, loads from config.
            graph_name: Name of the AGE graph for lineage.
            materialize_graph: Whether to write to AGE graph (requires AGE extension).
        """
        self._database_url = database_url
        self._graph_name = graph_name
        self._materialize_graph = materialize_graph
        self._pool: asyncpg.Pool | None = None
        self._age_available: bool | None = None

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

    async def _check_age_available(self) -> bool:
        """Check if Apache AGE extension is available."""
        if self._age_available is None:
            try:
                pool = await self._get_pool()
                async with pool.acquire() as conn:
                    result = await conn.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'age')"
                    )
                    self._age_available = bool(result)
            except Exception as e:
                logger.warning(f"Could not check AGE availability: {e}")
                self._age_available = False

        return self._age_available

    async def emit(self, event: RunEvent) -> int | None:
        """Emit a lineage event.

        Stores the event in PostgreSQL and optionally updates AGE graph.

        Args:
            event: RunEvent to emit.

        Returns:
            Event ID if stored successfully, None otherwise.
        """
        try:
            # Store in PostgreSQL
            event_id = await self._store_event(event)

            # Optionally materialize to AGE graph
            if self._materialize_graph and await self._check_age_available():
                await self._update_graph(event)

            return event_id

        except Exception as e:
            logger.error(f"Failed to emit lineage event: {e}")
            return None

    async def _store_event(self, event: RunEvent) -> int:
        """Store event in lineage_events table.

        Args:
            event: RunEvent to store.

        Returns:
            Event ID.
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            event_id = await conn.fetchval(
                """
                INSERT INTO lineage_events (
                    event_type,
                    event_time,
                    run_id,
                    job_namespace,
                    job_name,
                    run_state,
                    inputs,
                    outputs,
                    facets,
                    parent_run_id
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
                """,
                event.event_type,
                event.event_time,
                event.run.run_id,
                event.job.namespace,
                event.job.name,
                event.run_state.value,
                json.dumps([d.to_dict() for d in event.inputs]),
                json.dumps([d.to_dict() for d in event.outputs]),
                json.dumps(event.run.facets.to_dict()),
                self._get_parent_run_id(event),
            )

        logger.debug(
            f"Stored lineage event {event_id}: "
            f"{event.job.namespace}.{event.job.name} "
            f"[{event.run_state.value}]"
        )

        return event_id

    async def _update_graph(self, event: RunEvent) -> None:
        """Update AGE graph with event data.

        Creates/updates vertices and edges for:
        - Dataset vertices for inputs/outputs
        - Job vertex
        - Run vertex
        - INPUT_TO edges (Dataset -> Run)
        - OUTPUTS edges (Run -> Dataset)
        - EXECUTES edges (Job -> Run)

        Args:
            event: RunEvent to materialize.
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            # Set search path for AGE - LOAD 'age' requires superuser, but
            # setting search_path is sufficient when AGE is installed as extension
            await conn.execute("SET search_path = ag_catalog, \"$user\", public")

            # Create Run vertex
            await self._create_run_vertex(conn, event)

            # Create Job vertex and EXECUTES edge
            await self._create_job_vertex(conn, event)

            # Create Dataset vertices and edges for inputs
            for dataset in event.inputs:
                await self._create_dataset_vertex(conn, dataset)
                await self._create_input_edge(conn, dataset, event.run)

            # Create Dataset vertices and edges for outputs
            for dataset in event.outputs:
                await self._create_dataset_vertex(conn, dataset)
                await self._create_output_edge(conn, event.run, dataset)

        logger.debug(f"Updated AGE graph for run {event.run.run_id}")

    async def _create_run_vertex(
        self,
        conn: asyncpg.Connection,
        event: RunEvent,
    ) -> None:
        """Create or update Run vertex."""
        cypher = f"""
            SELECT * FROM cypher('{self._graph_name}', $$
                MERGE (r:Run {{run_id: '{event.run.run_id}'}})
                SET r.state = '{event.run_state.value}',
                    r.event_time = '{event.event_time.isoformat()}',
                    r.job_namespace = '{event.job.namespace}',
                    r.job_name = '{event.job.name}'
                RETURN r
            $$) AS (r agtype);
        """
        await conn.execute(cypher)

    async def _create_job_vertex(
        self,
        conn: asyncpg.Connection,
        event: RunEvent,
    ) -> None:
        """Create Job vertex and EXECUTES edge."""
        job_id = f"{event.job.namespace}.{event.job.name}"

        # Create Job vertex
        cypher = f"""
            SELECT * FROM cypher('{self._graph_name}', $$
                MERGE (j:Job {{job_id: '{job_id}'}})
                SET j.namespace = '{event.job.namespace}',
                    j.name = '{event.job.name}'
                RETURN j
            $$) AS (j agtype);
        """
        await conn.execute(cypher)

        # Create EXECUTES edge
        cypher = f"""
            SELECT * FROM cypher('{self._graph_name}', $$
                MATCH (j:Job {{job_id: '{job_id}'}})
                MATCH (r:Run {{run_id: '{event.run.run_id}'}})
                MERGE (j)-[e:EXECUTES]->(r)
                RETURN e
            $$) AS (e agtype);
        """
        await conn.execute(cypher)

    async def _create_dataset_vertex(
        self,
        conn: asyncpg.Connection,
        dataset: Dataset,
    ) -> None:
        """Create Dataset vertex."""
        dataset_id = f"{dataset.namespace}:{dataset.name}"

        cypher = f"""
            SELECT * FROM cypher('{self._graph_name}', $$
                MERGE (d:Dataset {{dataset_id: '{dataset_id}'}})
                SET d.namespace = '{dataset.namespace}',
                    d.name = '{dataset.name}'
                RETURN d
            $$) AS (d agtype);
        """
        await conn.execute(cypher)

    async def _create_input_edge(
        self,
        conn: asyncpg.Connection,
        dataset: Dataset,
        run: Run,
    ) -> None:
        """Create INPUT_TO edge (Dataset -> Run)."""
        dataset_id = f"{dataset.namespace}:{dataset.name}"

        cypher = f"""
            SELECT * FROM cypher('{self._graph_name}', $$
                MATCH (d:Dataset {{dataset_id: '{dataset_id}'}})
                MATCH (r:Run {{run_id: '{run.run_id}'}})
                MERGE (d)-[e:INPUT_TO]->(r)
                RETURN e
            $$) AS (e agtype);
        """
        await conn.execute(cypher)

    async def _create_output_edge(
        self,
        conn: asyncpg.Connection,
        run: Run,
        dataset: Dataset,
    ) -> None:
        """Create OUTPUTS edge (Run -> Dataset)."""
        dataset_id = f"{dataset.namespace}:{dataset.name}"

        cypher = f"""
            SELECT * FROM cypher('{self._graph_name}', $$
                MATCH (r:Run {{run_id: '{run.run_id}'}})
                MATCH (d:Dataset {{dataset_id: '{dataset_id}'}})
                MERGE (r)-[e:OUTPUTS]->(d)
                RETURN e
            $$) AS (e agtype);
        """
        await conn.execute(cypher)

    def _get_parent_run_id(self, event: RunEvent) -> UUID | None:
        """Extract parent run ID from event facets."""
        parent = event.run.facets.parent_run
        if parent and "run" in parent:
            run_id = parent["run"].get("runId")
            if run_id:
                return UUID(run_id)
        return None

    @asynccontextmanager
    async def track_run(
        self,
        job: Job,
        inputs: list[Dataset],
        parent_run_id: UUID | None = None,
    ) -> AsyncIterator[Run]:
        """Context manager for tracking a job run.

        Automatically emits START and COMPLETE/FAIL events.

        Args:
            job: Job being executed.
            inputs: Input datasets.
            parent_run_id: Optional parent run for nested execution.

        Yields:
            Run object that can be used to record outputs.

        Example:
            async with emitter.track_run(Job.fetch("arxiv"), inputs) as run:
                # Do work...
                run.outputs = [Dataset.from_hx(content_id)]
        """
        if parent_run_id:
            run = Run.with_parent(parent_run_id)
        else:
            run = Run()

        # Emit START event
        start_event = RunEvent.start(job, inputs, run)
        await self.emit(start_event)

        outputs: list[Dataset] = []

        try:
            # Yield run for caller to populate outputs
            yield run
            outputs = getattr(run, "_outputs", [])

            # Emit COMPLETE event
            complete_event = RunEvent.complete(run, job, inputs, outputs)
            await self.emit(complete_event)

        except Exception as e:
            # Emit FAIL event
            fail_event = RunEvent.fail(run, job, inputs, str(e))
            await self.emit(fail_event)
            raise

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None


def get_emitter(
    database_url: str | None = None,
    force_new: bool = False,
) -> LineageEmitter:
    """Get the global LineageEmitter singleton.

    Args:
        database_url: Optional database URL override.
        force_new: If True, create a new emitter.

    Returns:
        LineageEmitter instance.
    """
    global _emitter

    if _emitter is None or force_new:
        from gaius.hx.config import get_hx_config

        config = get_hx_config()
        _emitter = LineageEmitter(
            database_url=database_url or config.database_url,
            graph_name=config.lineage_graph_name,
            materialize_graph=config.materialize_graph,
        )

    return _emitter


def reset_emitter() -> None:
    """Reset the emitter singleton (for testing)."""
    global _emitter
    _emitter = None
