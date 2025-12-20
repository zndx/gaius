"""Traceability infrastructure for RASE metamodel.

This module provides the "digital thread" that links all RASE artifacts:
- BDD requirements → Verification cases → Execution evidence → Training samples

The TraceableId is the fundamental unit of cross-model linking, mirroring
SysML v2's human id pattern: <'scheme:path'>

Architecture:
    ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
    │     OSM     │────▶│     VM      │────▶│   Evidence  │
    │ (Scenarios) │     │(Verification│     │ (Results +  │
    └─────────────┘     │   Cases)    │     │ Screenshots)│
           │            └─────────────┘     └─────────────┘
           │                   │                   │
           ▼                   ▼                   ▼
    ┌─────────────────────────────────────────────────────┐
    │              TraceableId (Digital Thread)           │
    │  <'bdd:features/X.feature#Scenario:Y/L42:When'>     │
    └─────────────────────────────────────────────────────┘

Reference:
    SysML v2 human id: <'identifier'> pattern for requirements and elements.
    See: X_rase-mbse-perspective_02.md section 8.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class IdScheme(str, Enum):
    """Scheme prefixes for TraceableId.

    Each scheme represents a namespace in the RASE metamodel:
    - bdd: BDD features, scenarios, steps
    - otel: OpenTelemetry spans and events
    - nifi: NiFi processors, groups, connections
    - metaflow: Metaflow runs, steps, tasks
    - rase: RASE-internal artifacts (verification results, etc.)
    - som: Set-of-Mark UI annotations
    - tom: Trace-of-Mark action sequences
    """
    BDD = "bdd"
    OTEL = "otel"
    NIFI = "nifi"
    METAFLOW = "metaflow"
    RASE = "rase"
    SOM = "som"
    TOM = "tom"


class TraceableId(BaseModel):
    """Unique identifier with scheme for cross-model traceability.

    Mirrors SysML v2 human id pattern: <'bdd:features/X.feature#Scenario:Y'>

    The path component uses a hierarchical structure:
    - For BDD: features/{file}#Scenario:{name}/L{line}:{step_type}
    - For OTel: spans/{trace_id}/{span_id}
    - For NiFi: groups/{pg_id}/processors/{proc_id}
    - For Metaflow: flows/{flow_name}/runs/{run_id}/steps/{step_name}

    Examples:
        >>> TraceableId.from_bdd("nifi_flow.feature", scenario="CreateBasicFlow")
        TraceableId(scheme='bdd', path='features/nifi_flow.feature#Scenario:CreateBasicFlow')

        >>> TraceableId.from_otel(trace_id="abc123", span_id="def456")
        TraceableId(scheme='otel', path='spans/abc123/def456')

    Attributes:
        scheme: The namespace scheme (bdd, otel, nifi, metaflow, rase)
        path: Hierarchical path within the scheme
        version: Optional version for temporal tracking
    """

    scheme: IdScheme
    path: str
    version: str | None = None

    model_config = {"frozen": True}  # Immutable for use as dict key

    def __str__(self) -> str:
        """SysML v2-style human id representation."""
        base = f"<'{self.scheme.value}:{self.path}'>"
        if self.version:
            base = f"{base}@{self.version}"
        return base

    def __hash__(self) -> int:
        return hash((self.scheme, self.path, self.version))

    @property
    def short_id(self) -> str:
        """Short form for display (last path component)."""
        parts = self.path.split("/")
        return parts[-1] if parts else self.path

    @property
    def uri(self) -> str:
        """URI form for serialization."""
        base = f"{self.scheme.value}://{self.path}"
        if self.version:
            base = f"{base}?v={self.version}"
        return base

    @classmethod
    def from_uri(cls, uri: str) -> "TraceableId":
        """Parse from URI form."""
        match = re.match(r"(\w+)://(.+?)(?:\?v=(.+))?$", uri)
        if not match:
            raise ValueError(f"Invalid TraceableId URI: {uri}")
        scheme, path, version = match.groups()
        return cls(scheme=IdScheme(scheme), path=path, version=version)

    # --- Factory methods for each scheme ---

    @classmethod
    def from_bdd(
        cls,
        feature: str,
        scenario: str | None = None,
        step_line: int | None = None,
        step_type: str | None = None,
    ) -> "TraceableId":
        """Create BDD traceability ID.

        Args:
            feature: Feature filename (e.g., "nifi_flow.feature")
            scenario: Optional scenario name
            step_line: Optional line number for step
            step_type: Optional step type (Given/When/Then)

        Examples:
            from_bdd("nifi_flow.feature")
            from_bdd("nifi_flow.feature", scenario="CreateBasicFlow")
            from_bdd("nifi_flow.feature", scenario="CreateBasicFlow", step_line=42, step_type="When")
        """
        path = f"features/{feature}"
        if scenario:
            path += f"#Scenario:{scenario}"
        if step_line is not None:
            path += f"/L{step_line}"
            if step_type:
                path += f":{step_type}"
        return cls(scheme=IdScheme.BDD, path=path)

    @classmethod
    def from_bdd_step_hash(cls, feature: str, step_text: str) -> "TraceableId":
        """Create BDD ID using hash of step text (stable across line moves).

        This addresses the instability of line-number-based IDs mentioned in
        section 9 of the RASE-MBSE perspective document.
        """
        normalized = " ".join(step_text.lower().split())
        step_hash = hashlib.sha1(normalized.encode()).hexdigest()[:12]
        path = f"features/{feature}#step:{step_hash}"
        return cls(scheme=IdScheme.BDD, path=path)

    @classmethod
    def from_otel(
        cls,
        trace_id: str,
        span_id: str | None = None,
        event_name: str | None = None,
    ) -> "TraceableId":
        """Create OTel traceability ID."""
        path = f"spans/{trace_id}"
        if span_id:
            path += f"/{span_id}"
        if event_name:
            path += f"/events/{event_name}"
        return cls(scheme=IdScheme.OTEL, path=path)

    @classmethod
    def from_nifi(
        cls,
        process_group_id: str,
        processor_id: str | None = None,
        connection_id: str | None = None,
    ) -> "TraceableId":
        """Create NiFi traceability ID."""
        path = f"groups/{process_group_id}"
        if processor_id:
            path += f"/processors/{processor_id}"
        elif connection_id:
            path += f"/connections/{connection_id}"
        return cls(scheme=IdScheme.NIFI, path=path)

    @classmethod
    def from_metaflow(
        cls,
        flow_name: str,
        run_id: str | None = None,
        step_name: str | None = None,
        task_id: str | None = None,
    ) -> "TraceableId":
        """Create Metaflow traceability ID."""
        path = f"flows/{flow_name}"
        if run_id:
            path += f"/runs/{run_id}"
        if step_name:
            path += f"/steps/{step_name}"
        if task_id:
            path += f"/tasks/{task_id}"
        return cls(scheme=IdScheme.METAFLOW, path=path)

    @classmethod
    def from_rase(cls, artifact_type: str, artifact_id: str) -> "TraceableId":
        """Create RASE-internal traceability ID."""
        path = f"{artifact_type}/{artifact_id}"
        return cls(scheme=IdScheme.RASE, path=path)

    @classmethod
    def generate(cls, scheme: IdScheme, prefix: str = "") -> "TraceableId":
        """Generate a new unique ID with UUID."""
        uid = uuid4().hex[:12]
        path = f"{prefix}/{uid}" if prefix else uid
        return cls(scheme=scheme, path=path)


class LinkType(str, Enum):
    """Types of traceability links between artifacts.

    These follow common MBSE relationship semantics:
    - DERIVES: Target is derived from source (requirement decomposition)
    - SATISFIES: Target satisfies/implements source requirement
    - VERIFIES: Target verification case verifies source requirement
    - ALLOCATES: Target is allocated to source (e.g., step → processor)
    - TRACES: General traceability (evidence link)
    - REFINES: Target refines source with more detail
    """
    DERIVES = "derives"
    SATISFIES = "satisfies"
    VERIFIES = "verifies"
    ALLOCATES = "allocates"
    TRACES = "traces"
    REFINES = "refines"


class TraceabilityLink(BaseModel):
    """A directed link in the traceability graph.

    Links connect artifacts across RASE models:
    - OSM scenario → VM requirement (DERIVES)
    - VM verification case → VM requirement (VERIFIES)
    - VM verification result → UOM screenshot (TRACES)

    Attributes:
        source: Source artifact ID
        target: Target artifact ID
        link_type: Semantic type of the relationship
        metadata: Additional context (timestamps, rationale, etc.)
    """

    source: TraceableId
    target: TraceableId
    link_type: LinkType
    created_at: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.source} --{self.link_type.value}--> {self.target}"


class DigitalThread(BaseModel):
    """Complete traceability chain from requirement to training sample.

    This is the "spine" that enables answering "why did the agent do this?"
    with auditable evidence. Each DigitalThread captures one complete
    verification-to-training cycle.

    The chain follows:
        Requirement → Verification Case → Execution → Evidence → Training

    Attributes:
        thread_id: Unique identifier for this thread
        requirement_id: The requirement being verified
        verification_case_id: The verification case executed
        verification_result_id: The execution result

        Evidence chain:
        - api_state_before: SSM state before execution
        - api_state_after: SSM state after execution
        - ui_screenshots: UOM screenshot IDs captured during execution
        - otel_spans: OTel span IDs for the execution

        Training artifacts:
        - training_episode_id: ID of the generated training episode
        - reward_outcome: Computed reward from verifier
        - model_checkpoint: Model version trained on this data
    """

    thread_id: TraceableId = Field(
        default_factory=lambda: TraceableId.generate(IdScheme.RASE, "threads")
    )
    created_at: datetime = Field(default_factory=datetime.now)

    # Requirement chain
    requirement_id: TraceableId
    verification_case_id: TraceableId
    verification_result_id: TraceableId | None = None

    # SSM evidence (API-derived ground truth)
    api_state_before: TraceableId | None = None
    api_state_after: TraceableId | None = None

    # UOM evidence (UI observations)
    ui_screenshots: list[TraceableId] = Field(default_factory=list)

    # OTel evidence (execution traces)
    otel_spans: list[TraceableId] = Field(default_factory=list)
    correlation_id: UUID | None = None

    # Training artifacts (if generated)
    training_episode_id: TraceableId | None = None
    reward_outcome: float | None = None
    model_checkpoint: str | None = None

    def add_evidence(
        self,
        evidence_id: TraceableId,
        evidence_type: Literal["screenshot", "span", "state_before", "state_after"],
    ) -> None:
        """Add evidence to the thread."""
        if evidence_type == "screenshot":
            self.ui_screenshots.append(evidence_id)
        elif evidence_type == "span":
            self.otel_spans.append(evidence_id)
        elif evidence_type == "state_before":
            self.api_state_before = evidence_id
        elif evidence_type == "state_after":
            self.api_state_after = evidence_id

    def to_links(self) -> list[TraceabilityLink]:
        """Generate all traceability links for this thread."""
        links = []

        # Requirement → Verification Case
        links.append(TraceabilityLink(
            source=self.requirement_id,
            target=self.verification_case_id,
            link_type=LinkType.VERIFIES,
        ))

        # Verification Case → Result
        if self.verification_result_id:
            links.append(TraceabilityLink(
                source=self.verification_case_id,
                target=self.verification_result_id,
                link_type=LinkType.TRACES,
            ))

        # Result → Evidence
        if self.verification_result_id:
            for screenshot_id in self.ui_screenshots:
                links.append(TraceabilityLink(
                    source=self.verification_result_id,
                    target=screenshot_id,
                    link_type=LinkType.TRACES,
                ))
            for span_id in self.otel_spans:
                links.append(TraceabilityLink(
                    source=self.verification_result_id,
                    target=span_id,
                    link_type=LinkType.TRACES,
                ))

        # Training artifacts
        if self.training_episode_id and self.verification_result_id:
            links.append(TraceabilityLink(
                source=self.verification_result_id,
                target=self.training_episode_id,
                link_type=LinkType.DERIVES,
                metadata={"reward": self.reward_outcome},
            ))

        return links


class TraceabilityGraph(BaseModel):
    """In-memory graph of all traceability links.

    Provides query capabilities for traceability analysis:
    - Forward tracing: What derives from this requirement?
    - Backward tracing: What requirements does this satisfy?
    - Impact analysis: What's affected if this changes?
    """

    links: list[TraceabilityLink] = Field(default_factory=list)
    threads: list[DigitalThread] = Field(default_factory=list)

    def add_link(self, link: TraceabilityLink) -> None:
        """Add a link to the graph."""
        self.links.append(link)

    def add_thread(self, thread: DigitalThread) -> None:
        """Add a digital thread and its derived links."""
        self.threads.append(thread)
        self.links.extend(thread.to_links())

    def forward_trace(self, source_id: TraceableId) -> list[TraceabilityLink]:
        """Find all links originating from the given ID."""
        return [link for link in self.links if link.source == source_id]

    def backward_trace(self, target_id: TraceableId) -> list[TraceabilityLink]:
        """Find all links pointing to the given ID."""
        return [link for link in self.links if link.target == target_id]

    def transitive_forward(
        self,
        source_id: TraceableId,
        max_depth: int = 10,
    ) -> set[TraceableId]:
        """Find all transitively reachable IDs from source."""
        visited: set[TraceableId] = set()
        frontier = {source_id}

        for _ in range(max_depth):
            if not frontier:
                break
            next_frontier: set[TraceableId] = set()
            for current in frontier:
                if current in visited:
                    continue
                visited.add(current)
                for link in self.forward_trace(current):
                    next_frontier.add(link.target)
            frontier = next_frontier - visited

        return visited - {source_id}

    def impact_analysis(self, changed_id: TraceableId) -> dict[str, list[TraceableId]]:
        """Analyze impact of a change to the given artifact.

        Returns dict mapping impact type to affected IDs:
        - "directly_affected": Immediate dependents
        - "transitively_affected": All reachable dependents
        - "verification_needed": Verification cases that need re-run
        """
        direct = {link.target for link in self.forward_trace(changed_id)}
        transitive = self.transitive_forward(changed_id)

        # Find verification cases in the affected set
        verification_needed = [
            tid for tid in transitive
            if tid.scheme == IdScheme.RASE and "verification" in tid.path
        ]

        return {
            "directly_affected": list(direct),
            "transitively_affected": list(transitive),
            "verification_needed": verification_needed,
        }


__all__ = [
    "IdScheme",
    "TraceableId",
    "LinkType",
    "TraceabilityLink",
    "DigitalThread",
    "TraceabilityGraph",
]
