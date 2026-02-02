"""Data models for Bases feature store."""

from gaius.bases.models.base import BaseDefinition, BaseType
from gaius.bases.models.feature import EntityType, Feature, FeatureGroup
from gaius.bases.models.schema import ColumnSchema, QueryResult, EntityHistoryResult
from gaius.bases.models.types import (
    KuduType,
    KuduDataType,
    TypeConverter,
    # Convenience type constructors
    int8,
    int16,
    int32,
    int64,
    float32,
    float64,
    boolean,
    string,
    varchar,
    binary,
    timestamp,
    date_type,
    decimal,
)

__all__ = [
    # Base and schema models
    "BaseDefinition",
    "BaseType",
    "ColumnSchema",
    "EntityType",
    "Feature",
    "FeatureGroup",
    "QueryResult",
    "EntityHistoryResult",
    # Kudu type system
    "KuduType",
    "KuduDataType",
    "TypeConverter",
    # Type constructors
    "int8",
    "int16",
    "int32",
    "int64",
    "float32",
    "float64",
    "boolean",
    "string",
    "varchar",
    "binary",
    "timestamp",
    "date_type",
    "decimal",
]
