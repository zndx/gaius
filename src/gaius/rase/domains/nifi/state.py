"""NiFi System State Model.

Defines the typed graph structure for NiFi instances, implementing
the generic SystemState protocol from gaius.rase.core.

Maps to SysML v2:
    part def NiFiInstance {
        attribute baseUrl : String;
        part root : ProcessorGroup;
    }

    part def ProcessorGroup {
        attribute name : String;
        part groups : ProcessorGroup[*];
        part processors : Processor[*];
        part connections : FlowConnection[*];
    }

This module provides the "API truth" representation - the canonical state
as reported by the NiFi REST API, against which UI agent actions are verified.

Design principles:
1. Semantic identity: Elements identified by name/type, not position or UUID
2. Immutable snapshots: State objects are frozen for safe comparison
3. Hierarchical: Recursive ProcessorGroup structure for nested flows
4. Serializable: Full JSON round-trip for persistence and transmission
5. Protocol-compliant: Implements SystemState for generic verification
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from gaius.rase.traceability import TraceableId, IdScheme


class ProcessorRunState(str, Enum):
    """Runtime state of a NiFi processor.

    NiFi processors transition through these states during operation.
    """

    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    DISABLED = "DISABLED"
    INVALID = "INVALID"
    VALIDATING = "VALIDATING"


# Backward compatibility alias
ProcessorState = ProcessorRunState


class Processor(BaseModel):
    """A NiFi processor node.

    Maps to SysML v2:
        part def Processor {
            attribute name : String;
            attribute nifiType : String;
            attribute runState : ProcessorState;
        }

    Attributes:
        id: NiFi-assigned UUID (for API operations)
        name: Human-readable name (semantic identity)
        nifi_type: Fully qualified processor class name
        run_state: Current runtime state
        properties: Configuration properties
        relationships: Available output relationships
        comments: Optional documentation
    """

    id: str
    name: str
    nifi_type: str
    run_state: ProcessorRunState = ProcessorRunState.STOPPED
    properties: dict[str, Any] = Field(default_factory=dict)
    relationships: list[str] = Field(default_factory=list)
    comments: str = ""

    # Position on canvas (for UI correlation, not semantic identity)
    position_x: float = 0.0
    position_y: float = 0.0

    model_config = {"frozen": True}

    @property
    def semantic_key(self) -> str:
        """Key for semantic comparison (name only).

        Position and UUID are NOT part of semantic identity.
        Two processors are semantically equivalent if they have
        the same name and type.
        """
        return self.name

    @property
    def type_short_name(self) -> str:
        """Short form of processor type (class name only)."""
        return self.nifi_type.split(".")[-1]

    def to_traceable_id(self, parent_group_id: str) -> TraceableId:
        """Generate a TraceableId for this processor."""
        return TraceableId.from_nifi(
            process_group_id=parent_group_id,
            processor_id=self.id,
        )


class FlowConnection(BaseModel):
    """A connection between NiFi processors.

    Maps to SysML v2:
        connection def FlowConnection {
            end part source : Processor;
            end part target : Processor;
            attribute relationship : String;
        }

    Semantic identity is based on source/destination names and relationships,
    NOT on connection UUID or routing path.

    Attributes:
        id: NiFi-assigned UUID
        name: Optional connection name
        source_id: Source processor UUID
        source_name: Source processor name (for semantic comparison)
        destination_id: Destination processor UUID
        destination_name: Destination processor name
        selected_relationships: Which relationships are routed
        backpressure_bytes: Backpressure threshold (bytes)
        backpressure_count: Backpressure threshold (FlowFile count)
    """

    id: str
    name: str = ""
    source_id: str
    source_name: str
    destination_id: str
    destination_name: str
    selected_relationships: list[str] = Field(default_factory=list)
    backpressure_bytes: int = 1_000_000_000  # 1GB default
    backpressure_count: int = 10_000

    # Runtime metrics (for operational constraints)
    queued_count: int = 0
    queued_bytes: int = 0

    model_config = {"frozen": True}

    @property
    def semantic_key(self) -> str:
        """Key for semantic comparison.

        Format: source_name->destination_name[rel1,rel2,...]
        """
        rels = ",".join(sorted(self.selected_relationships))
        return f"{self.source_name}->{self.destination_name}[{rels}]"

    @property
    def is_backpressured(self) -> bool:
        """Check if connection has backpressure."""
        return (
            self.queued_count >= self.backpressure_count
            or self.queued_bytes >= self.backpressure_bytes
        )


class ControllerService(BaseModel):
    """A NiFi controller service (shared resource).

    Controller services provide shared functionality across processors
    (e.g., database connection pools, SSL contexts).

    Attributes:
        id: NiFi-assigned UUID
        name: Human-readable name
        nifi_type: Fully qualified service class name
        state: Runtime state (ENABLED/DISABLED)
        properties: Configuration properties
    """

    id: str
    name: str
    nifi_type: str
    state: str = "DISABLED"
    properties: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}

    @property
    def semantic_key(self) -> str:
        """Semantic identity key."""
        return self.name


class ProcessorGroup(BaseModel):
    """A NiFi process group (container for flow components).

    Maps to SysML v2:
        part def ProcessorGroup {
            attribute name : String;
            part groups : ProcessorGroup[*];
            part processors : Processor[*];
            part connections : FlowConnection[*];
        }

    Process groups are hierarchical - they can contain nested groups
    for organizational purposes.

    Attributes:
        id: NiFi-assigned UUID
        name: Human-readable name (semantic identity)
        comments: Documentation
        processors: Child processors
        connections: Connections between processors
        child_groups: Nested process groups
        controller_services: Scoped controller services
    """

    id: str
    name: str
    comments: str = ""
    processors: list[Processor] = Field(default_factory=list)
    connections: list[FlowConnection] = Field(default_factory=list)
    child_groups: list["ProcessorGroup"] = Field(default_factory=list)
    controller_services: list[ControllerService] = Field(default_factory=list)

    # Position on parent canvas
    position_x: float = 0.0
    position_y: float = 0.0

    model_config = {"frozen": True}

    @property
    def semantic_key(self) -> str:
        """Semantic identity key."""
        return self.name

    def get_processor(self, name: str) -> Processor | None:
        """Find processor by name."""
        for proc in self.processors:
            if proc.name == name:
                return proc
        return None

    def get_processor_by_id(self, proc_id: str) -> Processor | None:
        """Find processor by ID."""
        for proc in self.processors:
            if proc.id == proc_id:
                return proc
        return None

    def get_child_group(self, name: str) -> "ProcessorGroup" | None:
        """Find child group by name."""
        for group in self.child_groups:
            if group.name == name:
                return group
        return None

    def get_connection(
        self,
        source_name: str,
        dest_name: str,
    ) -> FlowConnection | None:
        """Find connection by source and destination names."""
        for conn in self.connections:
            if conn.source_name == source_name and conn.destination_name == dest_name:
                return conn
        return None

    def all_processors(self, recursive: bool = True) -> list[Processor]:
        """Get all processors, optionally including nested groups."""
        result = list(self.processors)
        if recursive:
            for child in self.child_groups:
                result.extend(child.all_processors(recursive=True))
        return result

    def all_connections(self, recursive: bool = True) -> list[FlowConnection]:
        """Get all connections, optionally including nested groups."""
        result = list(self.connections)
        if recursive:
            for child in self.child_groups:
                result.extend(child.all_connections(recursive=True))
        return result

    def to_traceable_id(self, parent_id: str | None = None) -> TraceableId:
        """Generate a TraceableId for this group."""
        return TraceableId.from_nifi(process_group_id=self.id)


class NiFiInstance(BaseModel):
    """Top-level NiFi instance state.

    Maps to SysML v2:
        part def NiFiInstance {
            attribute baseUrl : String;
            part root : ProcessorGroup;
        }

    This is the entry point for SSM state capture - it represents
    a complete snapshot of the NiFi instance at a point in time.

    Implements the SystemState protocol from gaius.rase.core:
    - captured_at: timestamp of state capture
    - to_traceable_id(): generate TraceableId
    - get_component(path): navigate to component by path

    Attributes:
        base_url: NiFi API endpoint
        root: Root process group containing all flows
        captured_at: Timestamp of state capture
        cluster_id: NiFi cluster identifier (if clustered)
    """

    base_url: str
    root: ProcessorGroup
    captured_at: datetime = Field(default_factory=datetime.now)
    cluster_id: str | None = None

    model_config = {"frozen": True}

    # --- SystemState protocol implementation ---

    def to_traceable_id(self) -> TraceableId:
        """Generate a TraceableId for this state snapshot.

        Required by SystemState protocol.
        """
        return TraceableId.from_rase(
            artifact_type="ssm_snapshot",
            artifact_id=f"{self.cluster_id or 'local'}_{self.captured_at.isoformat()}",
        )

    def get_component(self, path: str) -> Any | None:
        """Navigate to a component by path.

        Required by SystemState protocol.

        Args:
            path: Dot-separated or slash-separated path to component
                  (e.g., "root.processors.GetFile" or "root/GroupA/SubGroup")

        Returns:
            The component at the path, or None if not found
        """
        # Support both dot and slash separators
        parts = path.replace(".", "/").split("/")
        parts = [p for p in parts if p]  # Remove empty parts

        if not parts:
            return self.root

        current: Any = self.root

        for part in parts:
            if part == "root":
                continue

            if isinstance(current, ProcessorGroup):
                # Try processors first
                proc = current.get_processor(part)
                if proc:
                    current = proc
                    continue

                # Try child groups
                group = current.get_child_group(part)
                if group:
                    current = group
                    continue

                # Try by key (e.g., "processors", "connections")
                if part == "processors":
                    return current.processors
                elif part == "connections":
                    return current.connections
                elif part == "child_groups":
                    return current.child_groups

                return None

        return current

    # --- Original methods ---

    def get_group(self, path: str) -> ProcessorGroup | None:
        """Find process group by path (e.g., 'root/GroupA/SubGroup').

        Path components are matched by name.
        """
        parts = path.split("/")
        current = self.root

        for part in parts:
            if part in ("", "root"):
                continue
            found = current.get_child_group(part)
            if found is None:
                return None
            current = found

        return current


# --- Utility functions for state comparison ---


def semantic_processor_match(a: Processor, b: Processor) -> bool:
    """Check if two processors are semantically equivalent.

    Semantic equivalence considers:
    - Name (exact match)
    - Type (exact match)
    - Properties (subset match for essential properties)

    Does NOT consider:
    - Position on canvas
    - NiFi-assigned UUID
    - Runtime state (RUNNING vs STOPPED)
    """
    if a.name != b.name:
        return False
    if a.nifi_type != b.nifi_type:
        return False
    # Properties: a should be subset of b (or vice versa)
    # This allows for default property values to differ
    return True


def semantic_connection_match(a: FlowConnection, b: FlowConnection) -> bool:
    """Check if two connections are semantically equivalent."""
    return a.semantic_key == b.semantic_key


def semantic_group_match(
    expected: ProcessorGroup,
    actual: ProcessorGroup,
    recursive: bool = True,
) -> tuple[bool, list[str]]:
    """Compare two process groups for semantic equivalence.

    Returns:
        Tuple of (is_match, list of difference descriptions)
    """
    differences: list[str] = []

    # Compare processors by semantic key
    expected_procs = {p.semantic_key: p for p in expected.processors}
    actual_procs = {p.semantic_key: p for p in actual.processors}

    for key in expected_procs:
        if key not in actual_procs:
            differences.append(f"Missing processor: {key}")
        elif not semantic_processor_match(expected_procs[key], actual_procs[key]):
            differences.append(f"Processor mismatch: {key}")

    for key in actual_procs:
        if key not in expected_procs:
            differences.append(f"Extra processor: {key}")

    # Compare connections by semantic key
    expected_conns = {c.semantic_key: c for c in expected.connections}
    actual_conns = {c.semantic_key: c for c in actual.connections}

    for key in expected_conns:
        if key not in actual_conns:
            differences.append(f"Missing connection: {key}")

    for key in actual_conns:
        if key not in expected_conns:
            differences.append(f"Extra connection: {key}")

    # Recursive comparison of child groups
    if recursive:
        expected_groups = {g.name: g for g in expected.child_groups}
        actual_groups = {g.name: g for g in actual.child_groups}

        for name in expected_groups:
            if name not in actual_groups:
                differences.append(f"Missing group: {name}")
            else:
                _, child_diffs = semantic_group_match(
                    expected_groups[name],
                    actual_groups[name],
                    recursive=True,
                )
                differences.extend(f"{name}/{d}" for d in child_diffs)

        for name in actual_groups:
            if name not in expected_groups:
                differences.append(f"Extra group: {name}")

    return (len(differences) == 0, differences)


__all__ = [
    "ProcessorRunState",
    "ProcessorState",  # Backward compatibility alias
    "Processor",
    "FlowConnection",
    "ControllerService",
    "ProcessorGroup",
    "NiFiInstance",
    "semantic_processor_match",
    "semantic_connection_match",
    "semantic_group_match",
]
