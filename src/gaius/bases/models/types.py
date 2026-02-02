"""Kudu type system for Bases feature store.

Defines Kudu types as the canonical representation with PostgreSQL mappings
for the current stub implementation. When kudu_fdw is available, types will
map directly to Kudu's native type system.

Kudu Type Reference:
    https://kudu.apache.org/docs/schema_design.html#column-design

Type Hierarchy:
    KuduType (enum) - Base type enumeration
    KuduDataType - Full type specification with parameters
    TypeConverter - Conversion between Kudu and PostgreSQL types
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from datetime import date, datetime
from enum import Enum
from typing import Any, Callable


class KuduType(str, Enum):
    """Kudu column data types.

    These are the canonical types for the Bases feature store.
    All schema definitions should use these types.
    """

    # Integer types
    INT8 = "INT8"  # 8-bit signed integer
    INT16 = "INT16"  # 16-bit signed integer
    INT32 = "INT32"  # 32-bit signed integer
    INT64 = "INT64"  # 64-bit signed integer

    # Floating point types
    FLOAT = "FLOAT"  # 32-bit IEEE 754 floating point
    DOUBLE = "DOUBLE"  # 64-bit IEEE 754 floating point

    # Boolean
    BOOL = "BOOL"

    # String types
    STRING = "STRING"  # Variable-length UTF-8 encoded string
    VARCHAR = "VARCHAR"  # Variable-length UTF-8 with max length
    BINARY = "BINARY"  # Variable-length binary data

    # Temporal types
    UNIXTIME_MICROS = "UNIXTIME_MICROS"  # Microseconds since Unix epoch
    DATE = "DATE"  # Calendar date (days since Unix epoch)

    # Numeric types
    DECIMAL = "DECIMAL"  # Fixed-point decimal with precision and scale


@dataclass(frozen=True, slots=True)
class KuduDataType:
    """Full Kudu data type specification.

    Includes the base type and any type parameters (precision, scale, length).

    Examples:
        KuduDataType(KuduType.INT64)
        KuduDataType(KuduType.VARCHAR, length=255)
        KuduDataType(KuduType.DECIMAL, precision=18, scale=2)
    """

    base_type: KuduType
    precision: int | None = None  # For DECIMAL
    scale: int | None = None  # For DECIMAL
    length: int | None = None  # For VARCHAR

    def __post_init__(self) -> None:
        """Validate type parameters."""
        if self.base_type == KuduType.DECIMAL:
            if self.precision is None:
                object.__setattr__(self, "precision", 18)  # Default precision
            if self.scale is None:
                object.__setattr__(self, "scale", 0)  # Default scale
            if self.precision < 1 or self.precision > 38:  # type: ignore[operator]
                raise ValueError(f"DECIMAL precision must be 1-38, got {self.precision}")
            if self.scale < 0 or self.scale > self.precision:  # type: ignore[operator]
                raise ValueError(f"DECIMAL scale must be 0-{self.precision}, got {self.scale}")

        if self.base_type == KuduType.VARCHAR:
            if self.length is None:
                object.__setattr__(self, "length", 65535)  # Default max length
            if self.length < 1:  # type: ignore[operator]
                raise ValueError(f"VARCHAR length must be >= 1, got {self.length}")

    def __str__(self) -> str:
        """String representation matching Kudu schema syntax."""
        if self.base_type == KuduType.DECIMAL:
            return f"DECIMAL({self.precision},{self.scale})"
        elif self.base_type == KuduType.VARCHAR:
            return f"VARCHAR({self.length})"
        else:
            return self.base_type.value

    @classmethod
    def from_string(cls, type_str: str) -> KuduDataType:
        """Parse type string into KuduDataType.

        Args:
            type_str: Type string like "INT64", "DECIMAL(18,2)", "VARCHAR(255)"

        Returns:
            Parsed KuduDataType

        Raises:
            ValueError: If type string is invalid
        """
        type_str = type_str.strip().upper()

        # Handle parameterized types
        if type_str.startswith("DECIMAL("):
            # Parse DECIMAL(precision, scale)
            params = type_str[8:-1]  # Remove "DECIMAL(" and ")"
            parts = params.split(",")
            if len(parts) == 2:
                precision = int(parts[0].strip())
                scale = int(parts[1].strip())
                return cls(KuduType.DECIMAL, precision=precision, scale=scale)
            elif len(parts) == 1:
                precision = int(parts[0].strip())
                return cls(KuduType.DECIMAL, precision=precision, scale=0)
            else:
                raise ValueError(f"Invalid DECIMAL type: {type_str}")

        elif type_str.startswith("VARCHAR("):
            # Parse VARCHAR(length)
            length = int(type_str[8:-1].strip())
            return cls(KuduType.VARCHAR, length=length)

        else:
            # Simple type
            try:
                base_type = KuduType(type_str)
                return cls(base_type)
            except ValueError:
                # Try common aliases
                aliases = {
                    "INTEGER": KuduType.INT32,
                    "INT": KuduType.INT32,
                    "BIGINT": KuduType.INT64,
                    "SMALLINT": KuduType.INT16,
                    "TINYINT": KuduType.INT8,
                    "REAL": KuduType.FLOAT,
                    "FLOAT32": KuduType.FLOAT,
                    "FLOAT64": KuduType.DOUBLE,
                    "DOUBLE PRECISION": KuduType.DOUBLE,
                    "BOOLEAN": KuduType.BOOL,
                    "TEXT": KuduType.STRING,
                    "BYTEA": KuduType.BINARY,
                    "TIMESTAMP": KuduType.UNIXTIME_MICROS,
                    "TIMESTAMPTZ": KuduType.UNIXTIME_MICROS,
                    "TIMESTAMP WITH TIME ZONE": KuduType.UNIXTIME_MICROS,
                }
                if type_str in aliases:
                    return cls(aliases[type_str])
                raise ValueError(f"Unknown type: {type_str}")


# PostgreSQL type mappings
_KUDU_TO_POSTGRES: dict[KuduType, str] = {
    KuduType.INT8: "SMALLINT",  # PostgreSQL doesn't have INT1, use SMALLINT
    KuduType.INT16: "SMALLINT",
    KuduType.INT32: "INTEGER",
    KuduType.INT64: "BIGINT",
    KuduType.FLOAT: "REAL",
    KuduType.DOUBLE: "DOUBLE PRECISION",
    KuduType.BOOL: "BOOLEAN",
    KuduType.STRING: "TEXT",
    KuduType.VARCHAR: "VARCHAR",  # Will have length appended
    KuduType.BINARY: "BYTEA",
    KuduType.UNIXTIME_MICROS: "TIMESTAMP WITH TIME ZONE",
    KuduType.DATE: "DATE",
    KuduType.DECIMAL: "NUMERIC",  # Will have precision/scale appended
}

_POSTGRES_TO_KUDU: dict[str, KuduType] = {
    "SMALLINT": KuduType.INT16,
    "INT2": KuduType.INT16,
    "INTEGER": KuduType.INT32,
    "INT": KuduType.INT32,
    "INT4": KuduType.INT32,
    "BIGINT": KuduType.INT64,
    "INT8": KuduType.INT64,  # PostgreSQL INT8 = BIGINT, not Kudu INT8
    "REAL": KuduType.FLOAT,
    "FLOAT4": KuduType.FLOAT,
    "DOUBLE PRECISION": KuduType.DOUBLE,
    "FLOAT8": KuduType.DOUBLE,
    "BOOLEAN": KuduType.BOOL,
    "BOOL": KuduType.BOOL,
    "TEXT": KuduType.STRING,
    "VARCHAR": KuduType.VARCHAR,
    "CHARACTER VARYING": KuduType.VARCHAR,
    "CHAR": KuduType.STRING,
    "CHARACTER": KuduType.STRING,
    "BYTEA": KuduType.BINARY,
    "TIMESTAMP WITH TIME ZONE": KuduType.UNIXTIME_MICROS,
    "TIMESTAMPTZ": KuduType.UNIXTIME_MICROS,
    "TIMESTAMP WITHOUT TIME ZONE": KuduType.UNIXTIME_MICROS,
    "TIMESTAMP": KuduType.UNIXTIME_MICROS,
    "DATE": KuduType.DATE,
    "NUMERIC": KuduType.DECIMAL,
    "DECIMAL": KuduType.DECIMAL,
}


class TypeConverter:
    """Convert between Kudu types and PostgreSQL types.

    This is the stub implementation using PostgreSQL. When kudu_fdw
    becomes available, this will route to native Kudu types.
    """

    @staticmethod
    def kudu_to_postgres(kudu_type: KuduDataType) -> str:
        """Convert Kudu type to PostgreSQL type string.

        Args:
            kudu_type: Kudu data type

        Returns:
            PostgreSQL type string for CREATE TABLE / CAST
        """
        base_pg = _KUDU_TO_POSTGRES[kudu_type.base_type]

        if kudu_type.base_type == KuduType.DECIMAL:
            return f"NUMERIC({kudu_type.precision},{kudu_type.scale})"
        elif kudu_type.base_type == KuduType.VARCHAR:
            return f"VARCHAR({kudu_type.length})"
        else:
            return base_pg

    @staticmethod
    def postgres_to_kudu(pg_type: str) -> KuduDataType:
        """Convert PostgreSQL type string to Kudu type.

        Args:
            pg_type: PostgreSQL type string

        Returns:
            Equivalent Kudu data type
        """
        pg_type = pg_type.strip().upper()

        # Handle parameterized types
        if pg_type.startswith("NUMERIC(") or pg_type.startswith("DECIMAL("):
            params = pg_type.split("(")[1].rstrip(")")
            parts = params.split(",")
            precision = int(parts[0].strip())
            scale = int(parts[1].strip()) if len(parts) > 1 else 0
            return KuduDataType(KuduType.DECIMAL, precision=precision, scale=scale)

        elif pg_type.startswith("VARCHAR(") or pg_type.startswith("CHARACTER VARYING("):
            length = int(pg_type.split("(")[1].rstrip(")"))
            return KuduDataType(KuduType.VARCHAR, length=length)

        elif pg_type.startswith("CHAR(") or pg_type.startswith("CHARACTER("):
            # Fixed-length char maps to STRING
            return KuduDataType(KuduType.STRING)

        else:
            # Simple type lookup
            if pg_type in _POSTGRES_TO_KUDU:
                return KuduDataType(_POSTGRES_TO_KUDU[pg_type])

            # Try without parameters for types like "NUMERIC"
            base_type = pg_type.split("(")[0].strip()
            if base_type in _POSTGRES_TO_KUDU:
                return KuduDataType(_POSTGRES_TO_KUDU[base_type])

            raise ValueError(f"Unknown PostgreSQL type: {pg_type}")

    @staticmethod
    def coerce_value(value: Any, kudu_type: KuduDataType) -> Any:
        """Coerce a Python value to match the Kudu type.

        Used when processing query results to ensure type consistency.

        Args:
            value: Raw value from database
            kudu_type: Expected Kudu type

        Returns:
            Coerced value
        """
        if value is None:
            return None

        base = kudu_type.base_type

        # Integer types
        if base in (KuduType.INT8, KuduType.INT16, KuduType.INT32, KuduType.INT64):
            return int(value)

        # Float types
        elif base in (KuduType.FLOAT, KuduType.DOUBLE):
            return float(value)

        # Boolean
        elif base == KuduType.BOOL:
            if isinstance(value, bool):
                return value
            return bool(value)

        # String types
        elif base in (KuduType.STRING, KuduType.VARCHAR):
            return str(value)

        # Binary
        elif base == KuduType.BINARY:
            if isinstance(value, bytes):
                return value
            elif isinstance(value, memoryview):
                return bytes(value)
            return bytes(value)

        # Timestamp
        elif base == KuduType.UNIXTIME_MICROS:
            if isinstance(value, datetime):
                return value
            elif isinstance(value, (int, float)):
                # Assume microseconds since epoch
                return datetime.fromtimestamp(value / 1_000_000)
            return value

        # Date
        elif base == KuduType.DATE:
            if isinstance(value, date):
                return value
            elif isinstance(value, datetime):
                return value.date()
            return value

        # Decimal
        elif base == KuduType.DECIMAL:
            if isinstance(value, Decimal):
                return value
            return Decimal(str(value))

        return value


# Convenience functions for common types
def int8() -> KuduDataType:
    """Create INT8 type."""
    return KuduDataType(KuduType.INT8)


def int16() -> KuduDataType:
    """Create INT16 type."""
    return KuduDataType(KuduType.INT16)


def int32() -> KuduDataType:
    """Create INT32 type."""
    return KuduDataType(KuduType.INT32)


def int64() -> KuduDataType:
    """Create INT64 type."""
    return KuduDataType(KuduType.INT64)


def float32() -> KuduDataType:
    """Create FLOAT type."""
    return KuduDataType(KuduType.FLOAT)


def float64() -> KuduDataType:
    """Create DOUBLE type."""
    return KuduDataType(KuduType.DOUBLE)


def boolean() -> KuduDataType:
    """Create BOOL type."""
    return KuduDataType(KuduType.BOOL)


def string() -> KuduDataType:
    """Create STRING type."""
    return KuduDataType(KuduType.STRING)


def varchar(length: int = 65535) -> KuduDataType:
    """Create VARCHAR type with specified length."""
    return KuduDataType(KuduType.VARCHAR, length=length)


def binary() -> KuduDataType:
    """Create BINARY type."""
    return KuduDataType(KuduType.BINARY)


def timestamp() -> KuduDataType:
    """Create UNIXTIME_MICROS type."""
    return KuduDataType(KuduType.UNIXTIME_MICROS)


def date_type() -> KuduDataType:
    """Create DATE type."""
    return KuduDataType(KuduType.DATE)


def decimal(precision: int = 18, scale: int = 0) -> KuduDataType:
    """Create DECIMAL type with specified precision and scale."""
    return KuduDataType(KuduType.DECIMAL, precision=precision, scale=scale)
