"""OpenLineage Event Emission and AGE Graph Integration.

This module implements OpenLineage standard for data lineage tracking,
with optional materialization to Apache AGE graph database.

Components:
    - events: OpenLineage event dataclasses (Dataset, Job, Run, RunEvent)
    - emitter: LineageEmitter for storing events and updating graph
    - graph: AGE Cypher query helpers
    - decorators: @track_lineage decorator for automatic lineage capture
"""

from gaius.hx.lineage.events import (
    Dataset,
    Job,
    Run,
    RunEvent,
    RunState,
    DatasetFacets,
    JobFacets,
    RunFacets,
)
from gaius.hx.lineage.emitter import LineageEmitter, get_emitter

__all__ = [
    # Events
    "Dataset",
    "Job",
    "Run",
    "RunEvent",
    "RunState",
    "DatasetFacets",
    "JobFacets",
    "RunFacets",
    # Emitter
    "LineageEmitter",
    "get_emitter",
]
