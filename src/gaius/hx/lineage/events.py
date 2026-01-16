"""OpenLineage Event Definitions.

Implements the OpenLineage standard for data lineage events:
https://openlineage.io/spec/2-0-0/OpenLineage.json

Events track the flow of data through processing pipelines:
- Dataset: A data source or sink (e.g., Iceberg table, KB file, Qdrant collection)
- Job: A processing step (e.g., fetch, summarize, embed)
- Run: A specific execution of a Job
- RunEvent: State changes during a Run (START, COMPLETE, FAIL)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class RunState(Enum):
    """State of a run execution."""
    START = "START"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAIL = "FAIL"
    ABORT = "ABORT"


@dataclass
class DatasetFacets:
    """Facets (metadata) for a Dataset.

    Standard OpenLineage facets include:
    - schema: Column names and types
    - dataSource: Connection details
    - documentation: Human-readable description
    - ownership: Data ownership info
    """

    schema: dict | None = None
    data_source: dict | None = None
    documentation: str | None = None
    ownership: dict | None = None
    custom: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to OpenLineage JSON format."""
        result = {}
        if self.schema:
            result["schema"] = self.schema
        if self.data_source:
            result["dataSource"] = self.data_source
        if self.documentation:
            result["documentation"] = {"description": self.documentation}
        if self.ownership:
            result["ownership"] = self.ownership
        result.update(self.custom)
        return result


@dataclass
class Dataset:
    """A data source or sink in the lineage graph.

    Namespaces follow the pattern:
    - gaius.source: External data sources (arxiv, rss, docs)
    - gaius.hx: Raw content in Iceberg (hx:raw:{id})
    - gaius.kb: KB markdown files (kb:{path})
    - gaius.qdrant: Vector embeddings (qdrant:{collection}:{id})
    - gaius.thought: Generated thoughts (thought:{id})
    """

    namespace: str
    name: str
    facets: DatasetFacets = field(default_factory=DatasetFacets)

    def to_dict(self) -> dict:
        """Convert to OpenLineage JSON format."""
        result = {
            "namespace": self.namespace,
            "name": self.name,
        }
        facets = self.facets.to_dict()
        if facets:
            result["facets"] = facets
        return result

    @classmethod
    def from_source(cls, source_name: str, source_type: str) -> Dataset:
        """Create Dataset for an external source."""
        return cls(
            namespace="gaius.source",
            name=f"{source_type}:{source_name}",
        )

    @classmethod
    def from_hx(cls, content_id: str, table: str = "raw.content") -> Dataset:
        """Create Dataset for HX Iceberg content."""
        return cls(
            namespace="gaius.hx",
            name=f"{table}:{content_id}",
        )

    @classmethod
    def from_kb(cls, kb_path: str) -> Dataset:
        """Create Dataset for KB file."""
        return cls(
            namespace="gaius.kb",
            name=kb_path,
        )

    @classmethod
    def from_qdrant(cls, collection: str, point_id: str) -> Dataset:
        """Create Dataset for Qdrant embedding."""
        return cls(
            namespace="gaius.qdrant",
            name=f"{collection}:{point_id}",
        )

    @classmethod
    def from_thought(cls, thought_id: str) -> Dataset:
        """Create Dataset for a thought."""
        return cls(
            namespace="gaius.thought",
            name=thought_id,
        )

    @classmethod
    def from_fmp(
        cls,
        endpoint: str,
        symbol: str | None = None,
        exchange_id: str | None = None,
    ) -> Dataset:
        """Create Dataset for an FMP API exchange.

        Args:
            endpoint: FMP endpoint type (sec-filings, institutional-holder, etc.)
            symbol: Stock symbol if applicable.
            exchange_id: Exchange record ID for specific record reference.

        Returns:
            Dataset with namespace gaius.fmp.
        """
        if exchange_id:
            name = f"{endpoint}:{symbol or 'unknown'}:{exchange_id}"
        elif symbol:
            name = f"{endpoint}:{symbol}"
        else:
            name = endpoint
        return cls(
            namespace="gaius.fmp",
            name=name,
        )

    @classmethod
    def from_exchange(
        cls,
        provider: str,
        request_hash: str | None = None,
        exchange_id: str | None = None,
    ) -> Dataset:
        """Create Dataset for a generic API exchange record.

        Args:
            provider: API provider (xai, cerebras, bytez, brave, fmp).
            request_hash: Request hash for deduplication reference.
            exchange_id: Exchange record ID.

        Returns:
            Dataset with namespace gaius.exchange.
        """
        if exchange_id:
            name = f"{provider}:{exchange_id}"
        elif request_hash:
            name = f"{provider}:{request_hash[:16]}"  # Truncated for readability
        else:
            name = provider
        return cls(
            namespace="gaius.exchange",
            name=name,
        )


