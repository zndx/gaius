"""Project Metaflow flows onto NiFi canvas.

This module provides visualization-only projection of Metaflow DAGs
onto the NiFi canvas. Each Metaflow step becomes a placeholder processor
(UpdateAttribute) with connections representing step transitions.

The NiFi flows serve as a visual monitoring interface - actual execution
happens in Metaflow, not NiFi.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Type

from .client import NiFiClient
from .models import Position, ProcessorConfig, PROCESSOR_TYPES
from ..config import NiFiConfig

logger = logging.getLogger(__name__)


@dataclass
class StepInfo:
    """Information about a Metaflow step."""

    name: str
    decorators: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    docstring: str = ""
    is_start: bool = False
    is_end: bool = False


@dataclass
class FlowInfo:
    """Information about a Metaflow flow."""

    name: str
    module: str
    steps: dict[str, StepInfo] = field(default_factory=dict)
    dag_edges: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class ProjectionResult:
    """Result of projecting a flow to NiFi."""

    flow_name: str
    process_group_id: str
    processor_ids: dict[str, str]  # step_name -> processor_id
    connection_ids: list[str]
    nifi_url: str


class MetaflowParser:
    """Parse Metaflow flow classes to extract DAG structure."""

    def parse_flow(self, flow_class: Type) -> FlowInfo:
        """Parse a Metaflow flow class to extract structure.

        Args:
            flow_class: A Metaflow FlowSpec subclass

        Returns:
            FlowInfo with step names and DAG edges
        """
        import ast
        import inspect

        steps = {}
        dag_edges = []

        # Get all methods
        for name, method in inspect.getmembers(flow_class, predicate=inspect.isfunction):
            # Check if method has @step decorator or is start/end
            is_step = hasattr(method, "is_step") or name in ("start", "end")

            if is_step:
                # Parse next() calls from source
                next_steps = self._parse_next_calls(method)

                steps[name] = StepInfo(
                    name=name,
                    next_steps=next_steps,
                    docstring=method.__doc__ or "",
                    is_start=(name == "start"),
                    is_end=(name == "end"),
                    decorators=self._get_decorators(method),
                )

                # Add DAG edges
                for next_step in next_steps:
                    dag_edges.append((name, next_step))

        return FlowInfo(
            name=flow_class.__name__,
            module=flow_class.__module__,
            steps=steps,
            dag_edges=dag_edges,
        )

    def _parse_next_calls(self, method) -> list[str]:
        """Parse self.next() calls from method source to find transitions."""
        import ast
        import inspect

        next_steps = []

        try:
            source = inspect.getsource(method)
            tree = ast.parse(source)

            for node in ast.walk(tree):
                # Look for self.next(self.step_name) calls
                if isinstance(node, ast.Call):
                    if (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr == "next"
                        and node.args
                    ):
                        arg = node.args[0]
                        if isinstance(arg, ast.Attribute):
                            next_steps.append(arg.attr)
        except Exception as e:
            logger.debug(f"Could not parse {method.__name__}: {e}")

        return next_steps

    def _get_decorators(self, method) -> list[str]:
        """Extract decorator names from method."""
        decorators = []

        # Check common Metaflow decorators
        if hasattr(method, "is_step"):
            decorators.append("@step")
        if hasattr(method, "_retry_decorator"):
            decorators.append("@retry")
        if hasattr(method, "_card_decorator"):
            decorators.append("@card")
        if hasattr(method, "_kubernetes_decorator"):
            decorators.append("@kubernetes")

        return decorators


class MetaflowToNiFiProjector:
    """Project Metaflow flows onto NiFi canvas.

    Creates visual representations of Metaflow DAGs in NiFi using
    placeholder processors. This is visualization only - no execution.
    """

    def __init__(
        self,
        nifi_config: Optional[NiFiConfig] = None,
        parser: Optional[MetaflowParser] = None,
    ):
        self.nifi_config = nifi_config or NiFiConfig()
        self.parser = parser or MetaflowParser()

    async def project_flow(
        self,
        flow_class: Type,
        parent_group_id: Optional[str] = None,
        layout: str = "horizontal",
    ) -> ProjectionResult:
        """Project a Metaflow flow to NiFi.

        Args:
            flow_class: Metaflow FlowSpec subclass to project
            parent_group_id: NiFi process group ID (None = root)
            layout: Layout direction ("horizontal" or "vertical")

        Returns:
            ProjectionResult with created NiFi element IDs
        """
        async with NiFiClient(self.nifi_config) as client:
            # Parse the flow
            flow_info = self.parser.parse_flow(flow_class)
            logger.info(f"Parsed flow {flow_info.name} with {len(flow_info.steps)} steps")

            # Get root process group if not specified
            if parent_group_id is None:
                root = await client.get_root_process_group()
                parent_group_id = root["processGroupFlow"]["id"]

            # Create a process group for this flow
            process_group = await client.create_process_group(
                parent_id=parent_group_id,
                name=f"Metaflow: {flow_info.name}",
                position=Position(x=100, y=100),
                comments=f"Projected from Metaflow flow: {flow_info.module}.{flow_info.name}",
            )
            pg_id = process_group["id"]

            # Calculate positions based on DAG structure
            positions = self._calculate_positions(flow_info, layout)

            # Create processors for each step
            processor_ids = {}
            for step_name, step_info in flow_info.steps.items():
                pos = positions.get(step_name, Position(x=0, y=0))

                # Create processor with step metadata
                config = ProcessorConfig(
                    properties={
                        "metaflow.step_name": step_name,
                        "metaflow.flow_name": flow_info.name,
                        "metaflow.is_start": str(step_info.is_start).lower(),
                        "metaflow.is_end": str(step_info.is_end).lower(),
                        "metaflow.decorators": ",".join(step_info.decorators),
                    }
                )

                processor = await client.create_processor(
                    process_group_id=pg_id,
                    processor_type=PROCESSOR_TYPES["placeholder"],
                    name=step_name,
                    position=pos,
                    config=config,
                )
                processor_ids[step_name] = processor["id"]
                logger.debug(f"Created processor for step: {step_name}")

            # Create connections based on DAG edges
            connection_ids = []
            for source, dest in flow_info.dag_edges:
                if source in processor_ids and dest in processor_ids:
                    conn = await client.create_connection(
                        process_group_id=pg_id,
                        source_id=processor_ids[source],
                        dest_id=processor_ids[dest],
                        relationships=["success"],
                        name=f"{source} -> {dest}",
                    )
                    connection_ids.append(conn["id"])
                    logger.debug(f"Created connection: {source} -> {dest}")

            logger.info(
                f"Projected {flow_info.name}: {len(processor_ids)} processors, "
                f"{len(connection_ids)} connections"
            )

            return ProjectionResult(
                flow_name=flow_info.name,
                process_group_id=pg_id,
                processor_ids=processor_ids,
                connection_ids=connection_ids,
                nifi_url=f"{self.nifi_config.base_url.replace('/nifi-api', '')}/nifi/?processGroupId={pg_id}",
            )

    def _calculate_positions(
        self, flow_info: FlowInfo, layout: str
    ) -> dict[str, Position]:
        """Calculate processor positions based on DAG structure."""
        positions = {}

        # Topological levels
        levels = self._topological_levels(flow_info)

        # Spacing
        x_spacing = 350 if layout == "horizontal" else 0
        y_spacing = 150 if layout == "vertical" else 0

        # Group steps by level for vertical offset
        steps_per_level: dict[int, list[str]] = {}
        for step_name, level in levels.items():
            if level not in steps_per_level:
                steps_per_level[level] = []
            steps_per_level[level].append(step_name)

        # Assign positions
        for step_name, level in levels.items():
            level_steps = steps_per_level[level]
            idx = level_steps.index(step_name)

            if layout == "horizontal":
                x = 100 + level * x_spacing
                y = 100 + idx * 120  # Offset for parallel steps
            else:
                x = 100 + idx * 200
                y = 100 + level * y_spacing

            positions[step_name] = Position(x=x, y=y)

        return positions

    def _topological_levels(self, flow_info: FlowInfo) -> dict[str, int]:
        """Compute topological levels for DAG layout."""
        # Build adjacency list
        adj: dict[str, list[str]] = {s: [] for s in flow_info.steps}
        for src, dst in flow_info.dag_edges:
            if src in adj:
                adj[src].append(dst)

        # BFS from start to assign levels
        levels = {}
        queue = ["start"] if "start" in flow_info.steps else []
        visited = set()

        level = 0
        while queue:
            next_queue = []
            for step in queue:
                if step not in visited:
                    visited.add(step)
                    levels[step] = level
                    next_queue.extend(adj.get(step, []))
            queue = next_queue
            level += 1

        # Assign level 0 to any unvisited steps (orphans)
        for step in flow_info.steps:
            if step not in levels:
                levels[step] = 0

        return levels
