"""Pydantic models for NiFi REST API entities."""

from dataclasses import dataclass, field
from typing import Optional


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
}