@dataclass
class JobFacets:
    """Facets (metadata) for a Job."""

    documentation: str | None = None
    source_code: dict | None = None
    sql: str | None = None
    custom: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to OpenLineage JSON format."""
        result = {}
        if self.documentation:
            result["documentation"] = {"description": self.documentation}
        if self.source_code:
            result["sourceCode"] = self.source_code
        if self.sql:
            result["sql"] = {"query": self.sql}
        result.update(self.custom)
        return result


@dataclass
class Job:
    """A processing step in the lineage graph.

    Namespaces follow the pattern:
    - gaius.fetch: Content fetching (fetch.arxiv, fetch.rss)
    - gaius.summarize: Content summarization (summarize.batch)
    - gaius.embed: Embedding generation (embed.kb)
    - gaius.agent: Agent execution (agent.swarm, agent.cognition)
    """

    namespace: str
    name: str
    facets: JobFacets = field(default_factory=JobFacets)

    def to_dict(self) -> dict:
        """Convert to OpenLineage JSON format."""
        result = {
            "namespace": self.namespace,
            "name": self.name,
        }
        facets = self.facets.to_dict()
        if facets:
            result["facets"] = facets
        return result

    @classmethod
    def fetch(cls, source_type: str) -> Job:
        """Create Job for content fetching."""
        return cls(
            namespace="gaius.fetch",
            name=source_type,
        )

    @classmethod
    def summarize(cls, batch_name: str = "batch") -> Job:
        """Create Job for content summarization."""
        return cls(
            namespace="gaius.summarize",
            name=batch_name,
        )

    @classmethod
    def embed(cls, target: str = "kb") -> Job:
        """Create Job for embedding generation."""
        return cls(
            namespace="gaius.embed",
            name=target,
        )

    @classmethod
    def agent(cls, agent_type: str) -> Job:
        """Create Job for agent execution."""
        return cls(
            namespace="gaius.agent",
            name=agent_type,
        )

    @classmethod
    def fmp_fetch(cls, endpoint: str) -> Job:
        """Create Job for FMP API fetching.

        Args:
            endpoint: FMP endpoint type (sec-filings, holdings, profile, etc.)
        """
        return cls(
            namespace="gaius.fetch.fmp",
            name=endpoint,
        )

    @classmethod
    def prospects(cls, operation: str) -> Job:
        """Create Job for prospects/stewardship operations.

        Args:
            operation: Operation type (check, update, analyze, synthesize).
        """
        return cls(
            namespace="gaius.prospects",
            name=operation,
        )


@dataclass
class RunFacets:
    """Facets (metadata) for a Run."""

    error_message: str | None = None
    nominal_time: datetime | None = None
    parent_run: dict | None = None
    custom: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to OpenLineage JSON format."""
        result = {}
        if self.error_message:
            result["errorMessage"] = {
                "message": self.error_message,
                "programmingLanguage": "python",
            }
        if self.nominal_time:
            result["nominalTime"] = {
                "nominalStartTime": self.nominal_time.isoformat(),
            }
        if self.parent_run:
            result["parent"] = self.parent_run
        result.update(self.custom)
        return result


@dataclass
class Run:
    """A specific execution of a Job."""

    run_id: UUID = field(default_factory=uuid4)
    facets: RunFacets = field(default_factory=RunFacets)

    def to_dict(self) -> dict:
        """Convert to OpenLineage JSON format."""
        result = {
            "runId": str(self.run_id),
        }
        facets = self.facets.to_dict()
        if facets:
            result["facets"] = facets
        return result

    @classmethod
    def with_parent(cls, parent_run_id: UUID) -> Run:
        """Create a Run with a parent relationship."""
        return cls(
            facets=RunFacets(
                parent_run={
                    "run": {"runId": str(parent_run_id)},
                    "job": {},  # Filled in by emitter
                }
            )
        )


@dataclass
class RunEvent:
    """An event recording a state change in a Run.

    This is the primary event type in OpenLineage, capturing:
    - When a job run starts (START)
    - When it completes successfully (COMPLETE)
    - When it fails (FAIL)
    - Intermediate states (RUNNING)
    """

    event_type: str = "RunEvent"
    event_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    run: Run = field(default_factory=Run)
    job: Job = field(default_factory=lambda: Job(namespace="gaius", name="unknown"))
    inputs: list[Dataset] = field(default_factory=list)
    outputs: list[Dataset] = field(default_factory=list)
    run_state: RunState = RunState.START

    def to_dict(self) -> dict:
        """Convert to OpenLineage JSON format."""
        return {
            "eventType": self.event_type,
            "eventTime": self.event_time.isoformat(),
            "run": self.run.to_dict(),
            "job": self.job.to_dict(),
            "inputs": [d.to_dict() for d in self.inputs],
            "outputs": [d.to_dict() for d in self.outputs],
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def start(
        cls,
        job: Job,
        inputs: list[Dataset],
        run: Run | None = None,
        parent_run_id: UUID | None = None,
    ) -> RunEvent:
        """Create a START event for a job run."""
        if run is None:
            if parent_run_id:
                run = Run.with_parent(parent_run_id)
            else:
                run = Run()

        return cls(
            run=run,
            job=job,
            inputs=inputs,
            outputs=[],
            run_state=RunState.START,
        )

    @classmethod
    def complete(
        cls,
        run: Run,
        job: Job,
        inputs: list[Dataset],
        outputs: list[Dataset],
    ) -> RunEvent:
        """Create a COMPLETE event for a job run."""
        return cls(
            run=run,
            job=job,
            inputs=inputs,
            outputs=outputs,
            run_state=RunState.COMPLETE,
        )

    @classmethod
    def fail(
        cls,
        run: Run,
        job: Job,
        inputs: list[Dataset],
        error_message: str,
    ) -> RunEvent:
        """Create a FAIL event for a job run."""
        run.facets.error_message = error_message
        return cls(
            run=run,
            job=job,
            inputs=inputs,
            outputs=[],
            run_state=RunState.FAIL,
        )
