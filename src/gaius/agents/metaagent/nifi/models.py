"""Pydantic models for NiFi REST API entities."""

from dataclasses import dataclass, field
import json
from typing import Any, Optional


@dataclass
class Position:
    """Position on the NiFi canvas."""

    x: float = 0.0
    y: float = 0.0


@dataclass
class Revision:
    """NiFi entity revision for optimistic locking."""

    version: int = 0
    client_id: Optional[str] = None


@dataclass
class ProcessorConfig:
    """Processor configuration properties."""

    properties: dict = field(default_factory=dict)
    scheduling_strategy: str = "TIMER_DRIVEN"
    scheduling_period: str = "0 sec"
    penalty_duration: str = "30 sec"
    yield_duration: str = "1 sec"
    run_duration_nanos: int = 0
    bulletin_level: str = "WARN"


@dataclass
class ProcessorComponent:
    """Processor component definition."""

    name: str
    type: str  # Full processor class name
    position: Position = field(default_factory=Position)
    config: ProcessorConfig = field(default_factory=ProcessorConfig)
    state: str = "STOPPED"
    id: Optional[str] = None
    parent_group_id: Optional[str] = None


@dataclass
class ConnectionComponent:
    """Connection between processors."""

    name: str
    source_id: str
    destination_id: str
    selected_relationships: list = field(default_factory=lambda: ["success"])
    id: Optional[str] = None
    parent_group_id: Optional[str] = None


@dataclass
class ProcessGroupComponent:
    """Process group container."""

    name: str
    position: Position = field(default_factory=Position)
    comments: str = ""
    id: Optional[str] = None
    parent_group_id: Optional[str] = None


# Standard NiFi processor types for ExternalStep representation
PROCESSOR_TYPES = {
    # Placeholder processor for visualization
    "placeholder": "org.apache.nifi.processors.standard.UpdateAttribute",
    # Alternative types for future execution
    "execute_script": "org.apache.nifi.processors.script.ExecuteScript",
    "invoke_http": "org.apache.nifi.processors.standard.InvokeHTTP",
    "execute_command": "org.apache.nifi.processors.standard.ExecuteStreamCommand",
    "generate": "org.apache.nifi.processors.standard.GenerateFlowFile",
    "log": "org.apache.nifi.processors.standard.LogAttribute",
    "route": "org.apache.nifi.processors.standard.RouteOnAttribute",
    "listen_otlp": "org.apache.nifi.processors.opentelemetry.ListenOTLP",
}


# =============================================================================
# State Capture Models (for NiFiStateManager oracle)
# =============================================================================


@dataclass
class ProcessorState:
    """Captured state of a processor for semantic comparison.

    Key design: Comparison by name/type, NOT by position or ID.
    The ID is captured for reference but not used in equality checks.
    """

    id: str
    name: str
    type: str
    state: str  # STOPPED, RUNNING, DISABLED
    properties: dict[str, Any] = field(default_factory=dict)
    relationships: list[str] = field(default_factory=list)

    def semantic_key(self) -> str:
        """Key for semantic comparison (name only)."""
        return self.name

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "state": self.state,
            "properties": self.properties,
            "relationships": self.relationships,
        }


@dataclass
class ConnectionState:
    """Captured state of a connection for semantic comparison.

    Key design: Comparison by source/dest names and relationships,
    NOT by position or ID.
    """

    id: str
    name: str
    source_id: str
    source_name: str
    destination_id: str
    destination_name: str
    selected_relationships: list[str] = field(default_factory=list)

    def semantic_key(self) -> str:
        """Key for semantic comparison.

        Format: source_name->dest_name[rel1,rel2,...]
        """
        rels = ",".join(sorted(self.selected_relationships))
        return f"{self.source_name}->{self.destination_name}[{rels}]"

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "destination_id": self.destination_id,
            "destination_name": self.destination_name,
            "selected_relationships": self.selected_relationships,
        }


