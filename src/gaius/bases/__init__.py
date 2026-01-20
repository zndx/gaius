"""Bases: Dataview-style Feature Store.

A feature store with Obsidian Dataview semantics, exposing data through typed Bases
that abstract away the underlying storage backends (PostgreSQL registry, Iceberg offline,
Pinot online).

MCP Tools:
- list_bases(): List available bases with metadata
- query_base(): Execute DQL queries against bases
- get_entity_history(): Get event-sourced history for an entity

DQL Syntax (Dataview Query Language):
- WHERE <expression>: Filter rows
- ORDER BY <col> [ASC|DESC]: Sort results
- LIMIT <n>: Limit rows returned
- AS OF "<timestamp>": Time-travel (historical bases only)
- GROUP BY <col>: Group rows

Example:
    >>> result = await query_base(
    ...     "user_features",
    ...     "WHERE age > 25 AND region = 'US' ORDER BY created_at DESC LIMIT 100"
    ... )
"""

from gaius.bases.models import (
    BaseDefinition,
    BaseType,
    ColumnSchema,
    EntityType,
    Feature,
    FeatureGroup,
    QueryResult,
    EntityHistoryResult,
)
from gaius.bases.dql import parse_dql, DQLQuery
from gaius.bases.service import BasesService, BasesConfig

__all__ = [
    # Models
    "BaseDefinition",
    "BaseType",
    "ColumnSchema",
    "EntityType",
    "Feature",
    "FeatureGroup",
    "QueryResult",
    "EntityHistoryResult",
    # DQL
    "parse_dql",
    "DQLQuery",
    # Service
    "BasesService",
    "BasesConfig",
]