@dataclass
class FlowState:
    """Complete captured state of a process group.

    This is the "ground truth" snapshot used by NiFiStateManager
    for comparison with expected state (BDD oracle pattern).
    """

    process_group_id: str
    process_group_name: str
    processors: list[ProcessorState] = field(default_factory=list)
    connections: list[ConnectionState] = field(default_factory=list)
    child_groups: list["FlowState"] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "process_group_id": self.process_group_id,
            "process_group_name": self.process_group_name,
            "processors": [p.to_dict() for p in self.processors],
            "connections": [c.to_dict() for c in self.connections],
            "child_groups": [g.to_dict() for g in self.child_groups],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict) -> "FlowState":
        """Deserialize from dictionary."""
        return cls(
            process_group_id=data["process_group_id"],
            process_group_name=data["process_group_name"],
            processors=[
                ProcessorState(
                    id=p["id"],
                    name=p["name"],
                    type=p["type"],
                    state=p["state"],
                    properties=p.get("properties", {}),
                    relationships=p.get("relationships", []),
                )
                for p in data.get("processors", [])
            ],
            connections=[
                ConnectionState(
                    id=c["id"],
                    name=c["name"],
                    source_id=c["source_id"],
                    source_name=c["source_name"],
                    destination_id=c["destination_id"],
                    destination_name=c["destination_name"],
                    selected_relationships=c.get("selected_relationships", []),
                )
                for c in data.get("connections", [])
            ],
            child_groups=[
                cls.from_dict(g) for g in data.get("child_groups", [])
            ],
        )


@dataclass
class ProcessorMismatch:
    """Details about a processor mismatch between expected and actual state."""

    name: str
    expected_type: Optional[str] = None
    actual_type: Optional[str] = None
    property_diffs: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    state_diff: Optional[tuple[str, str]] = None  # (expected, actual)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "expected_type": self.expected_type,
            "actual_type": self.actual_type,
            "property_diffs": {
                k: {"expected": v[0], "actual": v[1]}
                for k, v in self.property_diffs.items()
            },
            "state_diff": (
                {"expected": self.state_diff[0], "actual": self.state_diff[1]}
                if self.state_diff
                else None
            ),
        }


@dataclass
class ConnectionMismatch:
    """Details about a connection mismatch between expected and actual state."""

    semantic_key: str
    expected_relationships: Optional[list[str]] = None
    actual_relationships: Optional[list[str]] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "semantic_key": self.semantic_key,
            "expected_relationships": self.expected_relationships,
            "actual_relationships": self.actual_relationships,
        }


@dataclass
class SemanticDiff:
    """Result of comparing expected vs actual FlowState.

    This powers the BDD oracle: when the browser agent creates flow,
    we compare against the API-created ground truth using this diff.
    """

    # Processors
    missing_processors: list[str] = field(default_factory=list)  # names
    extra_processors: list[str] = field(default_factory=list)  # names
    processor_mismatches: list[ProcessorMismatch] = field(default_factory=list)

    # Connections
    missing_connections: list[str] = field(default_factory=list)  # semantic keys
    extra_connections: list[str] = field(default_factory=list)  # semantic keys
    connection_mismatches: list[ConnectionMismatch] = field(default_factory=list)

    # Child groups (recursive comparison)
    child_group_diffs: dict[str, "SemanticDiff"] = field(default_factory=dict)

    @property
    def is_match(self) -> bool:
        """True if expected and actual states are semantically equivalent."""
        return (
            not self.missing_processors
            and not self.extra_processors
            and not self.processor_mismatches
            and not self.missing_connections
            and not self.extra_connections
            and not self.connection_mismatches
            and all(d.is_match for d in self.child_group_diffs.values())
        )

    @property
    def accuracy(self) -> float:
        """Calculate accuracy as ratio of matching elements.

        Returns value between 0.0 (nothing matches) and 1.0 (perfect match).
        """
        total_issues = (
            len(self.missing_processors)
            + len(self.extra_processors)
            + len(self.processor_mismatches)
            + len(self.missing_connections)
            + len(self.extra_connections)
            + len(self.connection_mismatches)
        )

        if total_issues == 0:
            return 1.0

        # Estimate total expected elements
        # This is approximate - better to track expected counts explicitly
        total_expected = total_issues + 10  # Assume some baseline
        return max(0.0, 1.0 - (total_issues / total_expected))

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "is_match": self.is_match,
            "accuracy": self.accuracy,
            "missing_processors": self.missing_processors,
            "extra_processors": self.extra_processors,
            "processor_mismatches": [m.to_dict() for m in self.processor_mismatches],
            "missing_connections": self.missing_connections,
            "extra_connections": self.extra_connections,
            "connection_mismatches": [m.to_dict() for m in self.connection_mismatches],
            "child_group_diffs": {
                k: v.to_dict() for k, v in self.child_group_diffs.items()
            },
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
